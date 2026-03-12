from fastapi import FastAPI, Request, HTTPException
import hmac
import hashlib
from config import GITHUB_TOKEN, GITHUB_WEBHOOK_SECRET

from nodes.diff_fetcher import fetch_diff
from nodes.parser import enrich_file
from nodes.pattern_matcher import scan_all_files
from nodes.llm_analyzer import analyze
from nodes.severity_scorer import score_all
from nodes.responder import post_review

app = FastAPI(title="GitHub Performance Regressor")


async def run_pipeline(owner: str, repo: str, pr_number: int, commit_sha: str):
    """Run the full 6-node performance analysis pipeline."""

    # Node 1: Fetch diff
    file_changes = await fetch_diff(owner, repo, pr_number, GITHUB_TOKEN)
    if not file_changes:
        return {"status": "clean", "message": "No relevant file changes found"}

    # Node 2: Parse AST (note: scaffolding uses hunks as source — production will fetch full files)
    enriched_files = []
    for fc in file_changes:
        source = "\n".join(fc.added_lines)  # simplified — production will fetch full file content
        enriched = enrich_file(fc, source)
        enriched_files.append(enriched)

    # Node 3: Pattern matching
    suspects = scan_all_files(enriched_files)
    if not suspects:
        return {"status": "clean", "message": "No suspected patterns found"}

    # Node 4: LLM analysis
    findings = await analyze(suspects)
    if not findings:
        return {"status": "clean", "message": "LLM confirmed no real issues"}

    # Node 5: Severity scoring
    scored_findings = score_all(findings, enriched_files)

    # Node 6: Post review
    result = post_review(owner, repo, pr_number, scored_findings, commit_sha)

    return result


def verify_signature(payload_body: bytes, signature: str) -> bool:
    """Verify that the webhook payload came from GitHub."""
    if not GITHUB_WEBHOOK_SECRET:
        return True  # skip verification if no secret configured
    expected = "sha256=" + hmac.new(
        GITHUB_WEBHOOK_SECRET.encode(),
        payload_body,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


@app.post("/webhook")
async def webhook(request: Request):
    # Verify webhook signature
    body = await request.body()
    signature = request.headers.get("X-Hub-Signature-256", "")
    if not verify_signature(body, signature):
        raise HTTPException(status_code=401, detail="Invalid signature")

    payload = await request.json()

    # Only process PR opened/synchronize events
    action = payload.get("action", "")
    if action not in ("opened", "synchronize"):
        return {"status": "ignored", "action": action}

    pr = payload.get("pull_request", {})
    repo_full = payload.get("repository", {}).get("full_name", "")
    pr_number = pr.get("number")
    commit_sha = pr.get("head", {}).get("sha", "")

    if not all([repo_full, pr_number, commit_sha]):
        raise HTTPException(status_code=400, detail="Missing PR data in payload")

    owner, repo = repo_full.split("/")

    result = await run_pipeline(owner, repo, pr_number, commit_sha)
    return result


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)