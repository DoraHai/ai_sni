"""Customer-scoped stored click observations; never extrapolate missing reports."""
from collections import defaultdict
from datetime import datetime, timezone
from functools import lru_cache

from sqlalchemy import func, select
from app.baidu.regions import load_regions
from app.models import KeywordRegionReport, KeywordHourlyReport
from app.sem_cockpit_readonly import account_data_scope, resolve_account_scope, validate_window
from app.sem_cockpit_details import coverage, window

PROVINCES = dict(zip(
    "北京 天津 河北 山西 内蒙古 辽宁 吉林 黑龙江 上海 江苏 浙江 安徽 福建 江西 山东 河南 湖北 湖南 广东 广西 海南 重庆 四川 贵州 云南 西藏 陕西 甘肃 青海 宁夏 新疆 台湾 香港 澳门".split(),
    "110000 120000 130000 140000 150000 210000 220000 230000 310000 320000 330000 340000 350000 360000 370000 410000 420000 430000 440000 450000 460000 500000 510000 520000 530000 540000 610000 620000 630000 640000 650000 710000 810000 820000".split()))


def short_name(name):
    for suffix in ("维吾尔自治区", "壮族自治区", "回族自治区", "特别行政区", "自治区", "省", "市"):
        if name.endswith(suffix):
            return name[:-len(suffix)]
    return name


@lru_cache(maxsize=1)
def city_provinces():
    rows = load_regions()
    by_id = {r["id"]: r for r in rows}
    matches = defaultdict(set)
    for row in rows:
        root = row
        seen = set()
        while root.get("parent_id") in by_id and root["id"] not in seen:
            seen.add(root["id"])
            root = by_id[root["parent_id"]]
        code = PROVINCES.get(short_name(root["name"]))
        if code:
            matches[short_name(row["name"])].add(code)
    return {name: next(iter(codes)) for name, codes in matches.items() if len(codes) == 1}


def province_code(name):
    # Baidu provinceCityName is e.g. "江苏-苏州" or "上海-上海".
    parts = name.strip().split("-")
    if len(parts) == 2 and parts[1].strip():
        return PROVINCES.get(short_name(parts[0].strip()))
    name = short_name(name.strip())
    return PROVINCES.get(name) or city_provinces().get(name)


async def read_placement(session, tenant_id, start, end, account_id):
    validate_window(start, end)
    scope, _, _ = await resolve_account_scope(session, tenant_id, account_id)
    result = {}
    for model, key, columns in (
        (KeywordRegionReport, "region", (KeywordRegionReport.region_name, KeywordRegionReport.region_level)),
        (KeywordHourlyReport, "hourly", (KeywordHourlyReport.hour,)),
    ):
        rows = (await session.execute(select(
            model.baidu_account_id, model.report_date, *columns,
            func.sum(model.click).label("click"), func.max(model.fetched_at).label("fetched_at")
        ).where(*account_data_scope(model, tenant_id, scope), model.report_date >= start, model.report_date <= end)
        .group_by(model.baidu_account_id, model.report_date, *columns))).all()
        payload = {"coverage": coverage(rows, start, end), "source": model.__tablename__}
        if key == "region":
            # A province and its cities are overlapping reports. Choose one
            # level for each account/day, never add both levels together.
            grouped = defaultdict(list)
            for row in rows:
                grouped[(row.baidu_account_id, row.report_date)].append(row)
            clicks, unmapped = defaultdict(int), 0
            for items in grouped.values():
                chosen = [r for r in items if r.region_level == "province"]
                if not chosen:
                    chosen = [r for r in items if r.region_level == "city"]
                for row in chosen:
                    code = province_code(row.region_name)
                    if code:
                        clicks[code] += int(row.click)
                    else:
                        unmapped += int(row.click)
            payload.update(regions=[{"code": code, "clicks": n} for code, n in sorted(clicks.items())],
                           total=sum(clicks.values()), unmapped_clicks=unmapped)
        else:
            cells = [{"weekday": i // 24, "hour": i % 24, "clicks": None} for i in range(168)]
            for row in rows:
                if 0 <= row.hour <= 23:
                    cell = cells[row.report_date.weekday() * 24 + row.hour]
                    cell["clicks"] = (cell["clicks"] or 0) + int(row.click)
            payload.update(cells=cells, total=sum(c["clicks"] or 0 for c in cells))
        result[key] = payload
    return {"contract_version": "sem-cockpit-v1", "module": "sem", "is_demo": False,
            "read_only": True, "tenant_id": tenant_id, "window": window(start, end),
            "account_scope": scope, "source": "keyword_dimension_reports",
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
            "units": {"cost": "CNY", "click": "count", "impression": "count", "ctr": "ratio", "cpc": "CNY/click"},
            **result}
