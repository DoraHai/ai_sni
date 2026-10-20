"""Actual synthetic personnel JWT + local SQL admission. No new inbox tables."""
import asyncio
from datetime import datetime, timedelta, timezone

import httpx
import jwt
import pytest
from fastapi import Depends, FastAPI
from sqlalchemy import delete

from app.database import get_session
from app.distribution_inbox_protocol import PREFIX
from app.models.advisor_tenant_grant import AdvisorTenantGrant as Grant
from app.models.role import Role
from app.models.user import User
from app.security import auth
from app.security.distribution_inbox_auth import require_inbox_identity
from test_advisor_tenant_auth import local_db  # real isolated SQLite fixture
from test_distribution_inbox_protocol import ID, IDENTITY_ROUTES


def bearer(sub, **changes):
    return 'Bearer ' + jwt.encode({'sub': str(sub), 'exp': int((datetime.now(timezone.utc)+timedelta(hours=1)).timestamp()),
                                  **changes}, auth._jwt_secret(), algorithm=auth.JWT_ALG)


def identity(sub=1):
    return bearer(sub, aud='advisor-session', scope_kind='advisor_identity')


async def call(local_db, credential, *, method='GET', suffix='/receipts', headers=None):
    app = FastAPI()
    async def admitted(ctx=Depends(require_inbox_identity)):
        return {'user': ctx.user_id}
    for verb, path in IDENTITY_ROUTES:
        app.add_api_route(PREFIX+path, admitted, methods=[verb])
    async def local_session():
        yield local_db[1]
    app.dependency_overrides[get_session] = local_session
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://synthetic.invalid') as client:
        return await client.request(method, PREFIX+suffix, headers=headers or {'Authorization': credential})


@pytest.mark.parametrize('method,suffix', IDENTITY_ROUTES)
def test_zero_grant_geo_only_advisor_can_use_exact_identity_paths(local_db, method, suffix):
    db, _ = local_db
    db.execute(delete(Grant))
    role = db.get(Role, 1)
    role.permissions = {'geo.assets': 'edit', 'geo.content': 'edit'}
    db.get(User, 1).tenant_id = None
    db.commit()
    response = asyncio.run(call(local_db, identity(), method=method, suffix=suffix))
    assert response.status_code == 200
    assert response.json() == {'user': 1}
    assert auth._required(PREFIX+suffix, method) == (None, method == 'POST')


def test_system_admin_personnel_jwt_and_client_rejected(local_db):
    assert asyncio.run(call(local_db, bearer(3))).status_code == 200
    assert asyncio.run(call(local_db, bearer(2))).status_code == 403
    # An ordinary settings editor is not a personnel system administrator.
    db, _ = local_db
    role = db.get(Role, 2)
    role.permissions = {'settings.accounts': 'edit', 'seo.content': 'edit'}
    db.commit()
    assert asyncio.run(call(local_db, bearer(2))).status_code == 403


def test_api_key_device_and_missing_login_do_not_get_an_owner(local_db):
    response = asyncio.run(call(local_db, '', headers={'X-API-Key': auth.get_settings().admin_api_key}))
    assert response.status_code == 403
    assert asyncio.run(call(local_db, 'Bearer dht2_'+ID+'.'+'a'*43)).status_code == 401
    assert asyncio.run(call(local_db, '')).status_code == 401


@pytest.mark.parametrize('change', ['inactive', 'locked', 'role_changed'])
def test_current_account_and_role_are_rechecked(local_db, change):
    assert asyncio.run(call(local_db, identity())).status_code == 200
    db, _ = local_db
    user = db.get(User, 1)
    if change == 'inactive': user.is_active = False
    elif change == 'locked': user.locked_until = datetime.now()+timedelta(hours=1)
    else: user.role_id = 2
    db.commit()
    assert asyncio.run(call(local_db, identity())).status_code in {401, 403}


def test_business_jwt_never_falls_back_to_identity(local_db):
    credential = bearer(1, aud='advisor-business', scope_kind='advisor_tenant', tid=1, gid=10,
                        auth_exp=int((datetime.now(timezone.utc)+timedelta(hours=1)).timestamp()))
    assert asyncio.run(call(local_db, credential)).status_code == 403


def test_only_exact_routes_get_menu_bypass():
    for suffix in ['/device/results', '/device/ack', '/device-pairings/claim']:
        from app.distribution_inbox_protocol import match_inbox_identity_route
        assert not match_inbox_identity_route('POST', PREFIX+suffix)
    assert auth._required(f'/api/v1/seo/distribution/v2/receipts/{ID}/label', 'POST') == ({'seo.content'}, True)
    assert auth._required(f'/api/v1/seo/distribution/v2/receipts/{ID}/unlabel', 'POST') == ({'seo.content'}, True)
    assert auth._required(f'/api/v1/geo/distribution/v2/receipts/{ID}/label', 'POST') == ({'geo.content'}, True)
    assert auth._required(f'/api/v1/geo/distribution/v2/receipts/{ID}/unlabel', 'POST') == ({'geo.content'}, True)
    assert auth._required('/api/v1/geo/distribution/v2/publications', 'GET') == ({'geo.content'}, False)
    assert auth._required('/api/v1/seo/distribution/v1/settings', 'PUT') == ({'seo.content'}, True)


@pytest.mark.parametrize('suffix', ['/receipts?tenant_id=1', '/receipts?project_id=2',
    '/receipts?ownerUserId=1', '/receipts?state=pending&state=active',
    '/receipts/'+ID.replace('1', '%31', 1), '/devices?ownerUserId=1'])
def test_real_http_extra_selectors_duplicate_queries_and_encoded_aliases_are_rejected(local_db, suffix):
    assert asyncio.run(call(local_db, identity(), suffix=suffix)).status_code == 403


def test_only_personnel_admin_can_explicitly_filter_owner(local_db):
    assert asyncio.run(call(local_db, bearer(3), suffix='/receipts?ownerUserId=1')).status_code == 200
    assert asyncio.run(call(local_db, identity(), suffix='/receipts?q=synthetic&limit=50&offset=0')).status_code == 200
