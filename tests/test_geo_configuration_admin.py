import asyncio
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.geo.content import routes
from app.geo.content.schemas import TrackingEnginesPut, VisibilityPatrolSettingsUpdate
from app.security.auth import AuthContext
from test_advisor_scoped_writes import backend, fixture_token, write_sandbox


@pytest.mark.parametrize('path,body', [
    ('/tracking-engines', {'tenant_id': 10, 'items': [{'engine_key': 'deepseek', 'display_name': 'fixture engine'}]}),
    ('/visibility-patrol/settings', {'tenant_id': 10, 'enabled': True}),
])
def test_non_advisor_customer_admin_cannot_change_platform_settings(tmp_path, monkeypatch, backend, path, body):
    async def run():
        async with write_sandbox(tmp_path, monkeypatch, backend=backend) as env:
            before = await env.snapshot()
            # Role 3 has settings.customers edit, so it is deliberately outside
            # advisor classification; it must still fail this separate gate.
            response = await env.request('PUT', path, body=body, auth=fixture_token(uid=3, native=True))
            assert response.status_code == 403, response.text
            assert '只有平台管理员' in response.json()['detail']
            assert await env.snapshot() == before
    asyncio.run(run())


@pytest.mark.parametrize('handler,payload', [
    (routes.put_tracking_engines, TrackingEnginesPut(tenant_id=10,
        items=[{'engine_key': 'deepseek', 'display_name': 'fixture engine'}])),
    (routes.put_visibility_patrol_settings, VisibilityPatrolSettingsUpdate(tenant_id=10)),
])
def test_global_account_admin_passes_gate_before_existing_business_checks(monkeypatch, handler, payload):
    class ReachedExistingChecks(Exception):
        pass
    boundary = AsyncMock(side_effect=ReachedExistingChecks)
    monkeypatch.setattr(routes, '_ensure_tenant_exists', boundary)
    ctx = AuthContext(99, 'fixture-admin', 'admin', None,
        {'settings.accounts': 'edit', 'geo.content': 'edit'})
    with pytest.raises(ReachedExistingChecks):
        asyncio.run(handler(payload, ctx, object()))
    boundary.assert_awaited_once()
