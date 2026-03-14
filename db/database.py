"""
Database engine and session management for the regression tracking system.

Uses SQLAlchemy 2.0 async with aiosqlite (local) or asyncpg (Postgres).
Database URL is configurable via DATABASE_URL in .env.
"""
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase

from config import DATABASE_URL
from logger import get_logger

log = get_logger("database")


class Base(DeclarativeBase):
    """Base class for all ORM models."""
    pass


engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    future=True,
)

async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def init_db():
    """Create all database tables. Called on application startup."""
    async with engine.begin() as conn:
        # Import models to register them with Base.metadata
        from db import models as _  # noqa: F401
        await conn.run_sync(Base.metadata.create_all)
    log.info("Database tables initialized")


async def get_session() -> AsyncSession:
    """Get a new async database session."""
    async with async_session_factory() as session:
        return session
