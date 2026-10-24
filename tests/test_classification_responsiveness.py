"""Synthetic ORM rows and fake sessions only: no database or remote services."""
import asyncio
import json
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from tests import sem_cockpit_fixtures  # isolated dummy application settings
from app import classification
from app.models import Keyword, Tenant


STAMP = datetime(2026, 10, 24, 1)
OLD_STAMP = datetime(2026, 10, 1)


class FrozenDatetime:
    @staticmethod
    def utcnow():
        return STAMP


def keyword_rows(size):
    # Brand overrides focus/new; manual categories/timestamps never change.
    variants = [
        ("ACME 水泵", [31], "auto", "normal", 0),
        ("重点词", [31], "auto", "new", 0),
        ("新词", None, "auto", "normal", 19),
        ("一般词", [], "auto", "new", 20),
        ("长尾词", [31], "manual", "longtail", 100),
        ("acme 已分类", [], "auto", "brand", 20),
        (None, None, "auto", "normal", 0),
    ]
    rows, impressions = [], []
    for i in range(size):
        text, tabs, source, category, total = variants[i % len(variants)]
        rows.append(Keyword(keyword_id=i, keyword=text, tabs=tabs,
                            category_source=source, category=category,
                            total_impression=-1, category_updated_at=OLD_STAMP))
        # Exercise the missing-impression default as well.
        if i % len(variants) != 6:
            impressions.append((i, total))
    return rows, impressions


def fake_session(rows, impressions):
    return SimpleNamespace(
        execute=AsyncMock(return_value=SimpleNamespace(all=lambda: impressions)),
        scalars=AsyncMock(return_value=SimpleNamespace(all=lambda: rows)),
        commit=AsyncMock(),
    )


async def original_loop(rows, impressions, tenant):
    """The pre-fix loop, kept as an output and scheduling reference."""
    totals = dict(impressions)
    terms = classification.resolve_brand_terms(tenant)
    counts = {}
    for kw in rows:
        kw.total_impression = totals.get(kw.keyword_id, 0)
        if kw.category_source != "manual":
            new_cat = classification.classify_one(kw.keyword, kw.tabs, kw.total_impression, terms)
            if kw.category != new_cat:
                kw.category = new_cat
                kw.category_updated_at = STAMP
        counts[kw.category] = counts.get(kw.category, 0) + 1
    return counts


async def measure(operation, rows):
    loop = asyncio.get_running_loop()
    gaps, bursts = [], []
    running = True

    async def heartbeat():
        previous = loop.time()
        previous_count = 0
        while running:
            await asyncio.sleep(0)
            current = loop.time()
            gaps.append(current - previous)
            count = sum(kw.total_impression != -1 for kw in rows)
            bursts.append(count - previous_count)
            previous_count, previous = count, loop.time()

    task = asyncio.create_task(heartbeat())
    await asyncio.sleep(0)
    counts = await operation()
    await asyncio.sleep(0)
    running = False
    await task
    return counts, max(gaps), max(bursts)


def test_14000_keywords_keep_results_and_allow_other_tasks(monkeypatch):
    monkeypatch.setattr(classification, "datetime", FrozenDatetime)
    tenant = Tenant(id=11, name="fallback", brand_terms=[" ACME ", "acme", ""])
    old_rows, impressions = keyword_rows(14000)
    new_rows, _ = keyword_rows(14000)
    session = fake_session(new_rows, impressions)

    async def run():
        old = await measure(lambda: original_loop(old_rows, impressions, tenant), old_rows)
        new = await measure(lambda: classification.reclassify_keywords(session, tenant), new_rows)
        return old, new

    old, new = asyncio.run(run())
    assert old[0] == new[0] == {"brand": 4000, "focus": 2000, "new": 4000,
                               "normal": 2000, "longtail": 2000}
    state = lambda rows: [(kw.category, kw.total_impression, kw.category_updated_at) for kw in rows]
    assert state(old_rows) == state(new_rows)
    assert old[2] == 14000
    # Deterministic responsiveness bound; wall time is reported, not a flaky
    # shared-runner timing assertion. The heartbeat sees at most one batch.
    assert new[2] <= 128
    print(json.dumps({"keywords": 14000, "before_max_pause_ms": round(old[1] * 1000, 3),
                      "after_max_pause_ms": round(new[1] * 1000, 3),
                      "before_max_rows_without_yield": old[2],
                      "after_max_rows_without_yield": new[2]}))
    session.commit.assert_awaited_once()


@pytest.mark.parametrize("size", [0, 1, 127, 128, 129])
def test_batch_edges_and_tenant_name_fallback(size, monkeypatch):
    monkeypatch.setattr(classification, "datetime", FrozenDatetime)
    tenant = Tenant(id=11, name="ACME", brand_terms=None)
    old_rows, impressions = keyword_rows(size)
    new_rows, _ = keyword_rows(size)
    session = fake_session(new_rows, impressions)
    expected = asyncio.run(original_loop(old_rows, impressions, tenant))
    assert asyncio.run(classification.reclassify_keywords(session, tenant)) == expected
    assert [(k.category, k.total_impression, k.category_updated_at) for k in new_rows] == [
        (k.category, k.total_impression, k.category_updated_at) for k in old_rows]
    session.commit.assert_awaited_once()
