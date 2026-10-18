"""Only synthetic receipts and mocked storage; no real tenants or credentials."""
import asyncio
import json
from contextlib import ExitStack
from datetime import datetime
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock, patch

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.database import get_session
from app.geo.content import receipt_import as receipts, routes
from app.geo.content.gate import PublishGateError
from app.security.auth import AuthContext, require_scoped_auth, _required
from app.security.advisor_scope import AdvisorScope


def row(**changes):
    return {"article_id": "12", "platform": "website", "public_url": "https://example.invalid/a",
            "published_at": "2026-10-20T09:30:00+08:00", "note": "合成测试", **changes}


@pytest.fixture
def fixture():
    task = NS(id=12, tenant_id=7, prompt_id=8, business_id=20, review_status="approved")
    variants = [NS(id=3, task_id=12, channel="website", article_version_id=16),
                NS(id=4, task_id=12, channel="wechat", article_version_id=16)]
    session = NS(scalar=AsyncMock(return_value=task), scalars=AsyncMock(side_effect=[[], []]),
                 commit=AsyncMock(), rollback=AsyncMock(), flush=AsyncMock(), add=Mock())
    ctx = AuthContext(9, "synthetic-editor", "编辑", 7, {"geo.content": "edit"})
    with ExitStack() as stack:
        patches = {
            "ensure_geo_entitlement": AsyncMock(), "_variants": AsyncMock(return_value=variants),
            "_latest_article": AsyncMock(return_value=NS(id=16)), "_build_rule_input": AsyncMock(),
            "_ensure_tenant_exists": AsyncMock(), "_brand_context_for_task": AsyncMock(return_value=("测试品牌", [])),
            "assert_can_publish": Mock(), "_write_publication": AsyncMock(return_value=True),
        }
        for name, value in patches.items():
            stack.enter_context(patch.object(routes, name, value))
        stack.enter_context(patch.object(receipts, "project_scope", AsyncMock(return_value=(NS(id=5), [20]))))
        stack.enter_context(patch.object(receipts, "prompt_ids_for_businesses", AsyncMock(return_value=[8])))
        yield NS(task=task, variants=variants, session=session, ctx=ctx, **patches)


def run(f, rows=None, dry_run=True):
    return asyncio.run(receipts.import_receipts(f.session, ctx=f.ctx, tenant_id=7, project_id=5,
        task_id=12, rows=rows or [row()], dry_run=dry_run))


def test_normal_preview_does_not_write_and_confirm_uses_existing_writer(fixture):
    f = fixture
    result = run(f)
    assert result["can_confirm"] and not result["committed"]
    assert result["rows"][0]["status"] == "能导入"
    f._write_publication.assert_not_awaited()
    f.session.commit.assert_not_awaited(); f.session.flush.assert_not_awaited(); f.session.add.assert_not_called()
    f.session.scalars.side_effect = [[], []]
    result = run(f, dry_run=False)
    assert result["committed"] and result["changed"] == 1
    args = f._write_publication.await_args.kwargs
    assert args["variant"] is f.variants[0] and args["task"] is f.task
    assert args["published_url"] == "https://example.invalid/a"
    assert args["published_at"] == datetime(2026, 10, 20, 1, 30)
    assert args["note"] == "合成测试" and args["publish_mode"] == "manual_export"
    f.session.commit.assert_awaited_once()


@pytest.mark.parametrize("status", ["none", "pending", "rejected"])
@pytest.mark.parametrize("dry_run", [True, False])
def test_customer_review_blocks_entire_batch(fixture, status, dry_run):
    f = fixture; f.task.review_status = status
    result = run(f, [row(), row(platform="wechat", public_url="https://example.invalid/b")], dry_run)
    assert not result["can_confirm"] and not result["committed"]
    assert all("审核" in item["reason"] for item in result["rows"])
    f._write_publication.assert_not_awaited(); f.session.commit.assert_not_awaited()


@pytest.mark.parametrize("changes,reason", [
    ({"public_url": "http://example.invalid/a"}, "https://"),
    ({"public_url": "https://u:p@example.invalid/a"}, "账号"),
    ({"public_url": "https://example.invalid/a b"}, "空格"),
    ({"public_url": "https://example.invalid:bad/a"}, "https://"),
    ({"public_url": "https://example.invalid:0/a"}, "https://"),
    ({"article_id": "999"}, "当前客户"), ({"tenant_id": "99"}, "当前客户"),
    ({"project_id": "99"}, "当前客户"), ({"variant_id": "999"}, "当前客户"),
    ({"platform": "不存在的渠道"}, "认不出"), ({"published_at": "2026-10-20 09:30"}, "时区"),
    ({"status": "unknown"}, "核实"), ({"note": "x" * 1001}, "1000"),
])
def test_invalid_rows_block_whole_batch_with_plain_reason(fixture, changes, reason):
    f = fixture
    result = run(f, [row(platform="wechat", public_url="https://example.invalid/b"), row(**changes)], False)
    assert not result["committed"] and reason in result["rows"][1]["reason"]
    f._write_publication.assert_not_awaited(); f.session.commit.assert_not_awaited()


def test_same_record_with_different_links_requires_resolution(fixture):
    result = run(fixture, [row(), row(public_url="https://example.invalid/different")], False)
    assert not result["committed"] and "不同链接" in result["rows"][1]["reason"]


def test_duplicate_rows_and_duplicate_link_across_channels_only_written_once(fixture):
    f = fixture
    result = run(f, [row(), row(), row(platform="wechat")], False)
    assert result["changed"] == 1 and result["committed"]
    assert [item["status"] for item in result["rows"]] == ["已导入", "无需导入", "无需导入"]
    f._write_publication.assert_awaited_once()


def test_repeat_upload_uses_normalized_url_identity_and_keeps_query(fixture):
    f = fixture
    f.session.scalars.side_effect = [[], [NS(variant_id=3, channel="website", published_url="https://EXAMPLE.invalid:443/a#heading")]]
    result = run(f, dry_run=False)
    assert result["committed"] and result["changed"] == 0
    f._write_publication.assert_not_awaited()
    assert receipts.https_url("https://example.invalid/?id=1")[1] != receipts.https_url("https://example.invalid/?id=2")[1]


def test_existing_record_with_other_link_is_not_overwritten(fixture):
    f = fixture; f.session.scalars.side_effect = [[], [NS(variant_id=3, channel="website", published_url="https://example.invalid/old")]]
    result = run(f, dry_run=False)
    assert not result["committed"] and "不会覆盖" in result["rows"][0]["reason"]


def test_stale_variant_and_gate_change_deny_confirmation(fixture):
    f = fixture; f.variants[0].article_version_id = 15
    assert "落后母稿" in run(f, dry_run=False)["rows"][0]["reason"]
    f.session.scalars.side_effect = [[], []]; f.variants[0].article_version_id = 16
    f.assert_can_publish.side_effect = PublishGateError("internal_rule_code")
    result = run(f, dry_run=False)
    assert not result["committed"] and "发布要求" in result["message"]
    assert "internal_rule_code" not in str(result)


def test_failed_second_write_rolls_back_the_entire_batch(fixture):
    f = fixture; f._write_publication.side_effect = [True, PublishGateError("changed")]
    with pytest.raises(HTTPException) as denied:
        run(f, [row(), row(platform="wechat", public_url="https://example.invalid/b")], False)
    assert denied.value.status_code == 409
    f.session.rollback.assert_awaited_once(); f.session.commit.assert_not_awaited()


def test_unknown_or_foreign_task_uses_tenant_and_project_scoped_query(fixture):
    f = fixture; f.session.scalar.return_value = None
    with pytest.raises(HTTPException) as denied:
        run(f, dry_run=False)
    assert denied.value.detail == receipts.SCOPE_ERROR
    statement = f.session.scalar.await_args.args[0]
    sql = str(statement)
    assert "tenant_id =" in sql and "prompt_id IN" in sql and "business_id IN" in sql and "FOR UPDATE" in sql
    assert 7 in statement.compile().params.values()
    f._write_publication.assert_not_awaited()


def test_new_channel_value_is_supported_without_a_hardcoded_platform_list(fixture):
    f = fixture; f.variants[0].channel = "future_custom"
    assert run(f, [row(platform="future_custom")])["can_confirm"]


def test_template_chinese_platform_name_resolves_existing_profile(fixture):
    assert run(fixture, [row(platform="官网 / 博客")])["can_confirm"]


def test_permission_and_advisor_scope_are_not_widened(fixture):
    f = fixture; f.ctx.permissions = {"geo.content": "view"}
    with pytest.raises(HTTPException) as denied:
        run(f)
    assert denied.value.status_code == 403
    f.ensure_geo_entitlement.assert_not_awaited()
    f.ctx.permissions = {"geo.content": "edit"}
    f.ctx.advisor_scope = AdvisorScope(frozenset())
    with pytest.raises(HTTPException) as denied:
        run(f)
    assert denied.value.status_code == 403
    assert _required("/api/v1/geo/content-tasks/12/import-receipts", "POST") == ({"geo.content"}, True)


def test_csv_json_bom_and_optional_fields():
    csv = '\ufeffarticle_id,platform,public_url,published_at,note\r\n12,website,https://example.invalid/a,,"备注,有逗号"\r\n'
    assert receipts.parse_receipts(csv.encode(), "receipt.CSV")[0]["note"] == "备注,有逗号"
    assert receipts.parse_receipts(json.dumps([row()]).encode(), "receipt.json") == [row()]
    assert receipts.published_time("") is None


@pytest.mark.parametrize("data,name", [(b"broken", "x.json"), (b"\xff", "x.csv"),
    (b"{}", "x.json"), (b"[]", "x.json"), (b"x", "x.xlsx"),
    (b"article_id,platform,public_url\n12,website\n", "x.csv"),
    (b"article_id,platform,public_url,public_url\n12,w,a,b\n", "x.csv"),
    (b"x" * (receipts.MAX_BYTES + 1), "x.csv"),
    (json.dumps([row()] * 201).encode(), "x.json"),
    (b"article_id,platform,public_url\n" + b"12,website,https://example.invalid/a\n" * 201, "x.csv")],
    ids=["broken-json", "encoding", "object", "empty", "extension", "missing-column", "duplicate-header",
         "too-large", "too-many-json", "too-many-csv"])
def test_bad_files_and_limits(data, name):
    with pytest.raises(ValueError):
        receipts.parse_receipts(data, name)


def test_multipart_http_preview_then_confirmation(fixture):
    f = fixture
    app = FastAPI(); app.include_router(routes.router, prefix="/api/v1/geo")
    app.dependency_overrides[require_scoped_auth] = lambda: f.ctx
    app.dependency_overrides[get_session] = lambda: f.session
    client = TestClient(app)
    path = "/api/v1/geo/content-tasks/12/import-receipts?tenant_id=7&project_id=5"
    data = json.dumps([row()]).encode()
    response = client.post(path, files={"file": ("receipts.json", data, "application/json")})
    assert response.status_code == 200 and response.json()["dry_run"]
    f._write_publication.assert_not_awaited()
    f.session.scalars.side_effect = [[], []]
    response = client.post(path + "&dry_run=false", files={"file": ("receipts.json", data, "application/json")})
    assert response.status_code == 200 and response.json()["changed"] == 1
    response = client.post(path, files={"file": ("broken.json", b"{", "application/json")})
    assert response.status_code == 400 and "文件" in response.json()["detail"]


@pytest.mark.parametrize('platform,channel', [
    ('news_source', 'news_source'), ('新闻源', 'news_source'),
    ('baidu_zhidao', 'baidu_zhidao'), ('百度问答（百度知道）', 'baidu_zhidao'),
    ('百度问答', 'baidu_zhidao'), ('百度知道', 'baidu_zhidao'),
    ('baidu_tieba', 'baidu_tieba'), ('百度贴吧', 'baidu_tieba'),
    ('toutiao', 'toutiao'), ('今日头条', 'toutiao'),
    ('zhihu', 'zhihu'), ('知乎', 'zhihu'), ('百家号', 'baijiahao'),
])
def test_destination_without_own_draft_uses_explicit_source(fixture, platform, channel):
    f = fixture
    result = run(f, [row(platform=platform, variant_id='3')], False)
    assert result['committed'] and result['changed'] == 1
    args = f._write_publication.await_args.kwargs
    assert args['variant'] is f.variants[0] and args['channel'] == channel
    assert args['channel_name'] is None and len(f.variants) == 2


@pytest.mark.parametrize('platform', ['other', '其他'])
def test_custom_name_uses_same_writer_metadata_as_single_backfill(fixture, platform):
    f = fixture
    result = run(f, [row(platform=platform, channel_name='  示例科技社区  ', variant_id=3)], False)
    assert result['committed'] and result['rows'][0]['platform'] == '其他：示例科技社区'
    args = f._write_publication.await_args.kwargs
    assert args['channel'] == args['channel_name'] == '示例科技社区'
    assert args['variant'] is f.variants[0]


@pytest.mark.parametrize('name', [None, '', '   ', '!?---', '📰', '名' * 31,
    '日报\n频道', '\n日报', '日报\t', '日报\u200b', '日报\u2028', '日报\u2029'])
def test_invalid_custom_name_rejects_entire_import(fixture, name):
    f = fixture
    result = run(f, [row(), row(platform='其他', channel_name=name, variant_id=3,
        public_url='https://example.invalid/custom')], False)
    assert not result['committed'] and '渠道名称' in result['rows'][1]['reason']
    f._write_publication.assert_not_awaited()


@pytest.mark.parametrize('changes,reason', [
    ({'platform': '百度贴吧'}, 'variant_id'),
    ({'platform': '其他', 'channel_name': '社区'}, 'variant_id'),
    ({'platform': '百度贴吧', 'variant_id': 999}, receipts.SCOPE_ERROR),
    ({'platform': '自定义社区', 'variant_id': 3}, '认不出'),
    ({'platform': 'website', 'channel_name': '社区'}, '只有'),
])
def test_missing_or_foreign_source_and_ambiguous_format_rejected(fixture, changes, reason):
    f = fixture
    result = run(f, [row(**changes)], False)
    assert not result['committed'] and reason in result['rows'][0]['reason']
    f._write_publication.assert_not_awaited()


def test_same_source_can_register_multiple_destinations_and_custom_names(fixture):
    f = fixture
    result = run(f, [row(),
        row(platform='百度贴吧', variant_id=3, public_url='https://example.invalid/tieba'),
        row(platform='其他', channel_name='社区甲', variant_id=3, public_url='https://example.invalid/custom-a'),
        row(platform='other', channel_name='社区乙', variant_id=3, public_url='https://example.invalid/custom-b'),
    ], False)
    assert result['committed'] and result['changed'] == 4
    assert [call.kwargs['channel'] for call in f._write_publication.await_args_list] == [
        'website', 'baidu_tieba', '社区甲', '社区乙']


@pytest.mark.parametrize('custom', [False, True])
def test_new_destination_existing_link_never_overwritten(fixture, custom):
    f = fixture
    destination = '社区甲' if custom else 'baidu_tieba'
    f.session.scalars.side_effect = [[], [NS(variant_id=3, channel=destination,
        published_url='https://example.invalid/old')]]
    result = run(f, [row(platform='其他' if custom else '百度贴吧', channel_name='社区甲' if custom else '',
        variant_id=3)], False)
    assert not result['committed'] and '不会覆盖' in result['rows'][0]['reason']
    f._write_publication.assert_not_awaited()


def test_aliases_and_custom_trim_share_destination_identity(fixture):
    f = fixture
    result = run(f, [row(platform='百度贴吧', variant_id=3), row(platform='baidu_tieba', variant_id=3),
        row(platform='其他', channel_name=' 社区 ', variant_id=3, public_url='https://example.invalid/custom'),
        row(platform='other', channel_name='社区', variant_id=3, public_url='https://example.invalid/custom'),
    ], False)
    assert result['committed'] and result['changed'] == 2


def test_new_destinations_cannot_bypass_review_or_stale_source(fixture):
    f = fixture; f.task.review_status = 'pending'
    assert not run(f, [row(platform='百度贴吧', variant_id=3)], False)['committed']
    f.session.scalars.side_effect = [[], []]; f.task.review_status = 'approved'
    f.variants[0].article_version_id = 15
    assert '落后母稿' in run(f, [row(platform='百度贴吧', variant_id=3)], False)['rows'][0]['reason']
    f._write_publication.assert_not_awaited()


def test_failure_between_new_destinations_rolls_back(fixture):
    f = fixture; f._write_publication.side_effect = [True, PublishGateError('changed')]
    with pytest.raises(HTTPException) as denied:
        run(f, [row(platform='百度贴吧', variant_id=3),
            row(platform='其他', channel_name='社区', variant_id=3, public_url='https://example.invalid/custom')], False)
    assert denied.value.status_code == 409
    f.session.rollback.assert_awaited_once(); f.session.commit.assert_not_awaited()


def test_csv_and_json_accept_new_template_columns():
    data = 'article_id,platform,channel_name,variant_id,public_url\n12,其他,社区,3,https://example.invalid/a\n'
    assert receipts.parse_receipts(data.encode(), 'x.csv')[0]['channel_name'] == '社区'
    assert receipts.parse_receipts(json.dumps([row(platform='other', channel_name='社区', variant_id=3)]).encode(), 'x.json')[0]['variant_id'] == 3


def test_browser_config_is_generated_from_single_source():
    from pathlib import Path
    from app.geo.content.backfill import CONFIG
    root = Path(__file__).resolve().parents[1]
    browser = json.loads((root / 'frontend/src/utils/geoBackfillConfig.json').read_text(encoding='utf-8'))
    assert browser == CONFIG, 'Run python scripts/generate_geo_backfill_config.py'


@pytest.mark.parametrize('channel', ['website', 'wechat', 'zhihu', 'baijiahao', 'news_source',
                                   'baidu_zhidao', 'baidu_tieba', 'toutiao'])
def test_every_standard_backfill_channel_can_use_another_reviewed_source(fixture, channel):
    f = fixture
    f.variants[:] = [v for v in f.variants if v.channel != channel]
    source = f.variants[0]
    result = run(f, [row(platform=channel, variant_id=source.id)], False)
    assert result['committed'] and result['changed'] == 1
    args = f._write_publication.await_args.kwargs
    assert args['variant'] is source and args['channel'] == channel
