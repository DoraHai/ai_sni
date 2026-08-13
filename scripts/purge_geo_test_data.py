"""Purge GEO operational / demo data (local reset).

Default: wipe ALL tenants' GEO content tables.
Keeps by default: geo_tracking_engines, geo_ai_settings (credentials/config).

Usage:
  python -m scripts.purge_geo_test_data --dry-run
  python -m scripts.purge_geo_test_data --yes
  python -m scripts.purge_geo_test_data --yes --tenant-id 1
  python -m scripts.purge_geo_test_data --yes --also-config
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from sqlalchemy import text

from app.database import async_session_factory

# Config tables kept unless --also-config
KEEP_DEFAULT = frozenset({"geo_tracking_engines", "geo_ai_settings"})


async def list_geo_tables(session) -> list[str]:
    r = await session.execute(
        text(
            "SELECT tablename FROM pg_tables "
            "WHERE schemaname = 'public' AND tablename LIKE 'geo_%' "
            "ORDER BY 1"
        )
    )
    return [row[0] for row in r]


async def table_has_tenant_id(session, table: str) -> bool:
    col = await session.scalar(
        text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_schema='public' AND table_name=:t AND column_name='tenant_id'"
        ),
        {"t": table},
    )
    return bool(col)


async def count_table(session, table: str, tenant_id: int | None) -> int:
    if tenant_id is None or not await table_has_tenant_id(session, table):
        return int(await session.scalar(text(f'SELECT count(*) FROM "{table}"')) or 0)
    return int(
        await session.scalar(
            text(f'SELECT count(*) FROM "{table}" WHERE tenant_id = :tid'),
            {"tid": tenant_id},
        )
        or 0
    )


async def run(
    *,
    dry_run: bool,
    tenant_id: int | None,
    also_config: bool,
) -> int:
    async with async_session_factory() as session:
        existing = await list_geo_tables(session)
        print(f"Found {len(existing)} geo_* tables")

        try:
            rows = await session.execute(text("SELECT id, name FROM tenants ORDER BY id"))
            print("Tenants:")
            for row in rows:
                print(f"  #{row[0]} {row[1]}")
        except Exception as exc:  # noqa: BLE001
            print(f"(tenants list skip: {exc})")
            await session.rollback()

        targets = [
            t
            for t in existing
            if also_config or t not in KEEP_DEFAULT
        ]

        print("\nPlanned counts:")
        total = 0
        plan: list[tuple[str, int]] = []
        for t in targets:
            n = await count_table(session, t, tenant_id)
            plan.append((t, n))
            if n:
                print(f"  {t}: {n}")
                total += n
        kept = [t for t in existing if t not in targets]
        if kept:
            print(f"\nKept (config): {', '.join(kept)}")
        if total == 0:
            print("No rows to delete.")
            return 0

        print(f"\nTotal rows: {total}")
        if dry_run:
            print("Dry-run only — nothing deleted.")
            return 0

        if tenant_id is None:
            # Full wipe: TRUNCATE CASCADE is FK-safe and resets identity
            names = ", ".join(f'"{t}"' for t in targets)
            await session.execute(text(f"TRUNCATE TABLE {names} RESTART IDENTITY CASCADE"))
            await session.commit()
            print(f"TRUNCATE CASCADE done on {len(targets)} tables.")
            return total

        # Tenant-scoped: DELETE with CASCADE via multiple passes
        # Prefer deleting leaf tables first by retrying until stable
        remaining = {t: n for t, n in plan if n > 0}
        deleted = 0
        for _pass in range(12):
            if not remaining:
                break
            progress = False
            for t in list(remaining.keys()):
                if not await table_has_tenant_id(session, t):
                    # cannot safely scope-delete global tables
                    print(f"  skip (no tenant_id): {t}")
                    del remaining[t]
                    progress = True
                    continue
                try:
                    async with session.begin_nested():
                        res = await session.execute(
                            text(f'DELETE FROM "{t}" WHERE tenant_id = :tid'),
                            {"tid": tenant_id},
                        )
                    n = res.rowcount or 0
                    if n:
                        print(f"  deleted {t}: {n}")
                        deleted += n
                    del remaining[t]
                    progress = True
                except Exception as exc:  # noqa: BLE001
                    # FK violation — try later
                    msg = str(exc).split("\n")[0][:120]
                    if _pass == 11:
                        print(f"  FAIL {t}: {msg}", file=sys.stderr)
                        raise
            if not progress:
                break

        await session.commit()
        print(f"\nDone. Deleted ~{deleted} rows.")
        if remaining:
            print(f"Remaining (blocked): {remaining}", file=sys.stderr)
            return 1
        return deleted


def main() -> None:
    ap = argparse.ArgumentParser(description="Purge GEO test/demo data")
    ap.add_argument("--dry-run", action="store_true", help="Count only")
    ap.add_argument("--yes", action="store_true", help="Actually delete")
    ap.add_argument(
        "--tenant-id",
        type=int,
        default=None,
        help="Only this tenant (default: all tenants via TRUNCATE)",
    )
    ap.add_argument(
        "--also-config",
        action="store_true",
        help="Also wipe geo_tracking_engines + geo_ai_settings",
    )
    args = ap.parse_args()
    if not args.dry_run and not args.yes:
        print("Refusing to delete without --yes (or use --dry-run).")
        sys.exit(2)
    code = asyncio.run(
        run(
            dry_run=args.dry_run,
            tenant_id=args.tenant_id,
            also_config=args.also_config,
        )
    )
    if isinstance(code, int) and code == 1:
        sys.exit(1)


if __name__ == "__main__":
    main()
