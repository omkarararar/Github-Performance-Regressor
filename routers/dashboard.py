"""
Dashboard API router — provides endpoints for the regression tracking dashboard.

All endpoints return JSON and are protected by an optional API key
(X-API-Key header, configured via DASHBOARD_API_KEY in .env).
"""
from fastapi import APIRouter, Depends, HTTPException, Header, Query
from typing import Optional

from config import DASHBOARD_API_KEY
from db import repository
from logger import get_logger

log = get_logger("dashboard")

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


# ---------------------------------------------------------------------------
# Auth dependency
# ---------------------------------------------------------------------------

async def verify_api_key(x_api_key: Optional[str] = Header(None)):
    """Verify the dashboard API key if one is configured."""
    if DASHBOARD_API_KEY and x_api_key != DASHBOARD_API_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/repos", dependencies=[Depends(verify_api_key)])
async def list_repos():
    """List all tracked repos with total PR count and latest debt score."""
    repos = await repository.get_all_repos()
    return {"repos": repos}


@router.get("/repo/{owner}/{repo_name}/overview", dependencies=[Depends(verify_api_key)])
async def repo_overview(owner: str, repo_name: str):
    """Return overview statistics for a repository."""
    full_name = f"{owner}/{repo_name}"
    stats = await repository.get_repo_stats(full_name)
    if not stats:
        raise HTTPException(status_code=404, detail=f"Repo {full_name} not found")
    return stats


@router.get("/repo/{owner}/{repo_name}/trends", dependencies=[Depends(verify_api_key)])
async def pattern_trends(owner: str, repo_name: str, weeks: int = Query(12, ge=1, le=52)):
    """Return weekly pattern trend data for a repo (default: last 12 weeks)."""
    full_name = f"{owner}/{repo_name}"
    trends = await repository.get_pattern_trends(full_name, weeks)
    return {"trends": trends}


@router.get("/repo/{owner}/{repo_name}/hotspots", dependencies=[Depends(verify_api_key)])
async def file_hotspots(owner: str, repo_name: str, limit: int = Query(10, ge=1, le=50)):
    """Return the files with the most findings in a repo."""
    full_name = f"{owner}/{repo_name}"
    hotspots = await repository.get_file_hotspots(full_name, limit)
    return {"hotspots": hotspots}


@router.get("/repo/{owner}/{repo_name}/history", dependencies=[Depends(verify_api_key)])
async def pr_history(owner: str, repo_name: str, limit: int = Query(20, ge=1, le=100)):
    """Return recent PR analysis history for a repo."""
    full_name = f"{owner}/{repo_name}"
    history = await repository.get_pr_history(full_name, limit)
    return {"history": history}


@router.get("/repo/{owner}/{repo_name}/patterns", dependencies=[Depends(verify_api_key)])
async def pattern_summary(owner: str, repo_name: str):
    """Return pattern stats with trend direction (up/down/stable)."""
    full_name = f"{owner}/{repo_name}"
    patterns = await repository.get_pattern_summary(full_name)
    return {"patterns": patterns}


@router.get("/repo/{owner}/{repo_name}/chronic-offenders", dependencies=[Depends(verify_api_key)])
async def chronic_offenders(owner: str, repo_name: str):
    """Return files that keep appearing in findings across multiple PRs."""
    full_name = f"{owner}/{repo_name}"
    offenders = await repository.get_chronic_offenders(full_name)
    return {"chronic_offenders": offenders}
