"""Tenant-row serialized, bounded GEO manual-result registry and receiver.

The module row and native publication are committed by the caller together.
Only hashes of one-time pairing/device values are persisted. No platform IO.
"""
import hashlib
import hmac
import re
import secrets
import time
import unicodedata
from dataclasses import dataclass
from datetime import timezone
from types import SimpleNamespace
from uuid import UUID, uuid4

from sqlalchemy import select, cast, func
from sqlalchemy.dialects.postgresql import JSONB, JSONPATH
from sqlalchemy.orm import load_only
from fastapi import HTTPException

from app.models import (Tenant, TenantModule, GeoProject, GeoContentTask, GeoChannelVariant,
                        GeoArticleVersion, GeoChannelAccount, GeoPublishingChannel, GeoPublication,
                        GeoPrompt, GeoOptimizationUnit, GeoOptimizationBusiness, User, Role)
from app.geo.content import distribution_protocol as p
from app.geo.project_scope import project_scope, prompt_ids_for_businesses
from app.geo.tenant_scope import ensure_geo_entitlement
from app.security.advisor_scope import account_locked, is_advisor

MAX_ACTIVE_DEVICES = 20
MAX_UNUSED_PAIRINGS = 20
PAIRING_FAILURE_LIMIT = 6
PAIRING_FAILURE_WINDOW_MS = 60_000


class PairingRejected(HTTPException):
    """Known-code failure ledger was flushed; the claim route must commit it."""


def display_name(value):
    if not isinstance(value, str):
        return ''
    return ' '.join(''.join(c for c in value if not unicodedata.category(c).startswith('C')).split())[:120]


def now_ms():
    return int(time.time() * 1000)


def sha(value):
    return hashlib.sha256(value.encode()).hexdigest()


def uuid():
    return str(uuid4())


async def hash_locator(session, collection, field, value):
    # Match the security field, never a substring in an operator-supplied label.
    path = f'$.{p.KEY}.{collection}.* ? (@.{field} == $h)'
    return await session.scalar(select(TenantModule.tenant_id).where(
        TenantModule.module_code == 'geo', func.jsonb_path_exists(TenantModule.module_settings,
            cast(path, JSONPATH), cast({'h': value}, JSONB))).limit(1))


@dataclass
class Store:
    session: object
    tenant_id: int
    row: object
    book: dict

    def audit(self, code, *, actor=None, device=None, task=None, **details):
        self.book['audit'].append({'code': code, 'at': now_ms(), 'actor_id': actor,
                                   'device_id': device, 'task_id': task, **details})

    async def save(self):
        if len(p.encode(self.book)) > p.MAX_BYTES:
            p.fail('REPORT_LEDGER_CAPACITY', 429)
        self.row.module_settings = {**(self.row.module_settings or {}), p.KEY: self.book}
        await self.session.flush()


async def open_store(session, tenant_id):
    # Same outer tenant lock as entitlement, project binding and manual writes.
    await session.scalar(select(Tenant.id).where(Tenant.id == tenant_id).with_for_update())
    await ensure_geo_entitlement(session, tenant_id)
    row = await session.scalar(select(TenantModule).where(
        TenantModule.tenant_id == tenant_id, TenantModule.module_code == 'geo')
        .with_for_update().execution_options(populate_existing=True))
    if row is None:
        p.fail('REPORT_SCHEMA_UNAVAILABLE', 503)
    return Store(session, tenant_id, row, p.registry(row.module_settings))


async def selected_project(store, project_id):
    project, businesses = await project_scope(store.session, store.tenant_id, project_id)
    # Project metadata/status updates need not acquire the tenant lock. Retain
    # the project row lock too, so pause/archive cannot commit between our
    # current-scope check and the publication/registry transaction.
    await store.session.refresh(project, with_for_update=True)
    if project.status != 'active' or project.tenant_module_id != store.row.id:
        p.fail('SCOPE_FORBIDDEN', 403)
    return project, businesses


async def actor_authorized(store, project_id, actor, *, write=True):
    """Fresh database authority, also used on device requests without human JWT.

    Never constructs an all-powerful AuthContext or reads password fields.
    Locks remain held through the native write and commit.
    """
    from app.models.advisor_tenant_grant import AdvisorTenantGrant as Grant
    from app.security.advisor_scope import AdvisorScope
    from app.geo.project_workflows import plan_for, advisor_available
    from app.security.geo_advisor import check_manual_execution_scope
    from app.config import get_settings

    session = store.session
    user = await session.scalar(select(User).options(load_only(
        User.id, User.role_id, User.tenant_id, User.is_active, User.locked_until))
        .where(User.id == actor['user_id']).with_for_update().execution_options(populate_existing=True))
    if user is None or not user.is_active or account_locked(user):
        p.fail('ACTOR_AUTHORIZATION_REVOKED', 403)
    role = await session.scalar(select(Role).where(Role.id == user.role_id)
        .with_for_update().execution_options(populate_existing=True))
    if role is None:
        p.fail('ACTOR_AUTHORIZATION_REVOKED', 403)
    project, businesses = await selected_project(store, project_id)
    admin = bool((role.is_system and role.name == '管理员')
                 or (role.permissions or {}).get('settings.accounts') == 'edit')
    if actor['kind'] == 'admin':
        if not admin or user.tenant_id not in {None, store.tenant_id}:
            p.fail('ACTOR_AUTHORIZATION_REVOKED', 403)
        return project, businesses
    if (actor['kind'] != 'advisor' or not is_advisor(role)
            or (write and not get_settings().advisor_scoped_content_writes_enabled)
            or any((role.permissions or {}).get(k) != 'edit' for k in ('geo.assets', 'geo.content'))):
        p.fail('ACTOR_AUTHORIZATION_REVOKED', 403)
    grant = await session.scalar(select(Grant).where(Grant.id == actor['grant_id'])
        .with_for_update().execution_options(populate_existing=True))
    all_ids = set(await session.scalars(select(Grant.tenant_id).where(
        Grant.user_id == user.id, Grant.revoked_at.is_(None))))
    if (grant is None or grant.user_id != user.id or grant.tenant_id != store.tenant_id
            or grant.revoked_at is not None or user.tenant_id not in all_ids):
        p.fail('ACTOR_AUTHORIZATION_REVOKED', 403)
    scope = AdvisorScope(frozenset(all_ids), store.tenant_id, grant.id)
    from app.security.advisor_write_reads import assigned_scope
    assigned_projects, assigned_businesses = await assigned_scope(session,
        SimpleNamespace(tenant_id=store.tenant_id, user_id=user.id))
    if project_id not in assigned_projects or not set(businesses).issubset(assigned_businesses):
        p.fail('ACTOR_AUTHORIZATION_REVOKED', 403)
    plan = plan_for(project)
    if (type(plan.get('advisor_user_id')) is not int or plan['advisor_user_id'] != user.id
            or not await advisor_available(session, store.tenant_id, user.id, advisor_scope=scope)):
        p.fail('ACTOR_AUTHORIZATION_REVOKED', 403)
    # Reuse the current content execution-chain serialization/authority rule;
    # a new route prefix must not silently skip or change that guard.
    if write:
        await check_manual_execution_scope(session, SimpleNamespace(tenant_id=store.tenant_id),
            SimpleNamespace(template='/api/v1/geo/content-tasks'))
    return project, businesses


def actor_from_context(ctx):
    if not ctx.user_id or ctx.is_superadmin:
        p.fail('HUMAN_LOGIN_REQUIRED', 403)
    if ctx.advisor_scope is not None:
        return {'kind': 'advisor', 'user_id': ctx.user_id, 'grant_id': ctx.advisor_scope.grant_id}
    if ctx.can_edit('settings.accounts'):
        return {'kind': 'admin', 'user_id': ctx.user_id, 'grant_id': None}
    p.fail('SCOPE_FORBIDDEN', 403)


async def management_store(session, ctx, tenant_id, project_id, *, write=False):
    ctx.ensure_tenant(tenant_id)
    store = await open_store(session, tenant_id)
    await selected_project(store, project_id)
    if write:
        await actor_authorized(store, project_id, actor_from_context(ctx))
    elif not (ctx.can_view('geo.content') or ctx.can_edit('settings.accounts')):
        p.fail('SCOPE_FORBIDDEN', 403)
    elif ctx.advisor_scope is not None:
        await actor_authorized(store, project_id, actor_from_context(ctx), write=False)
    return store


def settings_payload(store, project_id):
    book = store.book
    scope = book['scopes'].get(str(project_id)) or {'enabled': False, 'revision': 0}
    return {'schema': 1, 'enabled': book['enabled'] is True, 'revision': book['revision'],
            'scope_enabled': scope.get('enabled') is True, 'scope_revision': scope.get('revision', 0),
            'human_confirmation_required': True,
            'devices': [{'id': d['id'], 'label': d['label'], 'account_id': d['account_id'],
                         'platform': 'wechat-article', 'revoked': d['revoked'], 'expires_at': d['expires_at']}
                        for d in book['devices'].values() if d['scope_id'] == project_id]}


async def change_settings(store, project_id, actor, body):
    p.exact(body, {'enabled', 'scope_enabled', 'expected_revision', 'expected_scope_revision'})
    for k in ('enabled', 'scope_enabled'):
        if type(body[k]) is not bool:
            p.fail('INVALID_SHAPE', 422)
    p.integer(body['expected_revision'], 0); p.integer(body['expected_scope_revision'], 0)
    scope = store.book['scopes'].get(str(project_id)) or {'enabled': False, 'revision': 0}
    if body['expected_revision'] != store.book['revision'] or body['expected_scope_revision'] != scope['revision']:
        p.fail('SOURCE_CHANGED')
    # Re-arming a previously disabled tenant must not implicitly reactivate
    # another project's saved switch. Close those scopes explicitly first.
    if (body['enabled'] and not store.book['enabled'] and any(
            key != str(project_id) and value.get('enabled') is True
            for key, value in store.book['scopes'].items())):
        p.fail('SOURCE_CHANGED')
    store.book['enabled'] = body['enabled']
    store.book['revision'] += 1
    store.book['scopes'][str(project_id)] = {'enabled': body['scope_enabled'], 'revision': scope['revision'] + 1}
    store.audit('SETTINGS_UPDATED', actor=actor['user_id'])
    await store.save()
    return settings_payload(store, project_id)


async def account_binding(store, account_id):
    # Project authorization and exact task grants further narrow this existing
    # tenant-owned account. Never load encrypted platform credentials.
    session = store.session
    account = await session.scalar(select(GeoChannelAccount).options(load_only(
        GeoChannelAccount.id, GeoChannelAccount.tenant_id, GeoChannelAccount.channel_id,
        GeoChannelAccount.auth_type, GeoChannelAccount.status, GeoChannelAccount.expires_at))
        .where(GeoChannelAccount.id == account_id, GeoChannelAccount.tenant_id == store.tenant_id)
        .with_for_update().execution_options(populate_existing=True))
    if account is None or account.status not in {'active', 'unconfigured'} or account.auth_type != 'manual':
        p.fail('SCOPE_FORBIDDEN', 403)
    channel = await session.scalar(select(GeoPublishingChannel).options(load_only(
        GeoPublishingChannel.id, GeoPublishingChannel.tenant_id, GeoPublishingChannel.channel_type,
        GeoPublishingChannel.enabled)).where(GeoPublishingChannel.id == account.channel_id,
        GeoPublishingChannel.tenant_id == store.tenant_id).with_for_update().execution_options(populate_existing=True))
    if channel is None or channel.channel_type != 'wechat' or not channel.enabled:
        p.fail('SCOPE_FORBIDDEN', 403)
    if account.expires_at:
        expiry = account.expires_at
        if expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=timezone.utc)
        if expiry.timestamp() * 1000 < now_ms():
            p.fail('SCOPE_FORBIDDEN', 403)
    return account


async def placeholder_account(store, project_id, actor):
    # open_store holds the tenant + module locks until the pairing commits.
    # The existing channel JSON marks ownership; never adopt a same-name user channel.
    session = store.session
    channel = await session.scalar(select(GeoPublishingChannel).options(load_only(
        GeoPublishingChannel.id, GeoPublishingChannel.channel_type, GeoPublishingChannel.enabled,
        GeoPublishingChannel.content_rules)).where(GeoPublishingChannel.tenant_id == store.tenant_id,
        GeoPublishingChannel.name == '多号通公众号').with_for_update().execution_options(populate_existing=True))
    if channel is None:
        channel = GeoPublishingChannel(tenant_id=store.tenant_id, name='多号通公众号', channel_type='wechat',
            publish_mode='manual_only', enabled=True, content_rules={'duohaotong_placeholder': 1}, created_by=actor['user_id'])
        session.add(channel)
        await session.flush()
        store.audit('PLACEHOLDER_CHANNEL_CREATED', actor=actor['user_id'], tenant_id=store.tenant_id,
            project_id=project_id, channel_id=channel.id, reason='device_pairing')
    elif channel.channel_type != 'wechat' or (channel.content_rules or {}).get('duohaotong_placeholder') != 1:
        p.fail('PLACEHOLDER_CONFLICT')
    elif not channel.enabled:
        p.fail('PLACEHOLDER_DISABLED')
    account = await session.scalar(select(GeoChannelAccount).options(load_only(
        GeoChannelAccount.id, GeoChannelAccount.auth_type, GeoChannelAccount.status, GeoChannelAccount.expires_at))
        .where(GeoChannelAccount.tenant_id == store.tenant_id, GeoChannelAccount.channel_id == channel.id,
               GeoChannelAccount.display_name == '多号通公众号（发布时上报）')
        .with_for_update().execution_options(populate_existing=True))
    if account is None:
        account = GeoChannelAccount(tenant_id=store.tenant_id, channel_id=channel.id,
            display_name='多号通公众号（发布时上报）', auth_type='manual', status='active', created_by=actor['user_id'])
        session.add(account)
        await session.flush()
        store.audit('PLACEHOLDER_ACCOUNT_CREATED', actor=actor['user_id'], tenant_id=store.tenant_id,
            project_id=project_id, channel_id=channel.id, account_id=account.id, reason='device_pairing')
    elif account.auth_type != 'manual' or account.status != 'active':
        p.fail('PLACEHOLDER_DISABLED')
    await account_binding(store, account.id)
    return account.id


async def create_pairing(store, project_id, actor, body):
    p.exact(body, {'label', 'platform', 'expected_revision'} | ({'account_id'} if 'account_id' in body else set()))
    if (body['platform'] != 'wechat-article' or not isinstance(body['label'], str)
            or not 1 <= len(body['label'].strip()) <= 80 or not body['label'].isprintable()):
        p.fail('INVALID_SHAPE', 422)
    p.integer(body['expected_revision'], 0)
    account_id = body.get('account_id')
    if account_id is not None:
        account_id = p.integer(int(account_id)) if isinstance(account_id, str) and account_id.isdecimal() else p.integer(account_id)
        await account_binding(store, account_id)
    if store.book['revision'] != body['expected_revision']:
        p.fail('SOURCE_CHANGED')
    now = now_ms()
    if (sum(not d['revoked'] and d['expires_at'] > now for d in store.book['devices'].values()) >= MAX_ACTIVE_DEVICES
            or sum(not d['consumed'] and d['expires_at'] > now for d in store.book['pairings'].values()) >= MAX_UNUSED_PAIRINGS):
        p.fail('REPORT_LEDGER_CAPACITY', 429)
    if account_id is None:
        await actor_authorized(store, project_id, actor)
        account_id = await placeholder_account(store, project_id, actor)
    code = secrets.token_urlsafe(24)
    key = uuid()
    store.book['pairings'][key] = {'id': key, 'code_hash': sha(code), 'scope_id': project_id,
        'account_id': account_id, 'label': body['label'].strip(), 'actor': actor, 'expires_at': now + 600_000, 'consumed': False}
    store.book['revision'] += 1
    store.audit('PAIRING_CREATED', actor=actor['user_id'])
    await store.save()
    return {'schema': 1, 'pairing_id': key, 'pairing_code': code, 'expires_at': now + 600_000}


async def claim(session, body):
    p.exact(body, {'pairing_code', 'request_id'})
    code = body['pairing_code']
    if not isinstance(code, str) or not re.fullmatch(r'[A-Za-z0-9_-]{32}', code):
        p.fail('PAIRING_CODE_UNAVAILABLE')
    p.ident(body['request_id'])
    try:
        UUID(body['request_id'])
    except ValueError:
        p.fail('INVALID_SHAPE', 422)
    code_hash = sha(code)
    # JSON search only returns a locator. Lock/reload and constant-time compare
    # again before single consumption. Never scan/read another module's rows.
    locator = await hash_locator(session, 'pairings', 'code_hash', code_hash)
    if locator is None:
        p.fail('PAIRING_CODE_UNAVAILABLE')
    store = await open_store(session, locator)
    pairing = next((r for r in store.book['pairings'].values() if hmac.compare_digest(r['code_hash'], code_hash)), None)
    now = now_ms()
    if pairing is None:
        p.fail('PAIRING_CODE_UNAVAILABLE')
    failures = pairing.get('claim_failures') or {}
    count = failures.get('count', 0) if now < failures.get('until', 0) else 0
    if count >= PAIRING_FAILURE_LIMIT:
        p.fail('DEVICE_RATE_LIMITED', 429)
    try:
        if pairing['consumed'] or pairing['expires_at'] <= now:
            p.fail('PAIRING_CODE_UNAVAILABLE')
        await actor_authorized(store, pairing['scope_id'], pairing['actor'])
        await account_binding(store, pairing['account_id'])
        if sum(not d['revoked'] and d['expires_at'] > now for d in store.book['devices'].values()) >= MAX_ACTIVE_DEVICES:
            p.fail('REPORT_LEDGER_CAPACITY', 429)
    except HTTPException as error:
        # Row serialization makes failures durable across workers/restarts.
        # Only the failure metadata changes; no device/grant is created here.
        pairing['claim_failures'] = {'count': count + 1,
            'until': failures['until'] if count else now + PAIRING_FAILURE_WINDOW_MS}
        await store.save()
        raise PairingRejected(error.status_code, error.detail, headers=error.headers) from None
    device_id = uuid()
    # Keep the frozen pairing schema: exactly 64 base64url characters. The
    # optional dr1 locator proposed in the design is incompatible with that
    # schema. Locate by hash in GEO rows only; no credential is returned twice.
    credential = secrets.token_urlsafe(48)
    store.book['devices'][device_id] = {'id': device_id, 'label': pairing['label'],
        'scope_id': pairing['scope_id'], 'account_id': pairing['account_id'], 'binding_id': uuid(),
        'actor': pairing['actor'], 'credential_hash': sha(credential), 'expires_at': now + 90 * 86400_000,
        'revoked': False, 'request_seq': 0, 'request_digest': None}
    pairing['consumed'] = True
    store.book['revision'] += 1
    store.audit('PAIRING_CLAIMED', device=device_id)
    await store.save()
    return {'schema': 1, 'pairing_id': pairing['id'], 'claimed_at': now,
            'device': {'id': device_id, 'label': pairing['label'], 'active': True,
                       'credential': credential, 'credential_once': True},
            'bindings_configured': False, 'automatic_submit': False}


def native_headers(request):
    if any(request.headers.get(k) is not None for k in ('origin', 'cookie', 'sec-fetch-site', 'sec-fetch-mode', 'sec-fetch-dest')):
        p.fail('DEVICE_CREDENTIAL_INVALID', 401)
    if request.query_params:
        p.fail('INVALID_SHAPE', 422)


async def authenticate(session, request, *, reporting):
    native_headers(request)
    raw = request.headers.get('authorization', '')
    match = re.fullmatch(r'Bearer ([A-Za-z0-9_-]{64})', raw)
    if match is None:
        p.fail('DEVICE_CREDENTIAL_INVALID', 401)
    credential = match.group(1)
    credential_hash = sha(credential)
    tenant_id = await hash_locator(session, 'devices', 'credential_hash', credential_hash)
    if tenant_id is None:
        p.fail('DEVICE_CREDENTIAL_INVALID', 401)
    store = await open_store(session, tenant_id)
    device = next((d for d in store.book['devices'].values()
                   if hmac.compare_digest(d['credential_hash'], credential_hash)), None)
    if device is None:
        p.fail('DEVICE_CREDENTIAL_INVALID', 401)
    if device['revoked']:
        p.fail('DEVICE_REVOKED', 403)
    if device['expires_at'] < now_ms():
        p.fail('DEVICE_CREDENTIAL_EXPIRED', 401)
    await actor_authorized(store, device['scope_id'], device['actor'])
    await account_binding(store, device['account_id'])
    if reporting and not p.enabled(store.book, device['scope_id']):
        p.fail('REPORTING_DISABLED', 403)
    return store, device


async def device_profile(store, device):
    # Explicit display-only columns: never load account secrets or client selectors.
    customer = await store.session.scalar(select(Tenant.name).where(Tenant.id == store.tenant_id))
    project = await store.session.scalar(select(GeoProject.name).where(
        GeoProject.id == device['scope_id'], GeoProject.tenant_id == store.tenant_id,
        GeoProject.tenant_module_id == store.row.id))
    account = await store.session.scalar(select(GeoChannelAccount.display_name).where(
        GeoChannelAccount.id == device['account_id'], GeoChannelAccount.tenant_id == store.tenant_id))
    return {'schema': 1, 'device_id': device['id'], 'customer_name': display_name(customer),
            'scope_name': display_name(project), 'account_name': display_name(account),
            'label': display_name(device['label'])}


def transport(device, request, raw):
    bucket = now_ms() // 60_000
    count = device.get('rate_count', 0) if device.get('rate_bucket') == bucket else 0
    if count >= 120:
        p.fail('DEVICE_RATE_LIMITED', 429)
    device['rate_bucket'], device['rate_count'] = bucket, count + 1
    seq, sent = request.headers.get('x-distribution-request-seq', ''), request.headers.get('x-distribution-sent-at', '')
    if not re.fullmatch(r'[1-9][0-9]{0,15}', seq) or not re.fullmatch(r'[1-9][0-9]{0,15}', sent):
        p.fail('INVALID_SHAPE', 422)
    seq, sent = p.integer(int(seq)), p.integer(int(sent))
    if abs(now_ms() - sent) > p.WINDOW_MS:
        p.fail('CLOCK_SKEW', 422)
    fingerprint = p.digest([request.method, request.url.path, hashlib.sha256(raw).hexdigest(), seq, sent])
    if seq < device['request_seq'] or (seq == device['request_seq'] and fingerprint != device['request_digest']):
        p.fail('REPLAY_REJECTED')
    device['request_seq'], device['request_digest'] = seq, fingerprint


def binding(store, device):
    return {'customerId': str(store.tenant_id), 'projectId': f"geo-{device['scope_id']}",
            'deviceId': device['id'], 'accountId': str(device['account_id']), 'platform': 'wechat-article'}


async def native_task(store, project_id, task_id, variant_id, article_id, *, publish):
    from app.geo.content import routes
    from app.geo.content.gate import PublishGateError
    project, businesses = await selected_project(store, project_id)
    prompts = await prompt_ids_for_businesses(store.session, store.tenant_id, businesses)
    task = await store.session.scalar(select(GeoContentTask).where(
        GeoContentTask.id == task_id, GeoContentTask.tenant_id == store.tenant_id,
        GeoContentTask.prompt_id.in_(prompts), GeoContentTask.business_id.in_(businesses))
        .with_for_update().execution_options(populate_existing=True))
    if task is None:
        p.fail('TASK_NOT_FOUND', 404)
    # Verify the exact business along the prompt->unit chain as well as task.business_id.
    prompt = await store.session.scalar(select(GeoPrompt).where(GeoPrompt.id == task.prompt_id,
        GeoPrompt.tenant_id == store.tenant_id).with_for_update().execution_options(populate_existing=True))
    unit = await store.session.scalar(select(GeoOptimizationUnit).where(
        GeoOptimizationUnit.id == prompt.unit_id, GeoOptimizationUnit.tenant_id == store.tenant_id)
        .with_for_update().execution_options(populate_existing=True)) if prompt else None
    if unit is None or unit.business_id != task.business_id:
        p.fail('TASK_NOT_FOUND', 404)
    business = await store.session.scalar(select(GeoOptimizationBusiness).where(
        GeoOptimizationBusiness.id == task.business_id, GeoOptimizationBusiness.tenant_id == store.tenant_id)
        .with_for_update().execution_options(populate_existing=True))
    if publish and (task.status in {'archived', 'cancelled'} or prompt.status != 'active'
                    or unit.status != 'active' or business is None or business.status != 'active'):
        p.fail('SCOPE_FORBIDDEN', 403)
    variant = await store.session.scalar(select(GeoChannelVariant).where(
        GeoChannelVariant.id == variant_id, GeoChannelVariant.task_id == task.id,
        GeoChannelVariant.channel == 'wechat').with_for_update().execution_options(populate_existing=True))
    article = await routes._latest_article(store.session, task.id, fresh=True)
    if variant is None or article is None:
        p.fail('TASK_NOT_FOUND', 404)
    if publish:
        if variant.article_version_id != article.id or article.id != article_id:
            p.fail('SOURCE_CHANGED')
        rule = await routes._build_rule_input(store.session, task, article, fresh=True, refresh_citations=False)
        tenant = await routes._ensure_tenant_exists(store.session, store.tenant_id, fresh=True)
        brand, _ = await routes._brand_context_for_task(store.session, task, tenant, fresh=True)
        try:
            routes.assert_can_publish(rule, task=task, brand=brand)
        except PublishGateError:
            p.fail('REVIEW_REQUIRED')
    return task, variant, article


def content_for(variant, article):
    body = variant.body_markdown or ''
    meta = article.generation_meta or {}
    # Until a controlled module asset endpoint exists, reject every image/asset
    # representation rather than silently emitting an incomplete article.
    asset_keys = ('assets', 'images', 'cover', 'cover_image', 'cover_url', 'cover_image_url', 'thumb_media_id')
    rendered = '\n'.join([body, article.body_html or '', p.encode(variant.adapt_meta or {}).decode()])
    if (re.search(r'!\[|<\s*(img|picture|video|audio|svg|iframe)\b|data:', rendered, re.I)
            or any(meta.get(k) for k in asset_keys)
            or any((variant.adapt_meta or {}).get(k) for k in asset_keys)):
        p.fail('ASSET_UNAVAILABLE', 422)
    return {'version': f'geo-article-{article.id}', 'title': variant.title, 'body': body, 'assets': []}


async def create_task(store, project_id, actor, body):
    p.exact(body, {'content_task_id', 'variant_id', 'article_version_id', 'payload_hash', 'device_id', 'request_id'})
    for k in ('content_task_id', 'variant_id', 'article_version_id'):
        p.integer(body[k])
    p.ident(body['device_id']); p.ident(body['request_id'])
    if not p.enabled(store.book, project_id):
        p.fail('REPORTING_DISABLED', 403)
    device = store.book['devices'].get(body['device_id'])
    if device is None or device['scope_id'] != project_id or device['revoked'] or device['expires_at'] <= now_ms():
        p.fail('SCOPE_FORBIDDEN', 403)
    await account_binding(store, device['account_id'])
    task, variant, article = await native_task(store, project_id, body['content_task_id'], body['variant_id'], body['article_version_id'], publish=True)
    content = content_for(variant, article)
    digest = p.content_digest(content)
    if body['payload_hash'] != digest:
        p.fail('SOURCE_CHANGED')
    fingerprint = p.digest([project_id, actor, body])
    for old in store.book['tasks'].values():
        if old['request_id'] == body['request_id']:
            if old['request_digest'] != fingerprint:
                p.fail('IDEMPOTENCY_CONFLICT')
            return task_projection(old)
        if (old['device_id'] == device['id'] and old['native_task_id'] == task.id
                and old['variant_id'] == variant.id and old['article_id'] == article.id
                and old['outcome'] not in {'failed', 'canceled'}):
            p.fail('IDEMPOTENCY_CONFLICT')
    if (len(store.book['tasks']) >= p.MAX_TASKS or sum(t['expires_at'] > now_ms() and t['outcome'] not in
            {'succeeded', 'failed', 'canceled'} for t in store.book['tasks'].values()) >= 100):
        p.fail('REPORT_LEDGER_CAPACITY', 429)
    key, lease, grant_id, publication_id = uuid(), uuid(), uuid(), uuid()
    expires = min(now_ms() + 86400_000, device['expires_at'])
    target = binding(store, device)
    wire = {**target, 'contractVersion': 1, 'id': key, 'idempotencyKey': uuid(),
        'grantId': grant_id, 'publicationGrantId': publication_id, 'contentDigest': digest,
        'action': 'publish', 'leaseId': lease, 'leaseExpiresAt': expires}
    # Store the immutable fingerprint and references, not article text.
    entry = {'wire': wire, 'target': {**target, 'contentVersion': content['version'], 'contentDigest': digest, 'leaseId': lease},
        'device_id': device['id'], 'scope_id': project_id, 'native_task_id': task.id, 'variant_id': variant.id,
        'article_id': article.id, 'actor': actor, 'expires_at': expires,
        'request_id': body['request_id'], 'request_digest': fingerprint, 'outcome': 'queued', 'last_code': 'QUEUED',
        'events': {'receipt': {}, 'observation': {}}, 'sequence': {'receipt': 0, 'observation': 0}, 'publication_id': None}
    store.book['tasks'][key] = entry
    variant.adapt_meta = {**(variant.adapt_meta or {}), p.KEY: {'project_id': project_id, **task_projection(entry)}}
    store.audit('TASK_AUTHORIZED', actor=actor['user_id'], device=device['id'], task=key)
    await store.save()
    return task_projection(entry)


def task_projection(task):
    return {'taskId': task['wire']['id'], 'content_task_id': task['native_task_id'],
            'variant_id': task['variant_id'], 'article_version_id': task['article_id'],
            'leaseId': task['wire']['leaseId'], 'contentVersion': task['target']['contentVersion'],
            'contentDigest': task['target']['contentDigest'], 'manual_only': True,
            'reportedOutcome': task['outcome'], 'code': task['last_code'],
            'delivered': bool(task['events']['receipt'] or task['events']['observation']),
            'nativePublicationId': task['publication_id'],
            **({'reportedAccount': task['reportedAccount']} if 'reportedAccount' in task else {})}


async def task_authorized(store, device, task_id, *, publish):
    task = store.book['tasks'].get(task_id)
    if task is None or task['device_id'] != device['id'] or task['scope_id'] != device['scope_id']:
        p.fail('TASK_NOT_FOUND', 404)
    await actor_authorized(store, device['scope_id'], task['actor'])
    native, variant, article = await native_task(store, device['scope_id'], task['native_task_id'],
        task['variant_id'], task['article_id'], publish=publish)
    if publish:
        if task['expires_at'] < now_ms():
            p.fail('LEASE_EXPIRED')
        if p.content_digest(content_for(variant, article)) != task['target']['contentDigest']:
            p.fail('SOURCE_CHANGED')
    return task, native, variant, article


async def apply_events(store, device, events, stream):
    from app.geo.content import routes
    from app.geo.content.gate import PublishGateError
    if not isinstance(events, list) or len(events) > 64:
        p.fail('INVALID_SHAPE', 422)
    acks = []
    # Validate and process in client order; jumps allowed, unknown regressions rejected.
    for event in events:
        if not isinstance(event, dict) or not isinstance(event.get('taskId'), str):
            p.fail('INVALID_SHAPE', 422)
        success = event.get('code') == 'HUMAN_PUBLISHED'
        task, native, variant, article = await task_authorized(store, device, event['taskId'], publish=success)
        ack = p.validate_event(event, task, device['id'], stream)
        if event['at'] > now_ms() + p.WINDOW_MS:
            p.fail('CLOCK_SKEW', 422)
        ack, new = p.admit_event(store.book, task, event, stream, ack)
        if new and success:
            account = p.reported_account(event, stream)
            note = '多号通人工确认链接；页面待核验'
            if account is not None:
                note += '；回传公众号：' + account['name']
            try:
                await routes._write_publication(store.session, task=native, variant=variant, channel='wechat',
                    published_url=event['publicUrl'], note=note, publish_mode='manual_export')
            except PublishGateError:
                p.fail('REVIEW_REQUIRED')
            # The existing writer's HTTP-advisor hook has no human session
            # binding on an opaque-device request. Explicitly recheck its saved
            # authority on this same locked transaction, rather than relying on
            # that hook becoming a no-op or impersonating an administrator.
            await actor_authorized(store, device['scope_id'], task['actor'])
            await account_binding(store, device['account_id'])
            pub = await store.session.scalar(select(GeoPublication).where(
                GeoPublication.variant_id == variant.id, GeoPublication.channel == 'wechat',
                GeoPublication.published_url == event['publicUrl']))
            if pub is None:
                p.fail('REPORT_STORAGE_UNAVAILABLE', 503)
            task['publication_id'] = pub.id
            task['reported_url'] = event['publicUrl']
            if account is not None:
                task['reportedAccount'] = account
        if new:
            store.audit('RESULT_RECEIVED', device=device['id'], task=task['wire']['id'])
            variant.adapt_meta = {**(variant.adapt_meta or {}), p.KEY: {'project_id': task['scope_id'], **task_projection(task)}}
        acks.append(ack)
    return acks


async def envelope(store, device, acks):
    tasks, grants = [], []
    for entry in store.book['tasks'].values():
        if entry['device_id'] != device['id'] or entry['outcome'] in {'succeeded', 'failed', 'canceled'} or entry['expires_at'] < now_ms():
            continue
        # Pending human tasks continue to carry both grants after ACCEPTED.
        try:
            _, _, variant, article = await task_authorized(store, device, entry['wire']['id'], publish=True)
        except Exception as exc:
            from fastapi import HTTPException
            if isinstance(exc, HTTPException):
                continue
            raise
        tasks.append({**entry['wire'], 'content': content_for(variant, article)})
        for purpose, key in [('task', 'grantId'), ('publication', 'publicationGrantId')]:
            grants.append({**binding(store, device), 'purpose': purpose, 'id': entry['wire'][key],
                'advisorId': str(entry['actor']['user_id']), 'contentVersion': entry['target']['contentVersion'],
                'contentDigest': entry['target']['contentDigest'], 'actions': ['publish'],
                'expiresAt': entry['expires_at'], 'revoked': False})
    return {'contractVersion': 1, 'deviceAuthorized': True, 'receiptAcks': acks,
            'pausedTaskIds': [], 'binding': [binding(store, device)], 'paused': False,
            'grants': grants, 'tasks': tasks}


async def verification(store, task):
    state = {'state': 'pending', 'reason': 'not_checked', 'checkedAt': None}
    if task['publication_id']:
        from app.geo.publication_monitor import state_for, report_check
        from app.geo.content import routes
        variant = await store.session.get(GeoChannelVariant, task['variant_id'], populate_existing=True)
        pub = await store.session.get(GeoPublication, task['publication_id'], populate_existing=True)
        if variant and pub and pub.variant_id == variant.id:
            monitor = state_for(variant, pub)
            article = await routes._latest_article(store.session, task['native_task_id'], fresh=True)
            proof = report_check(variant, pub, article.id if article else None)
            status = monitor.get('state', 'pending')
            current_digest = p.content_digest({'version': task['target']['contentVersion'], 'title': variant.title,
                                               'body': variant.body_markdown, 'assets': []})
            if (article is None or article.id != task['article_id']
                    or current_digest != task['target']['contentDigest']
                    or pub.published_url != task.get('reported_url')):
                status = 'version_changed'
            elif status == 'healthy' and not proof['verified']:
                status = 'pending'
            state = {'state': {'healthy': 'verified', 'mismatch': 'failed', 'unreachable': 'unavailable'}.get(status, status),
                     'reason': status, 'checkedAt': monitor.get('checked_at')}
    return {**task_projection(task), 'verification': state, 'publicationVerified': state['state'] == 'verified'}
