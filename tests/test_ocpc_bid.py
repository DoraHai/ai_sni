"""oCPC 调价使用虚拟账户和 mock；绝不调用百度或生产数据库。"""
import asyncio
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

for key, value in {
    'DATABASE_URL': 'postgresql+asyncpg://test:test@localhost/test',
    'BAIDU_APP_ID': 'test', 'BAIDU_SECRET_KEY': '1234567890abcdefsecret',
    'BAIDU_DEFAULT_USERNAME': 'test', 'BAIDU_DEFAULT_UCID': '1',
    'BAIDU_SELF_ACCESS_TOKEN': 'test', 'BAIDU_SELF_TOKEN_EXPIRES_AT': '2099-01-01T00:00:00',
    'CRYPTO_MASTER_KEY_B64': 'AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=',
    'ADMIN_API_KEY': 'test',
}.items():
    os.environ.setdefault(key, value)

from app.baidu import ocpc_writeback as wb
from app.baidu.services.ocpc import OcpcService, normalize_ocpc_bid
from app.baidu.writeback_approval import payload_fingerprint, claim_approval, WritebackApprovalError
from app.api.ocpc import OcpcBidRequest, update_ocpc_bid
from app.security.auth import AuthContext, _required


@pytest.mark.parametrize('value', [True, None, 'NaN', 'Infinity', '-1', '0', '10000', '1.001'])
def test_invalid_money(value):
    with pytest.raises(ValueError):
        normalize_ocpc_bid(value)


def test_boundaries_and_payload():
    assert normalize_ocpc_bid('9999.00') == 9999
    assert normalize_ocpc_bid('0.01') == .01
    client = SimpleNamespace(call=AsyncMock(return_value={'data': []}))
    asyncio.run(OcpcService(client).update_target_bid(23, 180))
    client.call.assert_awaited_once_with('OcpcService', 'updateTargetPackage',
        {'targetPackageType': [{'targetPackageId': 23, 'ocpcBid': 180.0}]}, is_write=True, write_scope="ocpc_bid")


def setup(monkeypatch, dry_run=True):
    settings = SimpleNamespace(baidu_write_dry_run=dry_run, baidu_ocpc_write_enabled=True, baidu_legacy_split_confirmation_enabled=False)
    monkeypatch.setattr(wb, 'get_settings', lambda: settings)
    account = SimpleNamespace(id=11, tenant_id=3, status='active')
    package = SimpleNamespace(tenant_id=3, baidu_account_id=11, package_id=23,
                             ocpc_bid_type=1, ocpc_bid=168, package_name='测试策略', raw={'scope': []})
    session = SimpleNamespace(scalar=AsyncMock(return_value=package), add=Mock(),
        flush=AsyncMock(), commit=AsyncMock(), refresh=AsyncMock())
    monkeypatch.setattr(wb, '_active_account', AsyncMock(return_value=account))
    monkeypatch.setattr(wb, '_ensure_no_unresolved_funds_writeback', AsyncMock())
    monkeypatch.setattr(wb, '_claim_funds_approval', AsyncMock(return_value=4))
    monkeypatch.setattr(wb, '_effective_dry_run', AsyncMock(return_value=False))
    client = Mock()
    monkeypatch.setattr(wb, '_account_client', client)
    service = SimpleNamespace(get_target_packages=AsyncMock(return_value=[{
        'targetPackageId': 23, 'ocpcBidType': 1, 'ocpcBid': 168}]),
        update_target_bid=AsyncMock(return_value={'data': [{'targetPackageId': 23, 'ocpcBid': 180}]}))
    monkeypatch.setattr(wb, 'OcpcService', Mock(return_value=service))
    monkeypatch.setattr(wb, 'AccountService', Mock(return_value=SimpleNamespace(
        get_account_info=AsyncMock(return_value={'data': {'userId': 999}}))))
    args = dict(tenant_id=3, package_id=23, baidu_account_id=11, old_bid=168, new_bid=180,
                execution_mode='dry_run' if dry_run else 'live', approval_id=4,
                operator_user_id=7, operator_name='test')
    return settings, package, session, client, service, args


def test_dry_run_never_builds_client_or_changes_snapshot(monkeypatch):
    settings, package, session, client, service, args = setup(monkeypatch)
    result = asyncio.run(wb.apply_ocpc_bid(session, **args))
    assert result.status == 'dry_run' and result.approval_id is None
    assert package.ocpc_bid == 168
    client.assert_not_called()
    wb._claim_funds_approval.assert_not_awaited()
    assert session.scalar.await_args.args[0]._for_update_arg is not None


def test_separate_switch_fails_closed(monkeypatch):
    settings, package, session, client, service, args = setup(monkeypatch, False)
    settings.baidu_ocpc_write_enabled = False
    with pytest.raises(wb.WritebackError, match='执行模式'):
        asyncio.run(wb.apply_ocpc_bid(session, **args))
    client.assert_not_called()


@pytest.mark.parametrize('field,value', [('ocpc_bid_type', 2), ('ocpc_bid', 150)])
def test_changed_local_strategy_blocks(monkeypatch, field, value):
    _, package, session, client, _, args = setup(monkeypatch)
    setattr(package, field, value)
    with pytest.raises(wb.WritebackError):
        asyncio.run(wb.apply_ocpc_bid(session, **args))
    client.assert_not_called()


def test_missing_or_other_account_strategy_blocks(monkeypatch):
    _, _, session, client, _, args = setup(monkeypatch)
    session.scalar.return_value = None
    with pytest.raises(wb.WritebackError, match='不属于'):
        asyncio.run(wb.apply_ocpc_bid(session, **args))
    query = str(session.scalar.await_args.args[0])
    assert 'ocpc_packages.tenant_id =' in query and 'ocpc_packages.baidu_account_id =' in query
    client.assert_not_called()


def test_live_success_commits_intent_before_network(monkeypatch):
    _, package, session, _, service, args = setup(monkeypatch, False)
    async def write(*_):
        assert session.commit.await_count == 1
        wb._claim_funds_approval.assert_awaited_once()
        return {'data': [{'targetPackageId': 23, 'ocpcBid': 180}]}
    service.update_target_bid.side_effect = write
    result = asyncio.run(wb.apply_ocpc_bid(session, **args))
    assert result.status == 'success' and result.approval_id == 4
    assert package.ocpc_bid == 180 and package.raw == {'scope': [], 'ocpcBid': 180}
    service.get_target_packages.assert_awaited_once_with(999)


@pytest.mark.parametrize('response', [None, {'data': []}, {'data': [{'targetPackageId': 24, 'ocpcBid': 180}]}, {'_dry_run': True}])
def test_uncertain_write_requires_reconciliation(monkeypatch, response):
    _, package, session, _, service, args = setup(monkeypatch, False)
    if response is None:
        service.update_target_bid.side_effect = TimeoutError('timeout')
    else:
        service.update_target_bid.return_value = response
    result = asyncio.run(wb.apply_ocpc_bid(session, **args))
    assert result.status == 'reconcile' and package.ocpc_bid == 168
    assert session.commit.await_count == 2


def test_remote_stale_bid_does_not_write(monkeypatch):
    _, package, session, _, service, args = setup(monkeypatch, False)
    service.get_target_packages.return_value[0]['ocpcBid'] = 169
    result = asyncio.run(wb.apply_ocpc_bid(session, **args))
    assert result.status == 'failed'
    service.update_target_bid.assert_not_awaited()


def test_missing_approval_stops_before_network(monkeypatch):
    _, _, session, client, _, args = setup(monkeypatch, False)
    wb._claim_funds_approval.side_effect = wb.WritebackError('需要审批')
    with pytest.raises(wb.WritebackError, match='需要审批'):
        asyncio.run(wb.apply_ocpc_bid(session, **args))
    client.assert_not_called()


def test_approval_binds_account_old_price_and_new_price():
    payload = {'package_id': 23, 'baidu_account_id': 11, 'old_bid': 168, 'new_bid': 180}
    _, fingerprint = payload_fingerprint('ocpc_bid', payload)
    for key in payload:
        assert payload_fingerprint('ocpc_bid', {**payload, key: payload[key] + 1})[1] != fingerprint


def test_route_requires_edit_permission_and_tenant():
    assert _required('/api/v1/ocpc/packages/23/bid', 'POST') == ({'manage.ocpc'}, True)
    req = OcpcBidRequest(tenant_id=3, baidu_account_id=11, old_bid=168, new_bid=180, execution_mode='dry_run')
    ctx = AuthContext(7, 'reader', 'reader', 3, {'manage.ocpc': 'view'})
    with pytest.raises(Exception) as error:
        asyncio.run(update_ocpc_bid(23, req, ctx=ctx, session=None))
    assert error.value.status_code == 403
    ctx = AuthContext(7, 'editor', 'editor', 4, {'manage.ocpc': 'edit'})
    with pytest.raises(Exception) as error:
        asyncio.run(update_ocpc_bid(23, req, ctx=ctx, session=None))
    assert error.value.status_code == 403


def test_unresolved_intent_blocks_another_attempt(monkeypatch):
    _, _, session, client, _, args = setup(monkeypatch, False)
    wb._ensure_no_unresolved_funds_writeback.side_effect = wb.WritebackError('请先完成对账')
    with pytest.raises(wb.WritebackError, match='对账'):
        asyncio.run(wb.apply_ocpc_bid(session, **args))
    client.assert_not_called()
    wb._claim_funds_approval.assert_not_awaited()


@pytest.mark.parametrize('changes', [{'new_bid': 168}, {'new_bid': 300}, {'operator_user_id': None}])
def test_noop_large_jump_and_api_key_blocked(monkeypatch, changes):
    _, _, session, client, _, args = setup(monkeypatch)
    with pytest.raises(wb.WritebackError):
        asyncio.run(wb.apply_ocpc_bid(session, **{**args, **changes}))
    client.assert_not_called()


def test_ocpc_approval_can_only_be_consumed_once(monkeypatch):
    from app.baidu import writeback_approval
    from app.baidu.writeback_approval import shanghai_now_naive
    monkeypatch.setattr(writeback_approval, "get_settings", lambda: SimpleNamespace(
        baidu_legacy_split_confirmation_enabled=False, baidu_write_confirmation_ttl_minutes=15))
    payload = {'package_id': 23, 'baidu_account_id': 11, 'old_bid': 168, 'new_bid': 180}
    normalized, fingerprint = payload_fingerprint('ocpc_bid', payload)
    row = SimpleNamespace(tenant_id=3, status='approved', action_type='ocpc_bid',
        payload=normalized, payload_hash=fingerprint, approved_by=7, requested_by=7, created_at=shanghai_now_naive())
    session = SimpleNamespace(scalar=AsyncMock(return_value=row), flush=AsyncMock())
    args = dict(approval_id=4, tenant_id=3, action_type='ocpc_bid', payload=payload, operator_user_id=7)
    asyncio.run(claim_approval(session, **args))
    assert row.status == 'consumed'
    with pytest.raises(WritebackApprovalError):
        asyncio.run(claim_approval(session, **args))


def test_missing_account_scope_rejects_live_request(monkeypatch):
    _, _, session, client, _, args = setup(monkeypatch, False)
    wb._effective_dry_run.return_value = True
    with pytest.raises(wb.WritebackError, match='执行模式'):
        asyncio.run(wb.apply_ocpc_bid(session, **args))
    client.assert_not_called()
    wb._claim_funds_approval.assert_not_awaited()


def test_revoked_policy_after_intent_prevents_network(monkeypatch):
    _, _, session, client, service, args = setup(monkeypatch, False)
    wb._effective_dry_run.side_effect = [False, True]
    result = asyncio.run(wb.apply_ocpc_bid(session, **args))
    assert result.status == 'failed'
    client.assert_not_called()
    service.update_target_bid.assert_not_awaited()


def test_listing_mode_fails_closed_without_grant(monkeypatch):
    settings, _, session, client, _, _ = setup(monkeypatch, False)
    session.scalar.return_value = None
    assert asyncio.run(wb.ocpc_execution_mode(session, 3, 11)) == 'dry_run'
    client.assert_not_called()
