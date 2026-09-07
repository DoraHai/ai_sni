"""Fail CI unless every expected real-PostgreSQL GEO case ran successfully."""

from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
from pathlib import Path


EXPECTED = {
    "test_concurrent_generate_requests_create_exactly_one_job",
    "test_job_creation_failure_rolls_back_reservation_and_allows_retry",
    "test_live_job_blocks_regeneration_after_legacy_status_reset",
    "test_live_variant_job_blocks_master_generation",
    "test_generation_reservation_is_released_by_existing_recovery[cancel]",
    "test_generation_reservation_is_released_by_existing_recovery[stale]",
    "test_sync_variant_generation_blocks_sync_and_async_competitors[False]",
    "test_sync_variant_generation_blocks_sync_and_async_competitors[True]",
    "test_sync_variant_generation_is_blocked_by_live_master_job",
    "test_failed_sync_variant_job_releases_task_and_allows_retry",
    "test_translation_verification_rejects_source_changed_while_waiting_for_row_lock",
}


def main(path: str) -> int:
    root = ET.parse(Path(path)).getroot()
    cases = [
        item
        for item in root.iter("testcase")
        if str(item.get("classname") or "").endswith("test_geo_generation_postgres")
    ]
    names = [str(item.get("name") or "") for item in cases]
    bad = [
        name
        for name, item in zip(names, cases)
        if any(item.find(tag) is not None for tag in ("failure", "error", "skipped"))
    ]
    if len(names) != len(set(names)) or set(names) != EXPECTED or bad:
        print(f"expected={sorted(EXPECTED)!r}")
        print(f"observed={sorted(names)!r}")
        print(f"failed_or_skipped={bad!r}")
        return 1
    print(f"GEO_POSTGRES_CASES_OK count={len(names)} skipped=0 failed=0")
    for name in sorted(names):
        print(name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1]))
