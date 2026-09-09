"""Build the reviewable SEO demo data package without touching a database."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.seo_demo_fixture import build_seo_demo_fixture


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/seo-demo-fixture-v1.json"),
        help="JSON output path; overwritten atomically when contents change",
    )
    parser.add_argument(
        "--proposed-tenant-id",
        type=int,
        default=None,
        help="metadata for database review only; tenant 4 is always rejected",
    )
    args = parser.parse_args()
    package = build_seo_demo_fixture(proposed_tenant_id=args.proposed_tenant_id)
    payload = json.dumps(package, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".tmp")
    temporary.write_text(payload, encoding="utf-8")
    temporary.replace(args.output)
    print(json.dumps({"output": str(args.output), "counts": package["counts"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
