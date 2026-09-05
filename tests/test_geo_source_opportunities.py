import asyncio
from datetime import datetime, date
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest

from app.geo.content.source_opportunities import build_source_opportunities, source_url


def snapshot(i=1, **overrides):
    values = dict(id=i, prompt_id=1, engine=f"engine-{i % 2}", captured_at=datetime(2026, 9, 5),
                  sample_mode="openai_compat", simulated=False, mentions_brand=False,
                  cited_urls=["https://source.example/article", "https://source.example/article#section"],
                  note="API采样 · method=unprimed_json_v2 · analysis=completed", citation_accuracy="unknown")
    values.update(overrides)
    return SimpleNamespace(**values)


def build(rows, **kwargs):
    return build_source_opportunities(rows, prompts={1: SimpleNamespace(question="如何选择设备？", is_brand_probe=False)},
                                      own_domains=kwargs.get("own_domains", ["brand.example"]))


def test_dedup_and_explainable_priority_with_original_evidence():
    first = snapshot()
    result = build([first, first, snapshot(2), snapshot(3)])
    item = result["items"][0]
    assert result["eligible_samples"] == 3
    assert item["external_citation_count"] == 3
    assert item["priority"] == "优先核对"
    assert [e["snapshot_id"] for e in item["evidence"]] == [3, 2, 1]
    assert item["evidence"][0]["urls"] == ["https://source.example/article"]
    assert "不" in result["note"]


@pytest.mark.parametrize("change,reason", [
    ({"simulated": True}, "non_api"),
    ({"sample_mode": "manual"}, "non_api"),
    ({"note": "旧记录"}, "legacy_method"),
    ({"note": "method=unprimed_json_v2 · analysis=needs_review"}, "needs_review"),
    ({"note": "method=unprimed_json_v2"}, "needs_review"),
    ({"prompt_id": 99}, "brand_probe_or_missing_prompt"),
    ({"citation_accuracy": "inaccurate"}, "inaccurate_citation"),
])
def test_unreliable_samples_do_not_create_opportunities(change, reason):
    result = build([snapshot(**change)])
    assert result["items"] == []
    assert result["excluded_samples"][reason] == 1


def test_brand_probe_excluded():
    result = build_source_opportunities([snapshot()], prompts={1: SimpleNamespace(question="品牌好吗", is_brand_probe=True)}, own_domains=[])
    assert result["items"] == []


def test_no_owned_domain_configuration_never_asserts_owned_gap():
    assert build([snapshot(mentions_brand=True)], own_domains=[])["items"] == []
    result = build([snapshot()], own_domains=[])
    assert not result["own_domains_configured"]
    assert "自有域" not in result["items"][0]["reason"]


def test_subdomain_is_owned_and_suffix_impersonation_is_external():
    assert build([snapshot(cited_urls=["https://docs.brand.example/a"])])["items"] == []
    assert len(build([snapshot(cited_urls=["https://brand.example.evil.test/a"])])["items"]) == 1


def test_own_citation_elsewhere_in_same_question_prevents_false_gap():
    result = build([snapshot(mentions_brand=True), snapshot(2, mentions_brand=True, cited_urls=["https://brand.example/a"])])
    assert result["items"] == []


@pytest.mark.parametrize("url", ["javascript:alert(1)", "file:///c:/secret", "https://u:p@example.com/a", "https://x.test:bad/a", "https://[broken"])
def test_bad_urls_not_used(url):
    assert source_url(url) is None
    assert build([snapshot(cited_urls=[url])])["items"] == []


def test_single_sample_is_not_marked_priority():
    assert build([snapshot()])["items"][0]["priority"] == "补充采样"


def test_route_checks_tenant_before_reading():
    from app.geo.content.routes import citation_insights
    ctx = Mock()
    ctx.ensure_tenant.side_effect = PermissionError("wrong tenant")
    session = AsyncMock()
    with pytest.raises(PermissionError):
        asyncio.run(citation_insights(tenant_id=7, date_from=None, date_to=None, days=14, ctx=ctx, session=session))
    ctx.ensure_tenant.assert_called_once_with(7)
    session.scalars.assert_not_awaited()


def test_route_passes_only_tenant_window_rows_and_tenant_prompts():
    from app.geo.content.routes import citation_insights
    session = AsyncMock()
    session.scalars.side_effect = [[snapshot()], [SimpleNamespace(id=1, question="如何选设备", is_brand_probe=False)]]
    with patch('app.geo.content.routes._own_domains_for_tenant', new=AsyncMock(return_value=['brand.example'])), patch(
        'app.geo.content.routes._snapshot_payload', return_value={}
    ):
        result = asyncio.run(citation_insights(tenant_id=7, date_from=date(2026, 9, 1), date_to=date(2026, 9, 5), days=14, ctx=Mock(), session=session))
    assert len(result['source_opportunities']['items']) == 1
    first = session.scalars.call_args_list[0].args[0].compile().params
    assert first['tenant_id_1'] == 7
    assert first['captured_at_1'].isoformat() == '2026-08-31T16:00:00'
    assert first['captured_at_2'].isoformat() == '2026-09-05T16:00:00'
    assert session.scalars.call_args_list[1].args[0].compile().params['tenant_id_1'] == 7


def test_evidence_version_independent_of_database_row_order():
    first, second = snapshot(1), snapshot(2)
    assert build([first, second])["items"][0]["evidence_version"] == build([second, first, first])["items"][0]["evidence_version"]


def test_evidence_version_changes_with_question_or_domain_configuration():
    row = snapshot()
    old = build([row])["items"][0]["evidence_version"]
    assert old != build([row], own_domains=["different.example"])["items"][0]["evidence_version"]
    changed = build_source_opportunities([row], prompts={1: SimpleNamespace(question="新问题", is_brand_probe=False)}, own_domains=["brand.example"])
    assert old != changed["items"][0]["evidence_version"]


def citation_result(rows):
    from app.geo.content.routes import citation_insights
    session = AsyncMock()
    session.scalars.side_effect = [rows, [SimpleNamespace(id=1, question="如何选设备", is_brand_probe=False)]]
    with patch('app.geo.content.routes._own_domains_for_tenant', new=AsyncMock(return_value=['brand.example'])), patch('app.geo.content.routes._snapshot_payload', return_value={}):
        return asyncio.run(citation_insights(tenant_id=7, date_from=None, date_to=None, days=None, ctx=Mock(), session=session))


def test_citation_stats_exclude_simulation_but_opportunities_disclose_it():
    result = citation_result([snapshot(), snapshot(2, sample_mode="mock_persona")])
    assert result['total_snapshots'] == 1
    assert result['excluded_simulated'] == 1
    assert result['source_opportunities']['excluded_samples']['non_api'] == 1
    assert result['items'][0]['engine_counts'] == {'engine-1': 1}
    assert result['window']['start'] is not None


def test_citation_mixed_method_hides_rate_but_keeps_counts():
    result = citation_result([snapshot(cited_urls=['https://brand.example/a']), snapshot(2, note='历史采样')])
    assert result['rates_comparable'] is False
    assert result['own_domain_cite_rate'] is None
    assert result['snapshots_with_citations'] == 2


def test_citation_counts_actual_engine_hits_instead_of_averaging():
    result = citation_result([snapshot(1), snapshot(3), snapshot(5), snapshot(2)])
    assert result['items'][0]['engine_counts'] == {'engine-1': 3, 'engine-0': 1}
    assert result['items'][0]['cite_count'] == 4


def test_citation_invalid_window_rejected_before_query():
    from app.geo.content.routes import citation_insights
    from fastapi import HTTPException
    session = AsyncMock()
    with pytest.raises(HTTPException) as error:
        asyncio.run(citation_insights(tenant_id=7, date_from=date(2026, 9, 5), date_to=date(2026, 9, 1), days=14, ctx=Mock(), session=session))
    assert error.value.status_code == 400
    session.scalars.assert_not_awaited()
