"""Run the production distribution queue and planner without execution handoff."""

import argparse
import asyncio
import logging
import time

from sqlalchemy import text
from app.database import async_session_factory, engine
from app import distribution_queue, distribution_planning

LOG = logging.getLogger("distribution_queue_worker")


def result_summary(value):
    """Keep data and exception details out of the worker journal."""
    if value is None:
        return "none"
    return type(value).__name__


async def nord_only():
    """Stop before a cycle if SEO distribution contains another tenant."""
    tables = (
        "distribution_project_channels",
        "distribution_controls",
        "distribution_queue",
        "distribution_plan_requests",
        "distribution_plans",
    )
    async with async_session_factory() as db:
        await db.execute(text("SET TRANSACTION READ ONLY"))
        for table in tables:
            if await db.scalar(text(
                f"SELECT EXISTS(SELECT 1 FROM {table} WHERE module='seo' AND tenant_id<>1)"
            )):
                return False
    return True


async def run_cycle():
    try:
        allowed = await nord_only()
    except Exception as exc:
        LOG.error("scope_check=error error_type=%s", type(exc).__name__)
        return False
    if not allowed:
        LOG.error("scope_check=blocked reason=other_tenant_present")
        return False
    ok = True
    for name, run_once in (
        ("queue", distribution_queue.run_once),
        ("planning", distribution_planning.run_once),
    ):
        started = time.monotonic()
        try:
            result = await run_once(async_session_factory, module="seo")
        except Exception as exc:
            ok = False
            LOG.error("module=%s status=error error_type=%s elapsed_ms=%d",
                      name, type(exc).__name__, int((time.monotonic() - started) * 1000))
        else:
            LOG.info("module=%s status=ok result=%s elapsed_ms=%d",
                     name, result_summary(result), int((time.monotonic() - started) * 1000))
    return ok


async def run(once, interval):
    try:
        while True:
            ok = await run_cycle()
            if once:
                return 0 if ok else 1
            await asyncio.sleep(interval)
    finally:
        await engine.dispose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true", help="run one queue/planning cycle")
    parser.add_argument("--interval", type=float, default=30.0, help="seconds between cycles (default: 30)")
    args = parser.parse_args()
    if args.interval <= 0:
        parser.error("--interval must be positive")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    raise SystemExit(asyncio.run(run(args.once, args.interval)))


if __name__ == "__main__":
    main()
