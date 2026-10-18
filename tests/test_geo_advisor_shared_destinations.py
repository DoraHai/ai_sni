"""Synthetic authorization checks; no database or supplier connections."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.security import advisor_operations as operations
from app.security.advisor_write_routes import match_write_rule


@pytest.mark.parametrize('path', (
    '/publishing-channels/enable-multi-media-auto', '/oauth/social/refresh',
    '/channel-accounts/{account_id}/verify-social', '/oauth/social/start'))
def test_credential_and_auto_mode_actions_are_not_advisor_grants(path):
    request = SimpleNamespace(method='POST', scope={'route': SimpleNamespace(path=operations.PREFIX + path)})
    assert match_write_rule(request) is None


@pytest.mark.parametrize('path,body', (
    ('/publishing-channels', {'publish_mode': 'auto_publish'}),
    ('/publishing-channels/{channel_id}', {'publish_mode': 'draft_api'}),
    ('/channel-polish-prompts', {'add_channel_key': 'website'}),
    ('/channel-polish-prompts', {'remove_channel_key': 'website'})))
def test_indirect_global_auto_configuration_is_rejected(path, body):
    method = 'PUT' if 'polish' in path else 'PATCH' if '{' in path else 'POST'
    rule = operations.rules()[(method, operations.PREFIX + path)]
    with pytest.raises(HTTPException) as error:
        operations.check_fields(rule, body)
    assert error.value.status_code == 403


@pytest.mark.parametrize('path,method,body', (
    ('/publishing-channels', 'POST', {}),
    ('/publishing-channels/{channel_id}', 'DELETE', {}),
    ('/channel-accounts', 'POST', {}),
    ('/channel-accounts/{account_id}', 'PATCH', {}),
    ('/channel-accounts/{account_id}', 'DELETE', {}),
    ('/channel-polish-prompts', 'PUT', {}),
    ('/onboarding/apply', 'POST', {'create_website_channel': True})))
def test_shared_writes_cannot_affect_an_unassigned_project(path, method, body):
    session = SimpleNamespace(scalars=AsyncMock(return_value=[10, 50]), scalar=AsyncMock())
    ctx = SimpleNamespace(tenant_id=10)
    request = SimpleNamespace(path_params={})
    rule = operations.rules()[(method, operations.PREFIX + path)]
    with pytest.raises(HTTPException) as error:
        asyncio.run(operations.guard_shared_destinations(session, ctx, request, body, rule, {10}))
    assert error.value.status_code == 403
    session.scalar.assert_not_awaited()


@pytest.mark.parametrize('path,method', (
    ('/publishing-channels', 'POST'), ('/channel-accounts', 'POST'),
    ('/channel-polish-prompts', 'PUT')))
def test_shared_operational_edits_remain_available_when_all_projects_are_owned(path, method):
    session = SimpleNamespace(scalars=AsyncMock(return_value=[10, 11]))
    rule = operations.rules()[(method, operations.PREFIX + path)]
    asyncio.run(operations.guard_shared_destinations(session, SimpleNamespace(tenant_id=10),
        SimpleNamespace(path_params={}), {}, rule, {10, 11}))


@pytest.mark.parametrize('auth_type,credentials,allowed', (
    ('manual', None, True), ('manual', 'fixture-only', False), ('oauth2', None, False)))
def test_only_uncredentialed_manual_accounts_can_be_maintained(auth_type, credentials, allowed):
    account = SimpleNamespace(auth_type=auth_type, credentials_encrypted=credentials)
    session = SimpleNamespace(scalars=AsyncMock(return_value=[10]), scalar=AsyncMock(return_value=account))
    rule = operations.rules()[('DELETE', operations.PREFIX + '/channel-accounts/{account_id}')]
    async def run():
        await operations.guard_shared_destinations(session, SimpleNamespace(tenant_id=10),
            SimpleNamespace(path_params={'account_id': '100'}), {}, rule, {10})
    if allowed:
        asyncio.run(run())
    else:
        with pytest.raises(HTTPException) as error:
            asyncio.run(run())
        assert error.value.status_code == 403


@pytest.mark.parametrize('mode,credentialed', (
    ('auto_publish', False), ('manual_only', True)))
def test_channel_deletion_cannot_cascade_into_credentialed_accounts(mode, credentialed):
    account = SimpleNamespace(auth_type='oauth2' if credentialed else 'manual', credentials_encrypted=None)
    session = SimpleNamespace(scalars=AsyncMock(side_effect=[[10], [account]]),
        scalar=AsyncMock(return_value=SimpleNamespace(publish_mode=mode)))
    rule = operations.rules()[('DELETE', operations.PREFIX + '/publishing-channels/{channel_id}')]
    with pytest.raises(HTTPException) as error:
        asyncio.run(operations.guard_shared_destinations(session, SimpleNamespace(tenant_id=10),
            SimpleNamespace(path_params={'channel_id': '100'}), {}, rule, {10}))
    assert error.value.status_code == 403


@pytest.mark.parametrize('name,kwargs', (
    ('enable_multi_media_auto_pack', {}), ('oauth_social_start', {'account_id': 100}),
    ('oauth_social_refresh', {'account_id': 100}), ('verify_social_account', {'account_id': 100})))
def test_config_handlers_reject_customer_roles_before_any_supplier_or_database(name, kwargs):
    from app.geo.content import routes
    ctx = SimpleNamespace(tenant_id=10, can_edit=lambda *_: True)
    with pytest.raises(HTTPException) as error:
        asyncio.run(getattr(routes, name)(tenant_id=10, ctx=ctx, session=object(), **kwargs))
    assert error.value.status_code == 403
