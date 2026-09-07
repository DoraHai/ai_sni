"""Transaction serialization for global platform-administrator invariants."""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession


# Stable, repository-wide PostgreSQL advisory transaction lock ("PLATFADM").
PLATFORM_ADMIN_LOCK_ID = 0x504C41544641444D


async def acquire_platform_admin_lock(session: AsyncSession) -> None:
    """Serialize mutations that can reduce global platform administrators."""
    await session.execute(select(func.pg_advisory_xact_lock(PLATFORM_ADMIN_LOCK_ID)))
