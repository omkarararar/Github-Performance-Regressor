from fastapi import FastAPI, Request, HTTPException, BackgroundTasks
import hmac
import hashlib
from config import GITHUB_TOKEN, GITHUB_WEBHOOK_SECRET

from nodes.diff_fetcher import fetch_diff
from nodes.parser import enrich_file
from nodes.pattern_matcher import scan_all_files
from nodes.llm_analyzer import analyze
from nodes.severity_scorer import score_all
from nodes.responder import post_review
from logger import get_logger

log = get_logger("pipeline")

app = FastAPI(title="GitHub Performance Regressor")


@app.get("/health")
async def health():
    return {"status": "healthy", "service": "performance-regressor"}


async def run_pipeline(owner: str, repo: str, pr_number: int, commit_sha: str) -> dict:
    """Run the full 6-node performance analysis pipeline."""
    try:
        # Node 1: Fetch diff + full file contents
        log.info(f"Pipeline start: {owner}/{repo} PR #{pr_number}")
        file_changes = await fetch_diff(owner, repo, pr_number, GITHUB_TOKEN)
        if not file_changes:
            log.info("No relevant file changes found")
            return {"status": "clean", "message": "No relevant file changes found"}

        # Node 2: Parse AST using full file content
        enriched_files = []
        for fc in file_changes:
            enriched = enrich_file(fc)
            enriched_files.append(enriched)

        # Node 3: Pattern matching
        suspects = scan_all_files(enriched_files)
        if not suspects:
            log.info("No suspected patterns found")
            return {"status": "clean", "message": "No suspected patterns found"}

        # Node 4: LLM analysis
        findings = await analyze(suspects)
        if not findings:
            log.info("LLM confirmed no real issues")
            return {"status": "clean", "message": "LLM confirmed no real issues"}

        # Node 5: Severity scoring
        scored_findings = score_all(findings, enriched_files)

        # Node 6: Post review
        result = post_review(owner, repo, pr_number, scored_findings, commit_sha)

        log.info(f"Pipeline complete: {result}")
        return result

    except Exception as e:
        log.error(f"Pipeline failed: {e}", exc_info=True)
        return {"status": "error", "message": str(e)}


def verify_signature(payload_body: bytes, signature: str) -> bool:
    if not GITHUB_WEBHOOK_SECRET:
        return True
    expected = "sha256=" + hmac.new(
        GITHUB_WEBHOOK_SECRET.encode(),
        payload_body,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


@app.post("/webhook")
async def webhook(request: Request, background_tasks: BackgroundTasks):
    # Verify webhook signature
    body = await request.body()
    signature = request.headers.get("X-Hub-Signature-256", "")
    if not verify_signature(body, signature):
        log.warning("Invalid webhook signature received")
        raise HTTPException(status_code=401, detail="Invalid signature")

    payload = await request.json()

    # Only process PR opened/synchronize events
    action = payload.get("action", "")
    if action not in ("opened", "synchronize"):
        log.info(f"Ignoring PR action: {action}")
        return {"status": "ignored", "action": action}

    pr = payload.get("pull_request", {})
    repo_full = payload.get("repository", {}).get("full_name", "")
    pr_number = pr.get("number")
    commit_sha = pr.get("head", {}).get("sha", "")

    if not all([repo_full, pr_number, commit_sha]):
        raise HTTPException(status_code=400, detail="Missing PR data in payload")

    owner, repo = repo_full.split("/")
    log.info(f"Webhook received: {owner}/{repo} PR #{pr_number} ({action})")

    # Run pipeline in background (return 200 immediately to GitHub)
    background_tasks.add_task(run_pipeline, owner, repo, pr_number, commit_sha)

    return {"status": "processing", "pr": pr_number, "repo": repo_full}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)