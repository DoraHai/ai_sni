"""Database session dependency for GEO endpoints that must remain query-only."""

from collections.abc import AsyncIterator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session_factory


async def geo_read_session() -> AsyncIterator[AsyncSession]:
    """Yield a repeatable-read transaction that PostgreSQL enforces as read-only."""
    async with async_session_factory(autoflush=False) as session:
        try:
            # This must be the transaction's first SQL statement. PostgreSQL
            # rejects SET TRANSACTION after a query or write has already run.
            await session.execute(
                text(
                    "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"
                )
            )
            yield session
        finally:
            # A read dependency never commits. Rollback also closes an aborted
            # transaction when PostgreSQL rejected an accidental write.
            await session.rollback()
