"""Validate and load one immutable SEO demo fixture bundle."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.seo_demo_fixture_loader import SeoFixtureBundle, run_fixture_load


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path)
    parser.add_argument("--database-url-env", default="SEO_FIXTURE_DATABASE_URL")
    parser.add_argument("--allow-host", action="append", required=True)
    parser.add_argument("--allow-server-address", action="append", required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    database_url = os.environ.get(args.database_url_env, "")
    if not database_url:
        parser.error(f"database URL environment variable is empty: {args.database_url_env}")
    receipt = args.receipt
    if receipt.exists() or receipt.is_symlink() or not receipt.parent.is_dir():
        parser.error("--receipt must be a new file in an existing directory")
    bundle = SeoFixtureBundle.open(args.bundle)
    result = asyncio.run(
        run_fixture_load(
            database_url,
            bundle,
            allowed_hosts=set(args.allow_host),
            expected_server_addresses=set(args.allow_server_address),
        )
    )
    payload = json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    temporary = receipt.with_name(f".{receipt.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary, receipt)
    finally:
        temporary.unlink(missing_ok=True)
    print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
