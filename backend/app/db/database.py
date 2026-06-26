"""
Database connection management for Company Brain.

Provides async SQLAlchemy engine and session factory.
All database operations use async sessions to avoid blocking the event loop.
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    """SQLAlchemy declarative base for all ORM models."""
    pass


# ── Engine & Session Factory ────────────────────────────────────────────────

_engine = None
_session_factory = None


def _get_database_url() -> str:
    """Resolve the database URL from environment."""
    url = os.getenv("DATABASE_URL", "")
    if not url:
        # Fallback for local development without Docker
        url = "postgresql+asyncpg://cb_admin:change-me-in-production@localhost:5432/companybrain"
        logger.warning("DATABASE_URL not set — using fallback: %s", url.split("@")[-1])
    return url


def get_engine():
    """Return the shared async engine (lazy-initialised)."""
    global _engine
    if _engine is None:
        _engine = create_async_engine(
            _get_database_url(),
            echo=os.getenv("DB_ECHO", "false").lower() == "true",
            pool_size=20,
            max_overflow=10,
            pool_pre_ping=True,  # Detect stale connections
            pool_recycle=3600,   # Recycle connections every hour
        )
        logger.info("Database engine created: %s", _get_database_url().split("@")[-1])
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Return the shared session factory (lazy-initialised)."""
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            bind=get_engine(),
            class_=AsyncSession,
            expire_on_commit=False,
        )
    return _session_factory


@asynccontextmanager
async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Yield a database session with automatic commit/rollback.

    Usage::

        async with get_db_session() as session:
            session.add(some_model)
    """
    factory = get_session_factory()
    session = factory()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


async def init_db() -> None:
    """Create all tables at startup — unless schema is managed by migrations.

    Gated by ``AUTO_CREATE_SCHEMA``. When unset, it defaults ON in dev/local
    (convenience) and OFF in production, where Alembic owns the schema
    (``alembic upgrade head``). Set ``AUTO_CREATE_SCHEMA=true`` to force it on.
    Implicit DDL at boot is a footgun in prod (races between replicas, no
    review, no rollback), which is why production defaults to migrations.
    """
    from app.services.security.secret_config import is_production

    flag = os.getenv("AUTO_CREATE_SCHEMA")
    enabled = (flag.strip().lower() in ("1", "true", "yes", "on")) if flag is not None else (not is_production())
    if not enabled:
        logger.info("AUTO_CREATE_SCHEMA off — skipping create_all (Alembic manages the schema)")
        return

    engine = get_engine()
    async with engine.begin() as conn:
        # Import all models so they register with Base.metadata
        from app.db import models  # noqa: F401
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database tables initialised (create_all)")


async def close_db() -> None:
    """Dispose of the engine connection pool (called at shutdown)."""
    global _engine, _session_factory
    if _engine:
        await _engine.dispose()
        _engine = None
        _session_factory = None
        logger.info("Database engine disposed")
