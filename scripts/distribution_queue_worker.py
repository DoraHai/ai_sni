"""Explicit central worker entrance; starts no platform tool and applies no DDL.

Run from the selected backend root: python -m scripts.distribution_queue_worker
--once is suitable for an existing scheduler. Continuous mode resumes durable
configurations on process restart; DATABASE_URL must be explicitly configured.
"""
import argparse
import asyncio
import os
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker


async def run(once, interval, module=None):
    url = os.environ.get('DATABASE_URL')
    if not url: raise RuntimeError('Explicit DATABASE_URL required')
    from app.distribution_queue import run_once
    from app.distribution_planning import run_once as plan_once
    from app.distribution_execution import run_once as dispatch_once
    engine = create_async_engine(url, pool_pre_ping=True)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        while True:
            await run_once(sessions,module=module)
            await plan_once(sessions,module=module)
            await dispatch_once(sessions,module=module)
            if once: return
            await asyncio.sleep(interval)
    finally:
        await engine.dispose()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--once', action='store_true')
    parser.add_argument('--interval', type=int, default=30)
    args = parser.parse_args()
    if not 5 <= args.interval <= 3600: parser.error('interval must be 5..3600 seconds')
    asyncio.run(run(args.once,args.interval))
