import httpx
from models.schemas import FileChange

# Files we want to skip — they don't contain meaningful logic
SKIP_EXTENSIONS = {".lock", ".min.js", ".min.css", ".map", ".svg", ".png", ".jpg"}
SKIP_FILENAMES = {"package-lock.json", "yarn.lock", "pnpm-lock.yaml", "poetry.lock"}

# Map file extensions to language names (Tree-sitter needs this later)
EXTENSION_TO_LANGUAGE = {
    ".py": "python",
    ".js": "javascript",
    ".ts": "typescript",
    ".go": "go",
    ".java": "java",
    ".rb": "ruby",
}


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
    return False


def parse_diff(raw_diff: str) -> list[FileChange]:
    files = []
    current_file = None
    current_hunks = []
    added_lines = []

    for line in raw_diff.split("\n"):
        if line.startswith("diff --git"):
            if current_file and not should_skip(current_file):
                files.append(FileChange(
                    filename=current_file,
                    language=get_language(current_file),
                    hunks="\n".join(current_hunks),
                    added_lines=added_lines,
                ))
            parts = line.split(" b/")
            current_file = parts[-1] if len(parts) > 1 else None
            current_hunks = []
            added_lines = []

        elif current_file:
            current_hunks.append(line)
            if line.startswith("+") and not line.startswith("+++"):
                added_lines.append(line[1:])

    if current_file and not should_skip(current_file):
        files.append(FileChange(
            filename=current_file,
            language=get_language(current_file),
            hunks="\n".join(current_hunks),
            added_lines=added_lines,
        ))

    return files


async def fetch_diff(owner: str, repo: str, pr_number: int, github_token: str) -> list[FileChange]:
    url = f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr_number}"
    headers = {
        "Authorization": f"token {github_token}",
        "Accept": "application/vnd.github.v3.diff",
    }

    async with httpx.AsyncClient() as client:
        response = await client.get(url, headers=headers)
        response.raise_for_status()
        raw_diff = response.text

    return parse_diff(raw_diff)
