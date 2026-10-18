"""Manual destinations reuse a reviewed draft, without creating channel variants."""
import asyncio
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.geo.content import routes
from app.geo.content.gate import PublishGateError
from app.geo.content.review import assert_review_approved
from app.geo.content.schemas import PublicationCreate
from app.geo.publication_monitor import list_monitor, state_for
from app.models import GeoPublication


@pytest.fixture
def case(monkeypatch):
    task = NS(id=12, tenant_id=7, review_status='approved', period_id=4)
    variant = NS(id=3, task_id=12, article_version_id=16, channel='website',
                 title='测试稿件', body_markdown='测试正文', adapt_meta={}, status='ready')
    saved = []

    async def flush():
        for i, pub in enumerate(saved, 1):
            pub.id = i

    session = NS(get=AsyncMock(return_value=task), refresh=AsyncMock(),
                 scalar=AsyncMock(return_value=None), add=Mock(side_effect=saved.append),
                 flush=AsyncMock(side_effect=flush), commit=AsyncMock())

    def gate(_, *, task, brand):
        try:
            assert_review_approved(task)
        except ValueError as exc:
            raise PublishGateError(str(exc)) from exc

    monkeypatch.setattr(routes, 'ensure_geo_entitlement', AsyncMock())
    monkeypatch.setattr(routes, '_variants', AsyncMock(return_value=[variant]))
    monkeypatch.setattr(routes, '_latest_article', AsyncMock(return_value=NS(id=16)))
    monkeypatch.setattr(routes, '_build_rule_input', AsyncMock(return_value=None))
    monkeypatch.setattr(routes, '_ensure_tenant_exists', AsyncMock(return_value=NS(id=7)))
    monkeypatch.setattr(routes, '_brand_context_for_task', AsyncMock(return_value=('测试品牌', [])))
    monkeypatch.setattr(routes, '_ensure_default_publishing_channels', AsyncMock(return_value=[]))
    monkeypatch.setattr(routes, '_sync_task_pipeline', AsyncMock())
    monkeypatch.setattr(routes, '_task_payload', AsyncMock(return_value={'id': 12}))
    monkeypatch.setattr(routes, 'assert_can_publish', Mock(side_effect=gate))
    return NS(task=task, variant=variant, session=session, saved=saved,
              ctx=NS(ensure_tenant=Mock()))


def register(case, **payload):
    req = PublicationCreate(**{'tenant_id': 7, 'channel': 'website',
                              'published_url': 'https://example.invalid/article', **payload})
    return asyncio.run(routes.record_publication(12, req, case.ctx, case.session))


@pytest.mark.parametrize('channel', ['news_source', 'baidu_zhidao', 'baidu_tieba', 'toutiao'])
def test_new_destination_writes_using_explicit_reviewed_source(case, channel):
    register(case, channel=channel, source_variant_id=3)
    pub, = case.saved
    assert (pub.channel, pub.variant_id, pub.publish_mode) == (channel, 3, 'manual_export')
    assert pub.published_url == 'https://example.invalid/article'
    assert state_for(case.variant, pub)['baseline_source'] == 'publication_registration'
    case.session.refresh.assert_any_await(case.task, with_for_update=True)
    case.session.refresh.assert_any_await(case.variant, with_for_update=True)
    assert routes.assert_can_publish.call_count == 2
    case.ctx.ensure_tenant.assert_called_once_with(7)
    case.session.commit.assert_awaited_once()


@pytest.mark.parametrize('channel', ['website', 'wechat', 'zhihu', 'baijiahao', 'toutiao'])
def test_original_five_channels_keep_existing_payload(case, channel):
    case.variant.channel = channel
    register(case, channel=channel)
    assert case.saved[0].channel == channel
    assert case.saved[0].variant_id == 3


@pytest.mark.parametrize('name', ['  科技日报  ', '名' * 30, 'website'])
def test_custom_channel_persists_trimmed_name_and_monitor_displays_it(case, name):
    register(case, channel='other', custom_channel_name=name, source_variant_id=3)
    pub, = case.saved
    assert pub.channel == name.strip()
    assert GeoPublication.__table__.c.channel.type.length == 32
    case.session.scalar.return_value = 'published'
    case.session.execute = AsyncMock(return_value=NS(all=lambda: [(pub, case.variant)]))
    result = asyncio.run(list_monitor(case.session, 7, 12))
    assert result['items'][0]['channel_name'] == name.strip()
    assert result['items'][0]['channel'] == name.strip()


@pytest.mark.parametrize('name', [None, '', '   ', '!@#！？', '📰', '名' * 31, '日报\n频道'])
def test_custom_name_is_validated_on_server(case, name):
    with pytest.raises(ValidationError):
        register(case, channel='other', custom_channel_name=name, source_variant_id=3)
    case.session.add.assert_not_called()
    case.session.commit.assert_not_awaited()


@pytest.mark.parametrize('channel', ['!!!', '名' * 31, '自定义渠道'])
def test_direct_channel_cannot_bypass_custom_name_validation(case, channel):
    with pytest.raises(HTTPException) as error:
        register(case, channel=channel, source_variant_id=3)
    assert error.value.status_code == 400
    case.session.add.assert_not_called()


@pytest.mark.parametrize('url', ['http://example.invalid/a', 'https://',
    'https://example.invalid:bad/a', 'https://example.invalid:0/a',
    'https://user:pass@example.invalid/a', 'https://example.invalid/a\nb'])
def test_only_complete_https_links_can_be_registered(case, url):
    with pytest.raises(HTTPException) as error:
        register(case, published_url=url)
    assert error.value.status_code == 400
    case.session.add.assert_not_called()


@pytest.mark.parametrize('source', [None, 999])
def test_new_destination_requires_source_from_this_task(case, source):
    with pytest.raises(HTTPException) as error:
        register(case, channel='news_source', source_variant_id=source)
    assert error.value.status_code == 400
    case.session.add.assert_not_called()


@pytest.mark.parametrize('status', ['none', 'pending', 'rejected'])
def test_new_and_custom_channels_cannot_bypass_customer_review(case, status):
    case.task.review_status = status
    for payload in [dict(channel='news_source'), dict(channel='other', custom_channel_name='日报')]:
        with pytest.raises(HTTPException) as error:
            register(case, **payload, source_variant_id=3)
        assert error.value.status_code == 400
    case.session.add.assert_not_called()
    case.session.commit.assert_not_awaited()


def test_review_revoked_at_final_write_lock_is_rejected(case):
    async def refresh(obj, **kwargs):
        if obj is case.task and kwargs.get('with_for_update'):
            case.task.review_status = 'pending'
    case.session.refresh.side_effect = refresh
    with pytest.raises(HTTPException) as error:
        register(case, channel='other', custom_channel_name='日报', source_variant_id=3)
    assert error.value.status_code == 400
    case.session.add.assert_not_called()


def test_stale_source_draft_is_rejected_at_write_lock(case):
    case.variant.article_version_id = 15
    with pytest.raises(HTTPException) as error:
        register(case, channel='news_source', source_variant_id=3)
    assert error.value.status_code == 400
    case.session.add.assert_not_called()


def test_tenant_mismatch_is_rejected_before_variant_lookup(case):
    with pytest.raises(HTTPException) as error:
        register(case, tenant_id=8, channel='news_source', source_variant_id=3)
    assert error.value.status_code == 404
    routes._variants.assert_not_awaited()
    case.session.add.assert_not_called()


def test_unauthorized_tenant_is_rejected_before_entitlement(case):
    case.ctx.ensure_tenant.side_effect = HTTPException(403, '无权访问该客户')
    with pytest.raises(HTTPException) as error:
        register(case, channel='news_source', source_variant_id=3)
    assert error.value.status_code == 403
    routes.ensure_geo_entitlement.assert_not_awaited()
    case.session.get.assert_not_awaited()


def test_deduplication_keeps_destination_identity(case):
    register(case, channel='news_source', source_variant_id=3)
    query = case.session.scalar.await_args.args[0]
    assert 'geo_publications.channel' in str(query)
    assert 'news_source' in query.compile().params.values()
    case.session.scalar.return_value = case.saved[0]
    register(case, channel='news_source', source_variant_id=3)
    assert len(case.saved) == 1
