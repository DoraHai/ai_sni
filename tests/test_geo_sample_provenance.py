import asyncio
from functools import wraps
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.geo.content.metric_service import (
    brand_mention_rate, composition_of, compute_metrics,
    compute_metrics_from_rows, load_snapshots_in_window, resolve_exclude_simulated,
)
from app.geo.content.sample_provenance import sample_provenance


def run_async(fn):
    @wraps(fn)
    def run(*args, **kwargs):
        return asyncio.run(fn(*args, **kwargs))
    return run


def snap(index=0, **overrides):
    values = dict(prompt_id=index % 3 + 1, engine=f"engine-{index % 2}",
                  sample_mode="openai_compat", simulated=False, mentions_brand=True,
                  brand_position="first", cited_urls=[], competitors=[],
                  note="API采样 · method=unprimed_json_v2 · analysis=completed")
    values.update(overrides)
    return SimpleNamespace(**values)


@pytest.mark.parametrize("overrides", [
    {"simulated": True}, {"sample_mode": "mock_persona"},
    {"sample_mode": "manual", "note": "模拟采样 · method=unprimed_json_v2"},
])
def test_simulation_provenance_survives_old_mode_loss(overrides):
    assert sample_provenance(snap(**overrides))["sample_kind"] == "simulated"


def test_missing_method_is_legacy_not_relabelled_v2():
    assert sample_provenance(snap(note="真采样"))["sampling_method"] == "legacy"
    assert sample_provenance(snap(sample_mode="manual", note=""))["sampling_method"] == "unknown"


@pytest.mark.parametrize("bad_note", [
    "old sample", "API采样 · method=unprimed_json_v2 · analysis=needs_review",
    "API采样 · method=unprimed_json_v2",
])
def test_incompatible_or_unreviewed_samples_hide_percentages(bad_note):
    rows = [snap(i) for i in range(8)] + [snap(9, note=bad_note)]
    result = compute_metrics_from_rows(rows, probe_map={}, own_domains=[]).to_dict()
    assert result["snapshots_total"] == 9
    assert result["brand_mentions"] == 9
    assert result["brand_mention_rate"] is None
    assert result["visibility_mention_rate"] is None
    assert result["top1_rate"] is None
    assert not result["sample_composition"]["suitable_for_client"]


def test_consistent_completed_method_keeps_rates():
    rows = [snap(i) for i in range(8)]
    result = compute_metrics_from_rows(rows, probe_map={}, own_domains=[]).to_dict()
    assert result["brand_mention_rate"] == 1.0
    assert result["sample_composition"]["sampling_methods"] == {"unprimed_json_v2": 8}
    assert result["sample_composition"]["suitable_for_client"]
    assert composition_of([snap(note="")]).to_dict()["legacy_method_warning"]


@run_async
async def test_default_filter_never_reads_or_creates_settings():
    session = AsyncMock()
    assert await resolve_exclude_simulated(session, 1) is True
    assert await resolve_exclude_simulated(session, 1, False) is False
    assert not session.mock_calls


@run_async
@pytest.mark.parametrize("all_time", [True, False])
@pytest.mark.parametrize("include_simulated", [True, False])
@pytest.mark.parametrize("entry", [compute_metrics, brand_mention_rate])
async def test_metric_entry_points_apply_same_default_filter(all_time, include_simulated, entry):
    real = snap()
    rows = [real, snap(sample_mode="mock_persona"),
            snap(sample_mode="manual", note="历史模拟采样")]
    session = AsyncMock()
    session.scalars.side_effect = [rows, []]
    kwargs = dict(all_time=all_time)
    if include_simulated:
        kwargs["exclude_simulated"] = False
    if entry is compute_metrics:
        kwargs["own_domains"] = []
    result = await entry(session, 1, **kwargs)
    assert result.composition.total == (3 if include_simulated else 1)
    assert result.composition.simulated == (2 if include_simulated else 0)
    sql = str(session.scalars.call_args_list[0].args[0])
    assert "geo_answer_snapshots.tenant_id =" in sql


@run_async
async def test_window_filter_keeps_shanghai_time_bounds_and_tenant_scope():
    session = AsyncMock()
    session.scalars.return_value = [snap(), snap(sample_mode="mock_persona")]
    rows = await load_snapshots_in_window(session, 7, start=date(2026, 9, 1), end=date(2026, 9, 2))
    assert len(rows) == 1
    statement = session.scalars.call_args.args[0]
    params = statement.compile().params
    assert params["tenant_id_1"] == 7
    assert params["captured_at_1"].isoformat() == "2026-08-31T16:00:00"
    assert params["captured_at_2"].isoformat() == "2026-09-02T16:00:00"


def test_conflicting_method_is_not_treated_as_legacy():
    row = snap(note="method=unprimed_json_v2 · method=other · analysis=completed")
    result = composition_of([row]).to_dict()
    assert result["needs_review"] == 1
    assert not result["suitable_for_client"]
    assert sample_provenance(row)["sampling_method"] == "conflicting"
