"""Baidu campaign region-code helpers shared by SEM APIs and writeback validation."""

from functools import lru_cache
import json
from pathlib import Path


_REGION_DATA_PATH = Path(__file__).parent.parent / "data" / "baidu_region_codes.json"
ALL_REGIONS_ID = 9_999_999


@lru_cache(maxsize=1)
def load_regions() -> tuple[dict, ...]:
    """Load and validate the bundled Baidu region-code snapshot once."""
    raw = _REGION_DATA_PATH.read_text(encoding="utf-8")
    raw = "\n".join(
        line for line in raw.splitlines() if not line.lstrip().startswith("//")
    )
    data = json.loads(raw)
    if not isinstance(data, list):
        raise RuntimeError("百度地域编码资源格式错误")

    rows: list[dict] = []
    seen: set[int] = set()
    for item in data:
        if not isinstance(item, dict):
            raise RuntimeError("百度地域编码资源格式错误")
        region_id = item.get("id")
        name = item.get("name")
        if (
            isinstance(region_id, bool)
            or not isinstance(region_id, int)
            or region_id <= 0
            or not isinstance(name, str)
            or not name.strip()
            or region_id in seen
        ):
            raise RuntimeError("百度地域编码资源包含无效或重复条目")
        seen.add(region_id)
        rows.append(item)
    return tuple(rows)


@lru_cache(maxsize=1)
def region_ids() -> frozenset[int]:
    return frozenset(int(item["id"]) for item in load_regions())
