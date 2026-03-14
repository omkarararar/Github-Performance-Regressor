from fastapi import FastAPI, Request, HTTPException, BackgroundTasks
from fastapi.staticfiles import StaticFiles
import hmac
import hashlib
from config import GITHUB_TOKEN, GITHUB_WEBHOOK_SECRET

from nodes.diff_fetcher import fetch_diff
from nodes.parser import enrich_file
from nodes.call_graph import analyze as call_graph_analyze
from nodes.pattern_matcher import scan_all_files
from nodes.llm_analyzer import analyze
from nodes.severity_scorer import score_all
from nodes.responder import post_review
from routers.dashboard import router as dashboard_router
from db.database import init_db
from db import repository as db_repository
from logger import get_logger

log = get_logger("pipeline")

app = FastAPI(title="GitHub Performance Regressor")

# Mount dashboard API router
app.include_router(dashboard_router)

# Mount static files for dashboard UI
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.on_event("startup")
async def startup():
    """Initialize the database on application startup."""
    await init_db()
    log.info("Application started — database initialized")


@app.get("/health")
async def health():
    return {"status": "healthy", "service": "performance-regressor"}


async def run_pipeline(owner: str, repo: str, pr_number: int, commit_sha: str, author: str = "", title: str = "") -> dict:
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

        # Node 2.5: Cross-file call graph analysis
        enriched_files = await call_graph_analyze(enriched_files)

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

        # Persist to database
        try:
            await db_repository.save_pr_analysis(
                repo=f"{owner}/{repo}",
                pr_number=pr_number,
                head_sha=commit_sha,
                author=author,
                title=title,
                findings=scored_findings,
            )
        except Exception as e:
            log.error(f"Failed to save analysis to database: {e}", exc_info=True)

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
    author = pr.get("user", {}).get("login", "")
    title = pr.get("title", "")

    if not all([repo_full, pr_number, commit_sha]):
        raise HTTPException(status_code=400, detail="Missing PR data in payload")

    owner, repo = repo_full.split("/")
    log.info(f"Webhook received: {owner}/{repo} PR #{pr_number} ({action})")

    # Run pipeline in background (return 200 immediately to GitHub)
    background_tasks.add_task(run_pipeline, owner, repo, pr_number, commit_sha, author, title)

    return {"status": "processing", "pr": pr_number, "repo": repo_full}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="localhost", port=8000)
