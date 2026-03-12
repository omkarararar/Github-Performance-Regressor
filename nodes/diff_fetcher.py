import re
import httpx
import asyncio
from models.schemas import FileChange
from logger import get_logger

log = get_logger("diff_fetcher")

# Files we want to skip
SKIP_EXTENSIONS = {".lock", ".min.js", ".min.css", ".map", ".svg", ".png", ".jpg", ".gif", ".ico", ".woff", ".woff2", ".ttf", ".eot"}
SKIP_FILENAMES = {"package-lock.json", "yarn.lock", "pnpm-lock.yaml", "poetry.lock", "Pipfile.lock", "composer.lock", "Gemfile.lock", "go.sum"}
SKIP_DIRS = {"node_modules/", "vendor/", "dist/", "build/", "__pycache__/", ".git/"}

EXTENSION_TO_LANGUAGE = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".go": "go",
    ".java": "java",
    ".rb": "ruby",
    ".rs": "rust",
    ".cpp": "cpp",
    ".c": "c",
    ".cs": "csharp",
    ".php": "php",
    ".kt": "kotlin",
    ".swift": "swift",
}

MAX_RETRIES = 3
RETRY_DELAYS = [1, 2, 4]  # exponential backoff in seconds
MAX_FILE_SIZE = 500_000  # 500KB — skip files larger than this


def get_language(filename: str) -> str:
    for ext, lang in EXTENSION_TO_LANGUAGE.items():
        if filename.endswith(ext):
            return lang
    return "unknown"


def should_skip(filename: str) -> bool:
    if filename in SKIP_FILENAMES:
        return True
    for ext in SKIP_EXTENSIONS:
        if filename.endswith(ext):
            return True
    for skip_dir in SKIP_DIRS:
        if skip_dir in filename:
            return True
    return False


def _is_binary_diff(hunk_lines: list[str]) -> bool:
    """Detect if a diff section represents a binary file."""
    for line in hunk_lines[:5]:
        if "Binary files" in line or "GIT binary patch" in line:
            return True
    return False


def parse_diff(raw_diff: str) -> list[FileChange]:
    """Parse a unified diff string into FileChange objects with line number tracking."""
    files = []
    current_file = None
    current_hunks = []
    added_lines = []
    line_numbers = []
    current_new_line = 0

    for line in raw_diff.split("\n"):
        if line.startswith("diff --git"):
            # Save previous file
            if current_file and not should_skip(current_file):
                if not _is_binary_diff(current_hunks):
                    files.append(FileChange(
                        filename=current_file,
                        language=get_language(current_file),
                        hunks="\n".join(current_hunks),
                        added_lines=added_lines,
                        line_numbers=line_numbers,
                    ))
                else:
                    log.info(f"Skipping binary file: {current_file}")

            parts = line.split(" b/")
            current_file = parts[-1] if len(parts) > 1 else None
            current_hunks = []
            added_lines = []
            line_numbers = []
            current_new_line = 0

        elif current_file:
            current_hunks.append(line)

            # Parse hunk header to get starting line number
            hunk_match = re.match(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@", line)
            if hunk_match:
                current_new_line = int(hunk_match.group(1))
                continue

            if line.startswith("+") and not line.startswith("+++"):
                added_lines.append(line[1:])
                line_numbers.append(current_new_line)
                current_new_line += 1
            elif line.startswith("-") and not line.startswith("---"):
                pass  # deleted lines don't increment new file line counter
            else:
                current_new_line += 1  # context lines increment counter

    # Don't forget the last file
    if current_file and not should_skip(current_file):
        if not _is_binary_diff(current_hunks):
            files.append(FileChange(
                filename=current_file,
                language=get_language(current_file),
                hunks="\n".join(current_hunks),
                added_lines=added_lines,
                line_numbers=line_numbers,
            ))

    log.info(f"Parsed {len(files)} files from diff")
    return files


async def _request_with_retry(client: httpx.AsyncClient, method: str, url: str, headers: dict, **kwargs) -> httpx.Response:
    """Make an HTTP request with exponential backoff retry."""
    last_error = None

    for attempt in range(MAX_RETRIES):
        try:
            response = await client.request(method, url, headers=headers, **kwargs)

            if response.status_code == 403:
                log.error(f"Access denied (403) for {url} — check GitHub token permissions")
                response.raise_for_status()
            elif response.status_code == 404:
                log.error(f"Not found (404) for {url} — check repo/PR exists")
                response.raise_for_status()
            elif response.status_code == 422:
                log.error(f"Unprocessable (422) for {url} — diff may be too large")
                response.raise_for_status()
            elif response.status_code == 429:
                retry_after = int(response.headers.get("Retry-After", RETRY_DELAYS[attempt]))
                log.warning(f"Rate limited (429). Retrying in {retry_after}s (attempt {attempt + 1}/{MAX_RETRIES})")
                await asyncio.sleep(retry_after)
                continue

            response.raise_for_status()
            return response

        except httpx.HTTPStatusError as e:
            last_error = e
            if attempt < MAX_RETRIES - 1 and e.response.status_code >= 500:
                delay = RETRY_DELAYS[attempt]
                log.warning(f"Server error ({e.response.status_code}). Retrying in {delay}s (attempt {attempt + 1}/{MAX_RETRIES})")
                await asyncio.sleep(delay)
            else:
                raise

        except httpx.RequestError as e:
            last_error = e
            if attempt < MAX_RETRIES - 1:
                delay = RETRY_DELAYS[attempt]
                log.warning(f"Request failed: {e}. Retrying in {delay}s (attempt {attempt + 1}/{MAX_RETRIES})")
                await asyncio.sleep(delay)
            else:
                raise

    raise last_error


async def fetch_file_content(client: httpx.AsyncClient, owner: str, repo: str, filepath: str, ref: str, headers: dict) -> str:
    """Fetch the full content of a file from GitHub (needed for AST parsing)."""
    url = f"https://api.github.com/repos/{owner}/{repo}/contents/{filepath}?ref={ref}"
    content_headers = {**headers, "Accept": "application/vnd.github.v3.raw"}

    try:
        response = await _request_with_retry(client, "GET", url, headers=content_headers)
        content = response.text

        if len(content) > MAX_FILE_SIZE:
            log.warning(f"File {filepath} too large ({len(content)} bytes), skipping full source")
            return ""

        return content
    except Exception as e:
        log.error(f"Failed to fetch content for {filepath}: {e}")
        return ""


async def fetch_diff(owner: str, repo: str, pr_number: int, github_token: str) -> list[FileChange]:
    """
    Main entry point for Node 1.
    Fetches PR diff, parses it, then fetches full file contents for AST parsing.
    """
    diff_url = f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr_number}"
    headers = {
        "Authorization": f"token {github_token}",
        "Accept": "application/vnd.github.v3.diff",
    }

    log.info(f"Fetching diff for {owner}/{repo} PR #{pr_number}")

    async with httpx.AsyncClient(timeout=30.0) as client:
        # Fetch the diff
        response = await _request_with_retry(client, "GET", diff_url, headers=headers)
        raw_diff = response.text
        file_changes = parse_diff(raw_diff)

        # Fetch full file contents for each changed file
        # Get the PR head ref for fetching files
        pr_url = f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr_number}"
        pr_headers = {**headers, "Accept": "application/vnd.github.v3+json"}
        pr_response = await _request_with_retry(client, "GET", pr_url, headers=pr_headers)
        pr_data = pr_response.json()
        head_sha = pr_data.get("head", {}).get("sha", "")

        if head_sha:
            for fc in file_changes:
                if fc.language != "unknown":
                    log.info(f"Fetching full content for {fc.filename}")
                    fc.full_source = await fetch_file_content(client, owner, repo, fc.filename, head_sha, headers)
        else:
            log.warning("Could not determine PR head SHA — skipping full file fetch")

    log.info(f"Node 1 complete: {len(file_changes)} files, {sum(len(fc.added_lines) for fc in file_changes)} added lines")
    return file_changes
