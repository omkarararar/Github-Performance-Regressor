"""
Async CRUD functions for the regression tracking database.

All functions operate via async SQLAlchemy sessions and return
plain dicts/lists suitable for JSON serialisation by FastAPI.
"""
import json
from datetime import datetime, date, timedelta
from sqlalchemy import select, func, desc, and_, case, update as sa_update
from sqlalchemy.ext.asyncio import AsyncSession

from db.database import async_session_factory
from db.models import Repo, PullRequest, FindingRecord, PatternTrend
from models.schemas import Finding
from logger import get_logger

log = get_logger("db.repository")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _current_week_start() -> date:
    """Return the ISO week start (Monday) for the current date."""
    today = date.today()
    return today - timedelta(days=today.weekday())


def _compute_debt_score(findings: list[Finding]) -> float:
    """
    Compute the performance debt score for a set of findings.

    Formula: sum(severity_scores) * (1 + 0.5 * cross_file_count / max(total, 1))
    Cross-file findings are weighted 50% more heavily.
    """
    if not findings:
        return 0.0

    severity_map = {"High": 8, "Medium": 5, "Low": 2}
    total = len(findings)
    cross_file_count = sum(1 for f in findings if f.cross_file)
    severity_sum = sum(severity_map.get(f.severity, 3) for f in findings)

    return severity_sum * (1 + 0.5 * cross_file_count / max(total, 1))


# ---------------------------------------------------------------------------
# Write operations
# ---------------------------------------------------------------------------

async def save_pr_analysis(
    repo: str,
    pr_number: int,
    head_sha: str,
    author: str,
    title: str,
    findings: list[Finding],
) -> None:
    """
    Persist a complete PR analysis to the database.

    Creates the repo if it doesn't exist, upserts the PR record,
    saves all findings, and updates weekly pattern trend aggregates.
    """
    async with async_session_factory() as session:
        async with session.begin():
            # Get or create repo
            result = await session.execute(
                select(Repo).where(Repo.full_name == repo)
            )
            repo_obj = result.scalar_one_or_none()
            if not repo_obj:
                repo_obj = Repo(full_name=repo)
                session.add(repo_obj)
                await session.flush()

            # Count severities
            high = sum(1 for f in findings if f.severity == "High")
            med = sum(1 for f in findings if f.severity == "Medium")
            low = sum(1 for f in findings if f.severity == "Low")
            debt = _compute_debt_score(findings)

            # Upsert PR record
            result = await session.execute(
                select(PullRequest).where(
                    PullRequest.repo_id == repo_obj.id,
                    PullRequest.pr_number == pr_number,
                )
            )
            pr_obj = result.scalar_one_or_none()
            if pr_obj:
                # Update existing
                pr_obj.head_sha = head_sha
                pr_obj.author = author
                pr_obj.title = title
                pr_obj.analyzed_at = datetime.utcnow()
                pr_obj.finding_count = len(findings)
                pr_obj.high_count = high
                pr_obj.medium_count = med
                pr_obj.low_count = low
                pr_obj.debt_score = debt
                # Clear old findings
                for old in pr_obj.findings:
                    await session.delete(old)
                await session.flush()
            else:
                pr_obj = PullRequest(
                    repo_id=repo_obj.id,
                    pr_number=pr_number,
                    head_sha=head_sha,
                    author=author,
                    title=title,
                    finding_count=len(findings),
                    high_count=high,
                    medium_count=med,
                    low_count=low,
                    debt_score=debt,
                )
                session.add(pr_obj)
                await session.flush()

            # Save findings
            severity_map = {"High": 8, "Medium": 5, "Low": 2}
            for f in findings:
                record = FindingRecord(
                    pr_id=pr_obj.id,
                    file_path=f.file,
                    line_number=f.line,
                    pattern_type=f.pattern,
                    severity=f.severity or "Low",
                    severity_score=severity_map.get(f.severity, 3),
                    explanation=f.explanation,
                    suggested_fix=f.suggested_fix,
                    cross_file=f.cross_file,
                    call_chain=json.dumps(f.call_chain) if f.call_chain else None,
                )
                session.add(record)

            # Update pattern trends
            week_start = _current_week_start()
            pattern_counts: dict[str, list[int]] = {}
            for f in findings:
                if f.pattern not in pattern_counts:
                    pattern_counts[f.pattern] = []
                pattern_counts[f.pattern].append(severity_map.get(f.severity, 3))

            for pattern, scores in pattern_counts.items():
                result = await session.execute(
                    select(PatternTrend).where(
                        PatternTrend.repo_id == repo_obj.id,
                        PatternTrend.pattern_type == pattern,
                        PatternTrend.week == week_start,
                    )
                )
                trend = result.scalar_one_or_none()
                if trend:
                    # Accumulate
                    old_total = trend.count * trend.avg_severity
                    trend.count += len(scores)
                    trend.avg_severity = (old_total + sum(scores)) / trend.count
                else:
                    trend = PatternTrend(
                        repo_id=repo_obj.id,
                        pattern_type=pattern,
                        week=week_start,
                        count=len(scores),
                        avg_severity=sum(scores) / len(scores),
                    )
                    session.add(trend)

    log.info(f"Saved analysis for {repo} PR #{pr_number}: {len(findings)} findings, debt={debt:.1f}")


# ---------------------------------------------------------------------------
# Read operations
# ---------------------------------------------------------------------------

async def get_all_repos() -> list[dict]:
    """Return all tracked repos with total PR count and latest debt score."""
    async with async_session_factory() as session:
        result = await session.execute(
            select(
                Repo.full_name,
                func.count(PullRequest.id).label("pr_count"),
                func.max(PullRequest.debt_score).label("latest_debt_score"),
            )
            .outerjoin(PullRequest, PullRequest.repo_id == Repo.id)
            .group_by(Repo.full_name)
        )
        rows = result.all()
        return [
            {
                "full_name": r.full_name,
                "pr_count": r.pr_count,
                "latest_debt_score": r.latest_debt_score or 0.0,
            }
            for r in rows
        ]


async def get_repo_stats(repo_name: str) -> dict:
    """Return overview statistics for a repo."""
    async with async_session_factory() as session:
        # Get repo
        result = await session.execute(
            select(Repo).where(Repo.full_name == repo_name)
        )
        repo_obj = result.scalar_one_or_none()
        if not repo_obj:
            return {}

        # Aggregate stats
        result = await session.execute(
            select(
                func.count(PullRequest.id).label("total_prs"),
                func.sum(PullRequest.finding_count).label("total_findings"),
                func.sum(PullRequest.high_count).label("high_count"),
                func.sum(PullRequest.medium_count).label("medium_count"),
                func.sum(PullRequest.low_count).label("low_count"),
                func.avg(PullRequest.debt_score).label("avg_debt_score"),
            ).where(PullRequest.repo_id == repo_obj.id)
        )
        stats = result.one()

        # Worst and best PRs
        result = await session.execute(
            select(PullRequest.pr_number)
            .where(PullRequest.repo_id == repo_obj.id)
            .order_by(desc(PullRequest.debt_score))
            .limit(1)
        )
        worst = result.scalar_one_or_none()

        result = await session.execute(
            select(PullRequest.pr_number)
            .where(PullRequest.repo_id == repo_obj.id)
            .order_by(PullRequest.debt_score)
            .limit(1)
        )
        best = result.scalar_one_or_none()

        # Most common pattern
        result = await session.execute(
            select(
                FindingRecord.pattern_type,
                func.count(FindingRecord.id).label("cnt"),
            )
            .join(PullRequest, PullRequest.id == FindingRecord.pr_id)
            .where(PullRequest.repo_id == repo_obj.id)
            .group_by(FindingRecord.pattern_type)
            .order_by(desc("cnt"))
            .limit(1)
        )
        most_common_row = result.first()
        most_common = most_common_row.pattern_type if most_common_row else None

        # Cross-file percentage
        result = await session.execute(
            select(
                func.count(FindingRecord.id).label("total"),
                func.sum(case((FindingRecord.cross_file == True, 1), else_=0)).label("cross"),
            )
            .join(PullRequest, PullRequest.id == FindingRecord.pr_id)
            .where(PullRequest.repo_id == repo_obj.id)
        )
        cf_row = result.one()
        total_f = cf_row.total or 0
        cross_f = cf_row.cross or 0
        cross_pct = (cross_f / total_f * 100) if total_f > 0 else 0.0

        return {
            "total_prs": stats.total_prs or 0,
            "total_findings": stats.total_findings or 0,
            "high_count": stats.high_count or 0,
            "medium_count": stats.medium_count or 0,
            "low_count": stats.low_count or 0,
            "avg_debt_score": round(stats.avg_debt_score or 0, 2),
            "worst_pr_number": worst,
            "best_pr_number": best,
            "most_common_pattern": most_common,
            "cross_file_finding_pct": round(cross_pct, 1),
        }


async def get_pattern_trends(repo_name: str, weeks: int = 12) -> list[dict]:
    """Return weekly pattern trend data for a repo."""
    async with async_session_factory() as session:
        result = await session.execute(
            select(Repo).where(Repo.full_name == repo_name)
        )
        repo_obj = result.scalar_one_or_none()
        if not repo_obj:
            return []

        cutoff = date.today() - timedelta(weeks=weeks)
        result = await session.execute(
            select(PatternTrend)
            .where(
                PatternTrend.repo_id == repo_obj.id,
                PatternTrend.week >= cutoff,
            )
            .order_by(desc(PatternTrend.week))
        )
        trends = result.scalars().all()

        return [
            {
                "week": t.week.isoformat(),
                "pattern_type": t.pattern_type,
                "count": t.count,
                "avg_severity": round(t.avg_severity, 2),
            }
            for t in trends
        ]


async def get_file_hotspots(repo_name: str, limit: int = 10) -> list[dict]:
    """Return the files with the most findings in a repo."""
    async with async_session_factory() as session:
        result = await session.execute(
            select(Repo).where(Repo.full_name == repo_name)
        )
        repo_obj = result.scalar_one_or_none()
        if not repo_obj:
            return []

        result = await session.execute(
            select(
                FindingRecord.file_path,
                func.count(FindingRecord.id).label("total_findings"),
                func.sum(case((FindingRecord.severity == "High", 1), else_=0)).label("high_count"),
                func.avg(FindingRecord.severity_score).label("avg_severity_score"),
            )
            .join(PullRequest, PullRequest.id == FindingRecord.pr_id)
            .where(PullRequest.repo_id == repo_obj.id)
            .group_by(FindingRecord.file_path)
            .order_by(desc("total_findings"))
            .limit(limit)
        )
        rows = result.all()

        hotspots = []
        for r in rows:
            # Get most common pattern for this file
            pat_result = await session.execute(
                select(FindingRecord.pattern_type, func.count().label("cnt"))
                .join(PullRequest, PullRequest.id == FindingRecord.pr_id)
                .where(
                    PullRequest.repo_id == repo_obj.id,
                    FindingRecord.file_path == r.file_path,
                )
                .group_by(FindingRecord.pattern_type)
                .order_by(desc("cnt"))
                .limit(1)
            )
            pat_row = pat_result.first()

            # Get last seen PR
            pr_result = await session.execute(
                select(PullRequest.pr_number)
                .join(FindingRecord, FindingRecord.pr_id == PullRequest.id)
                .where(
                    PullRequest.repo_id == repo_obj.id,
                    FindingRecord.file_path == r.file_path,
                )
                .order_by(desc(PullRequest.analyzed_at))
                .limit(1)
            )
            last_pr = pr_result.scalar_one_or_none()

            hotspots.append({
                "file_path": r.file_path,
                "total_findings": r.total_findings,
                "high_count": r.high_count or 0,
                "avg_severity_score": round(r.avg_severity_score or 0, 2),
                "most_common_pattern": pat_row.pattern_type if pat_row else None,
                "last_seen_pr": last_pr,
            })

        return hotspots


async def get_pr_history(repo_name: str, limit: int = 20) -> list[dict]:
    """Return recent PR analysis history for a repo."""
    async with async_session_factory() as session:
        result = await session.execute(
            select(Repo).where(Repo.full_name == repo_name)
        )
        repo_obj = result.scalar_one_or_none()
        if not repo_obj:
            return []

        result = await session.execute(
            select(PullRequest)
            .where(PullRequest.repo_id == repo_obj.id)
            .order_by(desc(PullRequest.analyzed_at))
            .limit(limit)
        )
        prs = result.scalars().all()

        return [
            {
                "pr_number": pr.pr_number,
                "title": pr.title,
                "author": pr.author,
                "analyzed_at": pr.analyzed_at.isoformat() if pr.analyzed_at else None,
                "finding_count": pr.finding_count,
                "high_count": pr.high_count,
                "debt_score": round(pr.debt_score, 2),
            }
            for pr in prs
        ]


async def get_chronic_offenders(
    repo_name: str, min_occurrences: int = 3,
) -> list[dict]:
    """
    Return file paths that have appeared in findings across multiple separate PRs.

    Only files appearing in >= min_occurrences distinct PRs are returned.
    """
    async with async_session_factory() as session:
        result = await session.execute(
            select(Repo).where(Repo.full_name == repo_name)
        )
        repo_obj = result.scalar_one_or_none()
        if not repo_obj:
            return []

        result = await session.execute(
            select(
                FindingRecord.file_path,
                func.count(func.distinct(PullRequest.id)).label("pr_count"),
                func.max(PullRequest.pr_number).label("latest_pr"),
            )
            .join(PullRequest, PullRequest.id == FindingRecord.pr_id)
            .where(PullRequest.repo_id == repo_obj.id)
            .group_by(FindingRecord.file_path)
            .having(func.count(func.distinct(PullRequest.id)) >= min_occurrences)
            .order_by(desc("pr_count"))
        )
        rows = result.all()

        return [
            {
                "file_path": r.file_path,
                "pr_count": r.pr_count,
                "latest_pr": r.latest_pr,
            }
            for r in rows
        ]


async def get_pattern_summary(repo_name: str) -> list[dict]:
    """
    Return pattern stats with trend direction (up/down/stable).

    Trend is based on comparing the last 4 weeks vs the prior 4 weeks.
    """
    async with async_session_factory() as session:
        result = await session.execute(
            select(Repo).where(Repo.full_name == repo_name)
        )
        repo_obj = result.scalar_one_or_none()
        if not repo_obj:
            return []

        # Get all-time stats per pattern
        result = await session.execute(
            select(
                FindingRecord.pattern_type,
                func.count(FindingRecord.id).label("total_count"),
                func.avg(FindingRecord.severity_score).label("avg_severity"),
            )
            .join(PullRequest, PullRequest.id == FindingRecord.pr_id)
            .where(PullRequest.repo_id == repo_obj.id)
            .group_by(FindingRecord.pattern_type)
            .order_by(desc("total_count"))
        )
        pattern_rows = result.all()

        # Get trend data for each pattern
        today = date.today()
        recent_start = today - timedelta(weeks=4)
        prior_start = today - timedelta(weeks=8)

        patterns = []
        for row in pattern_rows:
            # Recent 4 weeks count
            r1 = await session.execute(
                select(func.coalesce(func.sum(PatternTrend.count), 0))
                .where(
                    PatternTrend.repo_id == repo_obj.id,
                    PatternTrend.pattern_type == row.pattern_type,
                    PatternTrend.week >= recent_start,
                )
            )
            recent_count = r1.scalar() or 0

            # Prior 4 weeks count
            r2 = await session.execute(
                select(func.coalesce(func.sum(PatternTrend.count), 0))
                .where(
                    PatternTrend.repo_id == repo_obj.id,
                    PatternTrend.pattern_type == row.pattern_type,
                    PatternTrend.week >= prior_start,
                    PatternTrend.week < recent_start,
                )
            )
            prior_count = r2.scalar() or 0

            if recent_count > prior_count:
                trend = "up"
            elif recent_count < prior_count:
                trend = "down"
            else:
                trend = "stable"

            patterns.append({
                "pattern_type": row.pattern_type,
                "total_count": row.total_count,
                "avg_severity": round(row.avg_severity or 0, 2),
                "trend_direction": trend,
            })

        return patterns
