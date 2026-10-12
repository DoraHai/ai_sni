"""Stateless one-time device pairing. Caller owns atomic commit; no secret replay."""
import hashlib
import os
import secrets
from types import SimpleNamespace
from uuid import uuid4

from fastapi import HTTPException
from app import distribution_control as core
from app.distribution_pairing_contract import PairingView, DeviceBindingView


def enabled():
    return os.environ.get('DISTRIBUTION_DEVICE_PAIRING_ENABLED') == 'true'


def problem(code, status=409):
    return HTTPException(status, {'code': code}, headers={'Cache-Control': 'no-store'})


def require_enabled():
    if not enabled():
        raise problem('PAIRING_DISABLED', 503)


def view(row):
    state = row['state']
    if state == 'pending' and row['expires_at'] <= core.now_ms():
        state = 'expired'
    value = {key: row[key] for key in ('id', 'request_id', 'device_id', 'label',
        'created_at', 'expires_at', 'claimed_at', 'revoked_at')}
    return PairingView.model_validate({**value, 'state': state}).model_dump(mode='json')


async def row_by_id(db, ident):
    row = await core.one(db, 'SELECT p.*,d.label FROM distribution_device_pairings p '
        'JOIN distribution_devices d ON d.id=p.device_id WHERE p.id=:id', id=ident)
    if not row:
        raise problem('PAIRING_NOT_FOUND', 404)
    return row


async def create(db, actor, request):
    await core.lock(db, 'pairing-create:' + str(actor))
    prior = await core.one(db, 'SELECT id FROM distribution_device_pairings '
        'WHERE created_by=:actor AND request_id=:request', actor=actor, request=request.request_id)
    if prior:
        raise problem('PAIRING_CREATE_ALREADY_EXISTS')
    count = await db.scalar(core.text("SELECT count(*) FROM distribution_device_pairings "
        "WHERE created_by=:actor AND state='pending' AND expires_at>:at"), {'actor': actor, 'at': core.now_ms()})
    if count >= 10:
        raise problem('PAIRING_CAPACITY', 409)
    ident, device_id = uuid4(), str(uuid4())
    code = secrets.token_urlsafe(24)
    now = core.now_ms()
    await db.execute(core.text('INSERT INTO distribution_devices '
        '(id,label,credential_hash,active,created_by,created_at) VALUES(:id,:label,:hash,false,:actor,:at)'),
        {'id': device_id, 'label': request.label, 'hash': hashlib.sha256(secrets.token_bytes(48)).hexdigest(),
         'actor': actor, 'at': now})
    await db.execute(core.text('INSERT INTO distribution_device_pairings '
        '(id,device_id,created_by,request_id,fingerprint,code_hash,state,created_at,expires_at) '
        "VALUES(:id,:device,:actor,:request,:fp,:hash,'pending',:at,:expiry)"),
        {'id': ident, 'device': device_id, 'actor': actor, 'request': request.request_id,
         'fp': hashlib.sha256(core.canonical(request.model_dump(mode='json')).encode()).hexdigest(),
         'hash': hashlib.sha256(code.encode()).hexdigest(), 'at': now, 'expiry': now + request.expires_in_seconds * 1000})
    await core.audit(db, actor, 'pairing_created', {'pairing_id': str(ident), 'device_id': device_id}, 'PENDING')
    return {'schema': 1, 'pairing': view(await row_by_id(db, ident)), 'pairing_code': code, 'code_once': True}


async def claim(db, request):
    digest = hashlib.sha256(request.pairing_code.encode()).hexdigest()
    peek = await core.one(db, 'SELECT device_id FROM distribution_device_pairings WHERE code_hash=:hash', hash=digest)
    if not peek:
        raise problem('PAIRING_CODE_UNAVAILABLE')
    # Same device -> pairing order as the existing admin revoke path.
    await core.lock(db, 'device:' + peek['device_id'])
    row = await core.one(db, 'SELECT p.*,d.label,d.active FROM distribution_device_pairings p '
        'JOIN distribution_devices d ON d.id=p.device_id WHERE p.code_hash=:hash FOR UPDATE OF p,d', hash=digest)
    if not row or row['state'] != 'pending' or row['active'] or row['expires_at'] <= core.now_ms():
        raise problem('PAIRING_CODE_UNAVAILABLE')
    from app.api.distribution import named
    # Code authority comes from the real issuing admin; re-read its current DB role.
    try:
        await named(db, SimpleNamespace(user_id=row['created_by']), admin=True)
    except HTTPException as exc:
        if exc.status_code >= 500:
            raise
        raise problem('PAIRING_CODE_UNAVAILABLE') from None
    if row['expires_at'] <= core.now_ms():
        raise problem('PAIRING_CODE_UNAVAILABLE')
    credential = secrets.token_urlsafe(48)
    now = core.now_ms()
    await db.execute(core.text('UPDATE distribution_devices SET credential_hash=:hash,active=true WHERE id=:id'),
        {'id': row['device_id'], 'hash': hashlib.sha256(credential.encode()).hexdigest()})
    await db.execute(core.text("UPDATE distribution_device_pairings SET state='claimed',claimed_at=:at,claim_request_id=:request WHERE id=:id"),
        {'id': row['id'], 'at': now, 'request': request.request_id})
    await core.audit(db, 'device:' + row['device_id'], 'pairing_claimed',
        {'pairing_id': str(row['id']), 'device_id': row['device_id'], 'request_id': str(request.request_id)}, 'CLAIMED')
    return {'schema': 1, 'pairing_id': str(row['id']), 'claimed_at': now,
        'device': {'id': row['device_id'], 'label': row['label'], 'active': True,
                   'credential': credential, 'credential_once': True},
        'bindings_configured': False, 'automatic_submit': False}


async def revoke_for_device(db, device_id, actor):
    """Called while the existing device revoke holds its device advisory lock."""
    installed = await db.scalar(core.text("SELECT to_regclass(current_schema()||'.distribution_device_pairings') IS NOT NULL"))
    if not installed:
        return
    rows = await core.rows(db, 'SELECT * FROM distribution_device_pairings WHERE device_id=:device FOR UPDATE', device=device_id)
    if not rows:
        return
    now = core.now_ms()
    for row in rows:
        if row['state'] != 'revoked':
            await db.execute(core.text("UPDATE distribution_device_pairings SET state='revoked',revoked_at=:at,revoked_by=:actor WHERE id=:id"),
                {'id': row['id'], 'at': now, 'actor': actor})
            await core.audit(db, actor, 'pairing_revoked', {'pairing_id': str(row['id']), 'device_id': device_id}, 'REVOKED')
    for table in ('distribution_device_capability_registrations', 'distribution_capability_attestations', 'distribution_remote_sessions'):
        if not await db.scalar(core.text('SELECT to_regclass(current_schema()||:table) IS NOT NULL'), {'table': '.' + table}):
            continue
        if table == 'distribution_device_capability_registrations':
            await db.execute(core.text('UPDATE distribution_device_capability_registrations SET active=false,revision=revision+1,expires_at=:at,updated_at=:at WHERE device_id=:device AND active'), {'device': device_id, 'at': now})
        elif table == 'distribution_capability_attestations':
            await db.execute(core.text('UPDATE distribution_capability_attestations SET expires_at=:at WHERE device_id=:device AND expires_at>:at'), {'device': device_id, 'at': now})
        else:
            from app.distribution_remote import broker
            sessions = await core.rows(db, "SELECT * FROM distribution_remote_sessions WHERE device_id=:device AND state IN ('requested','active') FOR UPDATE", device=device_id)
            for remote in sessions:
                await broker.close_row(db, dict(remote), 'AUTHORIZATION_REVOKED')


async def device_bindings(db, credential, device_id):
    from app import distribution_execution_capabilities as capabilities
    await capabilities.authenticate(db, credential, device_id)
    bindings = await core.rows(db, "SELECT * FROM distribution_bindings WHERE device_id=:device AND active "
        "AND platform='wechat-article' ORDER BY id LIMIT 50", device=device_id)
    result = []
    for binding in bindings:
        scope = {key: binding[key] for key in ('module', 'tenant_id', 'scope_id')}
        if binding['module'] == 'seo':
            assigned = await core.one(db, 'SELECT advisor_user_id FROM seo_site_advisor_assignments '
                'WHERE tenant_id=:tenant_id AND site_id=:scope_id AND active ORDER BY id DESC LIMIT 1', **scope)
            actor = assigned['advisor_user_id'] if assigned else None
        elif binding['module'] == 'geo':
            project = await core.one(db, 'SELECT project_settings FROM geo_projects WHERE tenant_id=:tenant_id AND id=:scope_id', **scope)
            module = core.adapter('geo')
            settings = project['project_settings'] if project else None
            plan = module.plan_for(SimpleNamespace(project_settings=settings)) if isinstance(settings, dict) else {}
            actor = plan.get('advisor_user_id') if isinstance(plan, dict) else None
        else:
            continue
        if type(actor) is not int or actor <= 0:
            continue
        try:
            await core.authorize_scope(db, actor, scope)
        except HTTPException as exc:
            if exc.status_code in (403, 404, 409):
                continue
            raise
        value = {key: binding[key] for key in ('device_id', 'module', 'tenant_id', 'scope_id',
            'account_id', 'external_account_id', 'platform')}
        result.append(DeviceBindingView.model_validate({**value, 'binding_id': binding['id']}).model_dump(mode='json'))
    return {'schema': 1, 'device_id': device_id, 'as_of': core.now_ms(), 'items': result, 'automatic_submit': False}
