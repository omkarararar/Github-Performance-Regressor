"""Seed the database with mock data to demo the dashboard."""
import asyncio
from db.database import init_db
from db.repository import save_pr_analysis
from models.schemas import Finding


async def seed():
    await init_db()

    # --- Repo 1: octocat/hello-world (3 PRs) ---
    await save_pr_analysis(
        repo="octocat/hello-world", pr_number=1, head_sha="aaa111",
        author="octocat", title="Add user API endpoint",
        findings=[
            Finding(file="views.py", line=10, snippet="Order.objects.filter(user_id=user.id)",
                    pattern="ORM call inside loop", explanation="N+1 query in user handler",
                    suggested_fix="Use select_related()", severity="High", cross_file=True,
                    call_chain=["views.py:get_users() [loop]", "→ db.py:fetch_orders()"]),
            Finding(file="views.py", line=25, snippet="User.objects.all()",
                    pattern="Unbounded query", explanation="Loads all users into memory",
                    suggested_fix="Add .limit(100)", severity="Medium"),
        ],
    )

    await save_pr_analysis(
        repo="octocat/hello-world", pr_number=2, head_sha="bbb222",
        author="devuser", title="Add async report generation",
        findings=[
            Finding(file="views.py", line=42, snippet="time.sleep(10)",
                    pattern="Blocking call in async", explanation="Blocks event loop",
                    suggested_fix="Use asyncio.sleep(10)", severity="High"),
            Finding(file="utils.py", line=15, snippet="db.find()",
                    pattern="Unbounded query", explanation="No limit on query",
                    suggested_fix="Add .limit()", severity="Low"),
        ],
    )

    await save_pr_analysis(
        repo="octocat/hello-world", pr_number=3, head_sha="ccc333",
        author="octocat", title="Optimize data processing",
        findings=[
            Finding(file="views.py", line=55, snippet="session.query(User)",
                    pattern="SQLAlchemy query in loop", explanation="N+1 in loop",
                    suggested_fix="Use joinedload()", severity="High", cross_file=True,
                    call_chain=["api.py:handler() [loop]", "→ views.py:get_data()"]),
            Finding(file="utils.py", line=30, snippet="transform(item)",
                    pattern="Repeated call in loop", explanation="Could be hoisted",
                    suggested_fix="Cache result outside loop", severity="Low"),
            Finding(file="models.py", line=8, snippet=".objects.all()",
                    pattern="Missing select_related/prefetch_related", explanation="Missing prefetch",
                    suggested_fix="Add .select_related('profile')", severity="Medium"),
        ],
    )

    print("✅ Seeded 3 PRs with 7 findings for octocat/hello-world")
    print("🔄 Restart the server and refresh the dashboard!")


if __name__ == "__main__":
    asyncio.run(seed())
