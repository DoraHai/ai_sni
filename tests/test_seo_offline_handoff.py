import asyncio
import io
import json
import re
import zipfile
from contextlib import ExitStack
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException, UploadFile
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

from app.api import seo
from app.models.seo import SeoContentAsset, SeoContentPublication, SeoPublishAttempt
from app.security.auth import AuthContext
from app.seo_offline_handoff import (
    MAX_BYTES, PLATFORMS, RECEIPT_FIELDS, Receipt, encode_csv, order_package, parse_receipts,
)


def asset(**changes):
    fields = dict(id=10, tenant_id=1, site_id=2, title='测试稿，含逗号', draft='<p>已核对正文</p>',
                  humanized_content=None, content_type='article', status='ready', version_count=3)
    return SeoContentAsset(**(fields | changes))


def receipt(**changes):
    return dict(article_id='10', platform=PLATFORMS[0], account='合成测试账号A',
                public_url='https://example.invalid/article/10', published_at='2026-10-16T12:00:00+08:00',
                status='published', source_version=3, payload_hash=seo._content_confirmation_hash(asset())) | changes


def context(permission='edit', tenant=1):
    return AuthContext(user_id=7, username='synthetic', role_name='test', tenant_id=tenant,
                       permissions={'seo.content': permission})


def fixture(content=None, existing=None):
    session = MagicMock()
    session.get = AsyncMock(return_value=content or asset())
    session.scalar = AsyncMock(return_value=existing)
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    return session


def dependencies():
    stack = ExitStack()
    for name in ('_seo_site', 'require_seo_site_operational', '_require_active_content_confirmation'):
        stack.enter_context(patch.object(seo, name, new=AsyncMock()))
    return stack


def import_rows(rows, session, dry_run=True, ctx=None):
    upload = UploadFile(filename='receipts.json', file=io.BytesIO(json.dumps(rows).encode('utf-8')))
    with dependencies():
        return asyncio.run(seo.import_offline_receipts(1, 2, dry_run, upload, session, ctx or context()))


def test_json_csv_unicode_and_timezone_roundtrip():
    r = receipt()
    for data, filename in [(json.dumps([r], ensure_ascii=False).encode(), 'r.json'),
                           (('\ufeff' + encode_csv([r], RECEIPT_FIELDS)).encode(), 'r.csv')]:
        result = parse_receipts(data, filename)[0]
        assert result.account == r['account']
        assert result.published_at.isoformat() == '2026-10-16T04:00:00+00:00'


@pytest.mark.parametrize('changes', [
    {'article_id': 10}, {'article_id': '9223372036854775808'}, {'source_version': True},
    {'source_version': '3'}, {'platform': '公众号'}, {'account': ' '}, {'account': '=formula'},
    {'public_url': 'http://example.invalid/a'}, {'public_url': 'https://u@example.invalid/a'},
    {'public_url': 'https://example.invalid:bad/a'}, {'public_url': 'https://exa mple.invalid/a'},
    {'published_at': None}, {'published_at': '2026-10-16T12:00:00'}, {'payload_hash': 'bad'},
    {'status': 'pending'}, {'status': 'failed'}, {'unexpected': True},
])
def test_invalid_receipts_are_rejected_without_echoing_values(changes):
    with pytest.raises(ValueError, match='第1条回执字段无效'):
        parse_receipts(json.dumps([receipt(**changes)]).encode(), 'r.json')


@pytest.mark.parametrize('data,name', [(b'\xff', 'r.json'), (b'{}', 'r.json'), (b'[]', 'r.json'),
    (b'not-json', 'r.json'), (b'bad,headers\n1,2', 'r.csv'), (b'x', 'r.xlsx'), (b' ' * (MAX_BYTES + 1), 'r.json')],
    ids=['encoding', 'object', 'empty', 'syntax', 'headers', 'extension', 'oversized'])
def test_invalid_files(data, name):
    with pytest.raises(ValueError):
        parse_receipts(data, name)


@pytest.mark.parametrize('data', [
    b'[' * 20000 + b'0' + b']' * 20000,
    b'[{"source_version":' + b'9' * 10000 + b'}]',
], ids=['excessive-nesting', 'excessive-integer'])
def test_json_decoder_limits_return_chinese_422_before_any_write(data):
    assert len(data) < MAX_BYTES
    session = fixture()
    upload = UploadFile(filename='receipts.json', file=io.BytesIO(data))
    with dependencies(), pytest.raises(HTTPException) as exc:
        asyncio.run(seo.import_offline_receipts(1, 2, False, upload, session, context()))
    assert exc.value.status_code == 422
    assert exc.value.detail == '回执JSON内容无效或嵌套过深，请按模板重新导出'
    session.get.assert_not_awaited()
    session.scalar.assert_not_awaited()
    session.add.assert_not_called()
    session.commit.assert_not_awaited()


def test_duplicate_keys_and_urls_and_row_limit():
    for rows in ([receipt(), receipt()], [receipt(), receipt(account='合成账号B')], [receipt()] * 201):
        with pytest.raises(ValueError):
            parse_receipts(json.dumps(rows).encode(), 'r.json')


def test_platform_catalogue_frontend_matches_backend():
    source = (Path(__file__).parents[1] / 'frontend/src/views/seo/seoOfflinePlatforms.js').read_text(encoding='utf8')
    assert re.findall(r"'([^']+)'", source) == list(PLATFORMS)
    assert len(set(PLATFORMS)) == 25


def test_package_contains_both_orders_and_reusable_templates():
    order = dict(article_id='10', title='=title', content_markdown='第一行\n第二行,逗号', material_path=None,
                 target_platform=PLATFORMS[0], target_account='合成账号', scheduled_at=None,
                 source_version=3, payload_hash='a' * 64)
    with zipfile.ZipFile(io.BytesIO(order_package([order]))) as archive:
        assert json.loads(archive.read('orders.json')) == [order]
        assert "'=title" in archive.read('orders.csv').decode()
        for suffix in ('json', 'csv'):
            template = parse_receipts(archive.read('receipts-template.' + suffix), 'r.' + suffix)[0]
            assert template.status == 'unknown' and template.public_url is None


def test_export_is_read_only_and_binds_visible_snapshot():
    session = fixture()
    snapshot = {k: receipt()[k] for k in ('article_id', 'source_version', 'payload_hash')}
    req = seo.OfflineOrderExport(tenant_id=1, site_id=2, articles=[snapshot],
                                target_platform=PLATFORMS[0], target_account='合成账号')
    with dependencies():
        response = asyncio.run(seo.export_offline_orders(req, session, context()))
    with zipfile.ZipFile(io.BytesIO(response.body)) as archive:
        assert json.loads(archive.read('orders.json'))[0]['content_markdown'] == '<p>已核对正文</p>'
    session.commit.assert_not_awaited()
    session.add.assert_not_called()
    assert response.headers['cache-control'] == 'no-store'
    session = fixture(asset(version_count=4))
    with dependencies(), pytest.raises(HTTPException) as exc:
        asyncio.run(seo.export_offline_orders(req, session, context()))
    assert exc.value.status_code == 409


@pytest.mark.parametrize('status', ['published', 'failed', 'unknown'])
def test_preview_never_writes_and_commit_preserves_three_states(status):
    r = receipt(status=status)
    if status != 'published':
        r.update(public_url=None, published_at=None)
    session = fixture()
    assert import_rows([r], session)['committed'] is False
    session.add.assert_not_called()
    session.commit.assert_not_awaited()
    result = import_rows([r], session, False)
    assert result['changed'] == 1
    added = [c.args[0] for c in session.add.call_args_list]
    publication = next(x for x in added if isinstance(x, SeoContentPublication))
    audit = next(x for x in added if isinstance(x, SeoPublishAttempt))
    assert publication.status == status
    assert audit.request_summary['account'] == r['account']
    assert audit.response_summary['human_reported'] is True
    assert session.get.return_value.status == ('published' if status == 'published' else 'ready')
    assert publication.published_at == (datetime(2026, 10, 16, 4) if status == 'published' else None)
    session.commit.assert_awaited_once()


@pytest.mark.parametrize('content,code', [(asset(tenant_id=9), 404), (asset(site_id=9), 404),
    (asset(version_count=4), 409), (asset(draft='改稿未升版本'), 409), (asset(status='drafting'), 409)])
def test_scope_version_hash_and_review_guards(content, code):
    session = fixture(content)
    with pytest.raises(HTTPException) as exc:
        import_rows([receipt()], session, False)
    assert exc.value.status_code == code
    session.commit.assert_not_awaited()
    session.add.assert_not_called()


@pytest.mark.parametrize('ctx', [context('view'), context(tenant=9)])
def test_permissions_rejected_before_database_writes(ctx):
    session = fixture()
    with pytest.raises(HTTPException) as exc:
        import_rows([receipt()], session, False, ctx)
    assert exc.value.status_code == 403
    session.get.assert_not_awaited()
    session.add.assert_not_called()


def test_confirmation_failure_and_late_invalid_row_leave_whole_batch_untouched():
    session = fixture()
    r = receipt(account='合成账号B', payload_hash='b' * 64)
    with pytest.raises(HTTPException):
        import_rows([receipt(), r], session, False)
    session.add.assert_not_called()
    session.commit.assert_not_awaited()
    upload = UploadFile(filename='r.json', file=io.BytesIO(json.dumps([receipt()]).encode()))
    with dependencies(), patch.object(seo, '_require_active_content_confirmation', new=AsyncMock(side_effect=HTTPException(409))), pytest.raises(HTTPException):
        asyncio.run(seo.import_offline_receipts(1, 2, False, upload, session, context()))
    session.add.assert_not_called()


def test_idempotent_repeat_and_no_downgrade_or_reassignment():
    existing = SeoContentPublication(id=90, status='published', page_url=receipt()['public_url'],
                                     published_at=datetime(2026, 10, 16, 4))
    session = fixture(existing=existing)
    assert import_rows([receipt()], session, False)['changed'] == 0
    session.add.assert_not_called()
    with pytest.raises(HTTPException) as exc:
        import_rows([receipt(status='failed', public_url=None, published_at=None)], fixture(existing=existing), False)
    assert exc.value.status_code == 409
    session = fixture()
    session.scalar.side_effect = [None, existing]
    with pytest.raises(HTTPException) as exc:
        import_rows([receipt()], session, False)
    assert exc.value.status_code == 409
    session.add.assert_not_called()


def test_unknown_can_be_resolved_to_published_and_concurrent_conflict_rolls_back():
    existing = SeoContentPublication(id=90, status='unknown', page_url=None, published_at=None)
    session = fixture()
    session.scalar.side_effect = [existing, None]
    assert import_rows([receipt()], session, False)['changed'] == 1
    assert existing.status == 'published'
    session = fixture()
    session.commit.side_effect = IntegrityError('synthetic-conflict', {}, Exception())
    with pytest.raises(HTTPException) as exc:
        import_rows([receipt()], session, False)
    assert exc.value.status_code == 409
    session.rollback.assert_awaited_once()


@pytest.mark.parametrize('status', ['failed', 'unknown', 'published'])
def test_legacy_completion_rejects_offline_receipts_before_content_lock_or_capture(status):
    publication = SeoContentPublication(id=90, tenant_id=1, content_asset_id=10,
        platform_code='manual', publish_mode='manual', source_version=3,
        idempotency_key='offline-receipt-test-key', status=status,
        page_url=receipt()['public_url'] if status == 'published' else None)
    session = fixture(existing=publication)
    session.get.return_value = publication
    req = seo.DistributionManualComplete(tenant_id=1, site_id=2, page_url=receipt()['public_url'])
    with dependencies(), patch.object(seo, '_distribution_content', new=AsyncMock()) as content_lookup, \
            patch.object(seo, '_queue_published_page_verification', new=AsyncMock()) as capture:
        with pytest.raises(HTTPException) as exc:
            asyncio.run(seo.complete_manual_publication(90, req, session, context()))
        assert exc.value.status_code == 409
        assert exc.value.detail['code'] == 'offline_receipt_import_required'
        content_lookup.assert_not_awaited()
        capture.assert_not_awaited()
        assert asyncio.run(seo._manual_complete_denial(session, context(), publication, asset())) == 'offline_receipt_import_required'
    assert publication.status == status
    session.add.assert_not_called()
    session.commit.assert_not_awaited()
    session.scalar.assert_not_awaited()


def test_legacy_manual_completion_without_offline_key_remains_supported():
    publication = SeoContentPublication(id=90, tenant_id=1, content_asset_id=10,
        platform_code='manual', publish_mode='manual', source_version=3, status='failed')
    content = asset()
    session = fixture()
    session.get.return_value = publication
    session.refresh = AsyncMock()
    req = seo.DistributionManualComplete(tenant_id=1, site_id=2, page_url=receipt()['public_url'])
    with dependencies(), patch.object(seo, '_distribution_content', new=AsyncMock(return_value=content)), \
            patch.object(seo, '_content_confirmation_schema_ready', new=AsyncMock(return_value=False)), \
            patch.object(seo, '_queue_published_page_verification', new=AsyncMock(return_value={})):
        assert asyncio.run(seo._manual_complete_denial(session, context(), publication, content)) is None
        result = asyncio.run(seo.complete_manual_publication(90, req, session, context()))
    assert result['page_url'] == receipt()['public_url']
    assert publication.status == 'published'
    session.commit.assert_awaited_once()


@pytest.mark.parametrize('existing_count', [19, 20])
def test_published_receipt_preserves_twenty_platform_limit(existing_count):
    platforms = list(PLATFORMS[:existing_count])
    content = asset(target_platforms=platforms)
    import_rows([receipt(platform=PLATFORMS[-1])], fixture(content), False)
    assert len(content.target_platforms) == 20
    assert content.target_platforms[:existing_count] == platforms
    assert (PLATFORMS[-1] in content.target_platforms) is (existing_count == 19)


def test_http_multipart_preview_and_confirmation_use_local_file_only():
    session = fixture()
    app = FastAPI()
    app.include_router(seo.router)
    app.dependency_overrides[seo.get_session] = lambda: session
    app.dependency_overrides[seo.require_scoped_auth] = lambda: context()
    app.dependency_overrides[seo.require_seo_module_access] = lambda: context()
    payload = json.dumps([receipt(status='unknown', public_url=None, published_at=None)])
    with dependencies(), patch.object(seo, 'publish_content', new=AsyncMock(side_effect=AssertionError('provider forbidden'))) as provider:
        with TestClient(app) as client:
            response = client.post('/api/v1/seo/content-assets/offline-handoff/import-receipts',
                params={'tenant_id': 1, 'site_id': 2}, files={'file': ('r.json', payload, 'application/json')})
            assert response.status_code == 200
            assert response.json()['dry_run'] is True
            session.commit.assert_not_awaited()
            response = client.post('/api/v1/seo/content-assets/offline-handoff/import-receipts',
                params={'tenant_id': 1, 'site_id': 2, 'dry_run': 'false'}, files={'file': ('r.json', payload, 'application/json')})
            assert response.status_code == 200
            assert response.json()['committed'] is True
            assert response.json()['rows'][0]['status'] == 'unknown'
            provider.assert_not_awaited()
