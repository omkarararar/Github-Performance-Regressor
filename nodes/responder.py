from github import Github
from config import GITHUB_TOKEN
from models.schemas import Finding


SEVERITY_BADGES = {
    "High": "🔴 **HIGH**",
    "Medium": "🟡 **MEDIUM**",
    "Low": "🟢 **LOW**",
}


def format_comment(finding: Finding) -> str:
    """Format a single finding into a GitHub PR review comment."""
    badge = SEVERITY_BADGES.get(finding.severity, "⚪ **UNKNOWN**")

    return f"""{badge} — {finding.pattern}

{finding.explanation}

**Suggested fix:**
```
{finding.suggested_fix}
```"""


def post_review(owner: str, repo: str, pr_number: int, findings: list[Finding], commit_sha: str):
    """
    Main entry point for Node 6.
    Posts inline review comments on the PR and sets check status.
    """
    if not findings:
        return {"status": "clean", "comments_posted": 0}

    g = Github(GITHUB_TOKEN)
    repository = g.get_repo(f"{owner}/{repo}")
    pr = repository.get_pull(pr_number)
    commit = repository.get_commit(commit_sha)

    comments_posted = 0

    # Post inline comments for each finding
    for finding in findings:
        body = format_comment(finding)
        try:
            pr.create_review_comment(
                body=body,
                commit=commit,
                path=finding.file,
                line=finding.line,
            )
            comments_posted += 1
        except Exception as e:
            print(f"Failed to post comment on {finding.file}:{finding.line}: {e}")

    # Post summary comment
    summary = build_summary(findings)
    pr.create_issue_comment(summary)

    # Determine overall status
    has_high = any(f.severity == "High" for f in findings)
    status = "failure" if has_high else "success"

    # Set commit status
    commit.create_status(
        state=status,
        description=f"Found {len(findings)} performance issue(s)" if findings else "No issues found",
        context="performance-regressor",
    )

    return {
        "status": status,
        "comments_posted": comments_posted,
        "total_findings": len(findings),
        "high": sum(1 for f in findings if f.severity == "High"),
        "medium": sum(1 for f in findings if f.severity == "Medium"),
        "low": sum(1 for f in findings if f.severity == "Low"),
    }


def build_summary(findings: list[Finding]) -> str:
    """Build a summary comment listing all findings."""
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
