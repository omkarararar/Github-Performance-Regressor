"""
SQLAlchemy ORM models for the regression tracking database.

Tables:
  - repos: Tracked GitHub repositories
  - pull_requests: Analyzed PRs with aggregate stats and debt scores
  - findings: Individual performance findings linked to PRs
  - pattern_trends: Weekly aggregates of pattern occurrences per repo
"""
from datetime import datetime, date
from sqlalchemy import (
    Column, Integer, String, Text, Float, Boolean, DateTime, Date,
    ForeignKey, UniqueConstraint,
)
from sqlalchemy.orm import relationship
from db.database import Base


class Repo(Base):
    """A tracked GitHub repository."""
    __tablename__ = "repos"

    id = Column(Integer, primary_key=True, autoincrement=True)
    full_name = Column(String(255), unique=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    pull_requests = relationship("PullRequest", back_populates="repo", cascade="all, delete-orphan")
    pattern_trends = relationship("PatternTrend", back_populates="repo", cascade="all, delete-orphan")


class PullRequest(Base):
    """A single analyzed pull request."""
    __tablename__ = "pull_requests"

    id = Column(Integer, primary_key=True, autoincrement=True)
    repo_id = Column(Integer, ForeignKey("repos.id"), nullable=False)
    pr_number = Column(Integer, nullable=False)
    head_sha = Column(String(40), nullable=False)
    author = Column(String(255))
    title = Column(Text)
    analyzed_at = Column(DateTime, default=datetime.utcnow)
    finding_count = Column(Integer, default=0)
    high_count = Column(Integer, default=0)
    medium_count = Column(Integer, default=0)
    low_count = Column(Integer, default=0)
    debt_score = Column(Float, default=0.0)

    __table_args__ = (
        UniqueConstraint("repo_id", "pr_number", name="uq_repo_pr"),
    )

    repo = relationship("Repo", back_populates="pull_requests")
    findings = relationship("FindingRecord", back_populates="pull_request", cascade="all, delete-orphan")


class FindingRecord(Base):
    """A single performance finding from a PR analysis."""
    __tablename__ = "findings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    pr_id = Column(Integer, ForeignKey("pull_requests.id"), nullable=False)
    file_path = Column(Text, nullable=False)
    line_number = Column(Integer)
    pattern_type = Column(String(255), nullable=False)
    severity = Column(String(10), nullable=False)
    severity_score = Column(Integer, nullable=False)
    explanation = Column(Text)
    suggested_fix = Column(Text)
    cross_file = Column(Boolean, default=False)
    call_chain = Column(Text)  # JSON-encoded list
    created_at = Column(DateTime, default=datetime.utcnow)

    pull_request = relationship("PullRequest", back_populates="findings")


class PatternTrend(Base):
    """Weekly aggregate of pattern occurrences for a repo."""
    __tablename__ = "pattern_trends"

    id = Column(Integer, primary_key=True, autoincrement=True)
    repo_id = Column(Integer, ForeignKey("repos.id"), nullable=False)
    pattern_type = Column(String(255), nullable=False)
    week = Column(Date, nullable=False)
    count = Column(Integer, default=0)
    avg_severity = Column(Float, default=0.0)

    __table_args__ = (
        UniqueConstraint("repo_id", "pattern_type", "week", name="uq_repo_pattern_week"),
    )

    repo = relationship("Repo", back_populates="pattern_trends")
