import time
from github import Github, GithubException, RateLimitExceededException
from config import GITHUB_TOKEN
from models.schemas import Finding
from logger import get_logger

log = get_logger("responder")

SEVERITY_BADGES = {
    "High": "🔴 **HIGH**",
    "Medium": "🟡 **MEDIUM**",
    "Low": "🟢 **LOW**",
}


def format_comment(finding: Finding) -> str:
    badge = SEVERITY_BADGES.get(finding.severity, "⚪ **UNKNOWN**")

    return f"""{badge} — {finding.pattern}

{finding.explanation}

**Suggested fix:**
```
{finding.suggested_fix}
```"""


def _wait_for_rate_limit(g: Github):
    """Check GitHub rate limit and wait if necessary."""
    rate = g.get_rate_limit().core
    if rate.remaining < 10:
        reset_time = rate.reset.timestamp()
        wait_seconds = max(0, reset_time - time.time()) + 1
        log.warning(f"GitHub rate limit low ({rate.remaining} remaining). Waiting {wait_seconds:.0f}s until reset.")
        time.sleep(wait_seconds)


def post_review(owner: str, repo: str, pr_number: int, findings: list[Finding], commit_sha: str) -> dict:
    """
    Main entry point for Node 6.
    Posts a single review with inline comments on the PR and sets commit status.
    """
    if not findings:
        log.info("No findings to post")
        return {"status": "clean", "comments_posted": 0}

    if not GITHUB_TOKEN:
        log.error("GITHUB_TOKEN not set — skipping review posting")
        return {"status": "error", "message": "No GitHub token configured"}

    try:
        g = Github(GITHUB_TOKEN)
        _wait_for_rate_limit(g)
        repository = g.get_repo(f"{owner}/{repo}")
        pr = repository.get_pull(pr_number)
        commit = repository.get_commit(commit_sha)
    except GithubException as e:
        log.error(f"Failed to connect to GitHub repo {owner}/{repo}: {e}")
        return {"status": "error", "message": str(e)}

    comments_posted = 0
    failed_comments = 0

    # Post inline comments using the review API (single review, batch comments)
    review_comments = []
    for finding in findings:
        body = format_comment(finding)
        review_comments.append({
            "path": finding.file,
            "line": finding.line,
            "body": body,
        })

    # Try batch review first (more efficient)
    try:
        _wait_for_rate_limit(g)
        pr.create_review(
            commit=commit,
            event="COMMENT",
            comments=[
                {"path": c["path"], "line": c["line"], "body": c["body"]}
                for c in review_comments
            ],
        )
        comments_posted = len(review_comments)
        log.info(f"Posted batch review with {comments_posted} inline comments")

    except GithubException as e:
        log.warning(f"Batch review failed ({e}), falling back to individual comments")

        # Fallback: post individual comments
        for comment in review_comments:
            try:
                _wait_for_rate_limit(g)
                pr.create_review_comment(
                    body=comment["body"],
                    commit=commit,
                    path=comment["path"],
                    line=comment["line"],
                )
                comments_posted += 1
            except RateLimitExceededException:
                _wait_for_rate_limit(g)
                try:
                    pr.create_review_comment(
                        body=comment["body"],
                        commit=commit,
                        path=comment["path"],
                        line=comment["line"],
                    )
                    comments_posted += 1
                except Exception as e2:
                    log.error(f"Failed to post comment on {comment['path']}:{comment['line']}: {e2}")
                    failed_comments += 1
            except GithubException as e:
                log.error(f"Failed to post comment on {comment['path']}:{comment['line']}: {e}")
                failed_comments += 1

    # Post summary comment
    try:
        summary = build_summary(findings)
        _wait_for_rate_limit(g)
        pr.create_issue_comment(summary)
        log.info("Posted summary comment")
    except GithubException as e:
        log.error(f"Failed to post summary comment: {e}")

    # Set commit status
    has_high = any(f.severity == "High" for f in findings)
    status = "failure" if has_high else "success"

    try:
        _wait_for_rate_limit(g)
        commit.create_status(
            state=status,
            description=f"Found {len(findings)} performance issue(s)",
            context="performance-regressor",
        )
        log.info(f"Set commit status: {status}")
    except GithubException as e:
        log.error(f"Failed to set commit status: {e}")

    result = {
        "status": status,
        "comments_posted": comments_posted,
        "comments_failed": failed_comments,
        "total_findings": len(findings),
        "high": sum(1 for f in findings if f.severity == "High"),
        "medium": sum(1 for f in findings if f.severity == "Medium"),
        "low": sum(1 for f in findings if f.severity == "Low"),
    }
    log.info(f"Node 6 complete: {result}")
    return result


def build_summary(findings: list[Finding]) -> str:
    high = [f for f in findings if f.severity == "High"]
    medium = [f for f in findings if f.severity == "Medium"]
    low = [f for f in findings if f.severity == "Low"]

    lines = ["## 🔍 Performance Review Summary\n"]

    if high:
        lines.append(f"🔴 **{len(high)} High** severity issue(s) — **merge blocked**")
    if medium:
        lines.append(f"🟡 **{len(medium)} Medium** severity issue(s)")
    if low:
        lines.append(f"🟢 **{len(low)} Low** severity issue(s)")

    lines.append("\n### Findings\n")
    lines.append("| # | Severity | File | Line | Pattern |")
    lines.append("|---|----------|------|------|---------|")

    for i, f in enumerate(findings, 1):
        badge = SEVERITY_BADGES.get(f.severity, "⚪")
        lines.append(f"| {i} | {badge} | `{f.file}` | {f.line} | {f.pattern} |")

    if high:
        lines.append("\n> ⚠️ **This PR has been blocked from merging** due to high severity performance issues.")
    else:
        lines.append("\n> ✅ No blocking issues found. Please review the warnings above.")

    return "\n".join(lines)
