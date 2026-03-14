"""
Tests for the regression tracking database layer.

Uses an in-memory SQLite database (sqlite+aiosqlite:///:memory:).
Tests cover CRUD operations, debt score calculation, trend upserts,
chronic offender detection, hotspots ordering, and dashboard endpoints.
"""
import asyncio
from datetime import datetime, date, timedelta

# Override DATABASE_URL before importing db modules
import config
config.DATABASE_URL = "sqlite+aiosqlite:///:memory:"

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from db.database import Base
from db import models as db_models
from db import repository
from db.repository import _compute_debt_score, _current_week_start
from models.schemas import Finding


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

async def _setup_db():
    """Create a fresh in-memory database and patch the session factory."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    # Monkey-patch the repository module's session factory
    repository.async_session_factory = session_factory
    return engine


def make_finding(
    file="app.py", line=10, pattern="ORM call inside loop",
    severity="High", cross_file=False, call_chain=None,
):
    return Finding(
        file=file, line=line, snippet="db.query()",
        pattern=pattern, explanation="N+1 query",
        suggested_fix="Use bulk query", severity=severity,
        cross_file=cross_file, call_chain=call_chain,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_debt_score_formula():
    """Verify the debt score calculation with known inputs."""
    # No findings → 0
    assert _compute_debt_score([]) == 0.0

    # 2 High findings (8 each), no cross-file
    findings = [make_finding(severity="High"), make_finding(severity="High", line=20)]
    score = _compute_debt_score(findings)
    expected = (8 + 8) * (1 + 0.5 * 0 / 2)  # 16 * 1.0 = 16.0
    assert score == expected, f"Expected {expected}, got {score}"

    # 2 findings, 1 cross-file → weighted more
    findings_cf = [
        make_finding(severity="High", cross_file=True),
        make_finding(severity="Medium", line=20),
    ]
    score_cf = _compute_debt_score(findings_cf)
    expected_cf = (8 + 5) * (1 + 0.5 * 1 / 2)  # 13 * 1.25 = 16.25
    assert score_cf == expected_cf, f"Expected {expected_cf}, got {score_cf}"
    print("✅ Debt score formula correct!")


def test_save_and_retrieve_pr():
    """Save a PR analysis, retrieve it via get_pr_history."""
    async def _run():
        await _setup_db()

        findings = [
            make_finding(severity="High"),
            make_finding(severity="Medium", line=20, pattern="Unbounded query"),
            make_finding(severity="Low", line=30, pattern="Repeated call in loop"),
        ]

        await repository.save_pr_analysis(
            repo="octocat/hello-world",
            pr_number=42,
            head_sha="abc123",
            author="octocat",
            title="Add new feature",
            findings=findings,
        )

        history = await repository.get_pr_history("octocat/hello-world")
        assert len(history) == 1
        pr = history[0]
        assert pr["pr_number"] == 42
        assert pr["author"] == "octocat"
        assert pr["title"] == "Add new feature"
        assert pr["finding_count"] == 3
        assert pr["high_count"] == 1
        print("✅ Save and retrieve PR works!")

    asyncio.run(_run())


def test_pattern_trends_upsert():
    """Saving two PRs in the same week should accumulate pattern trend count."""
    async def _run():
        await _setup_db()

        # PR 1
        await repository.save_pr_analysis(
            repo="test/repo", pr_number=1, head_sha="sha1",
            author="dev", title="PR 1",
            findings=[make_finding(severity="High", pattern="ORM call inside loop")],
        )

        # PR 2 (same week)
        await repository.save_pr_analysis(
            repo="test/repo", pr_number=2, head_sha="sha2",
            author="dev", title="PR 2",
            findings=[
                make_finding(severity="Medium", pattern="ORM call inside loop", line=20),
                make_finding(severity="Low", pattern="Unbounded query", line=30),
            ],
        )

        trends = await repository.get_pattern_trends("test/repo", weeks=4)
        orm_trends = [t for t in trends if t["pattern_type"] == "ORM call inside loop"]
        assert len(orm_trends) == 1
        assert orm_trends[0]["count"] == 2, f"Expected 2, got {orm_trends[0]['count']}"
        print("✅ Pattern trend upsert works!")

    asyncio.run(_run())


def test_chronic_offenders():
    """File in 3+ PRs appears in chronic offenders; file in 2 PRs does not."""
    async def _run():
        await _setup_db()

        # app.py appears in 3 PRs, utils.py in 2 PRs
        for i in range(3):
            findings = [make_finding(file="app.py", line=i + 1)]
            if i < 2:
                findings.append(make_finding(file="utils.py", line=i + 10))
            await repository.save_pr_analysis(
                repo="test/repo", pr_number=100 + i, head_sha=f"sha{i}",
                author="dev", title=f"PR {100+i}", findings=findings,
            )

        offenders = await repository.get_chronic_offenders("test/repo", min_occurrences=3)
        offender_files = [o["file_path"] for o in offenders]
        assert "app.py" in offender_files, f"app.py should be chronic offender"
        assert "utils.py" not in offender_files, f"utils.py should NOT be chronic offender (only 2 PRs)"
        print("✅ Chronic offenders threshold works!")

    asyncio.run(_run())


def test_hotspots_ordering():
    """Hotspots should be returned in descending finding count order."""
    async def _run():
        await _setup_db()

        # File with most findings
        findings = [
            make_finding(file="hot_file.py", line=1),
            make_finding(file="hot_file.py", line=2),
            make_finding(file="hot_file.py", line=3),
            make_finding(file="cold_file.py", line=1),
        ]

        await repository.save_pr_analysis(
            repo="test/repo", pr_number=1, head_sha="sha1",
            author="dev", title="PR 1", findings=findings,
        )

        hotspots = await repository.get_file_hotspots("test/repo", limit=10)
        assert len(hotspots) == 2
        assert hotspots[0]["file_path"] == "hot_file.py"
        assert hotspots[0]["total_findings"] == 3
        assert hotspots[1]["file_path"] == "cold_file.py"
        assert hotspots[1]["total_findings"] == 1
        print("✅ Hotspots ordering correct!")

    asyncio.run(_run())


def test_repo_overview():
    """Repo overview should return correct aggregate stats."""
    async def _run():
        await _setup_db()

        await repository.save_pr_analysis(
            repo="test/repo", pr_number=1, head_sha="sha1",
            author="dev", title="PR 1",
            findings=[
                make_finding(severity="High", cross_file=True),
                make_finding(severity="Medium", line=20),
            ],
        )

        overview = await repository.get_repo_stats("test/repo")
        assert overview["total_prs"] == 1
        assert overview["total_findings"] == 2
        assert overview["high_count"] == 1
        assert overview["medium_count"] == 1
        assert overview["cross_file_finding_pct"] == 50.0
        print("✅ Repo overview works!")

    asyncio.run(_run())


def test_all_repos():
    """All repos endpoint should list tracked repos."""
    async def _run():
        await _setup_db()

        await repository.save_pr_analysis(
            repo="org/repo-a", pr_number=1, head_sha="sha1",
            author="dev", title="PR 1",
            findings=[make_finding()],
        )
        await repository.save_pr_analysis(
            repo="org/repo-b", pr_number=1, head_sha="sha2",
            author="dev", title="PR 1",
            findings=[make_finding()],
        )

        repos = await repository.get_all_repos()
        names = [r["full_name"] for r in repos]
        assert "org/repo-a" in names
        assert "org/repo-b" in names
        assert len(repos) == 2
        print("✅ All repos listing works!")

    asyncio.run(_run())


def test_empty_repo():
    """Querying a non-existent repo should return empty results gracefully."""
    async def _run():
        await _setup_db()

        stats = await repository.get_repo_stats("nonexistent/repo")
        assert stats == {}

        history = await repository.get_pr_history("nonexistent/repo")
        assert history == []

        offenders = await repository.get_chronic_offenders("nonexistent/repo")
        assert offenders == []

        print("✅ Empty repo handling works!")

    asyncio.run(_run())


if __name__ == "__main__":
    test_debt_score_formula()
    test_save_and_retrieve_pr()
    test_pattern_trends_upsert()
    test_chronic_offenders()
    test_hotspots_ordering()
    test_repo_overview()
    test_all_repos()
    test_empty_repo()
    print("\n🎉 All database tests passed!")
