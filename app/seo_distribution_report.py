"""Tenant-bound manual publication reports in the existing SEO module JSON.

All mutations use a fresh module row UPDATE lock. Never store device plaintext,
article bodies, provider credentials or arbitrary device errors in this ledger.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import hashlib
import hmac
import re
import secrets
import time
import unicodedata
from types import SimpleNamespace
from uuid import uuid4

from bs4 import BeautifulSoup
from fastapi import HTTPException
from sqlalchemy import cast, func, select
from sqlalchemy.dialects.postgresql import JSONB, JSONPATH
from starlette.requests import Request

from app.models.module_workspace import TenantModule, SeoSite
from app.models.seo import SeoContentPublication, SeoDistributionConnection, SeoDistributionVariant, SeoPublishAttempt
from app.module_scope import module_is_available
from app.seo_distribution_protocol import (KEY, PREFIX, TARGET, admit_event, canonical,
    content_digest, deny, digest, enabled, positive, registry)


def now_ms():
    return int(time.time() * 1000)


def sha(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


async def locked_module(session, tenant_id):
    row = await session.scalar(select(TenantModule).where(
        TenantModule.tenant_id == tenant_id, TenantModule.module_code == 'seo',
    ).with_for_update().execution_options(populate_existing=True))
    if row is None or not module_is_available(row):
        deny('SCOPE_FORBIDDEN', 403)
    return row


def store(module, state):
    if len(canonical(state).encode('utf-8')) > 8 * 1024 * 1024:
        deny('REPORT_LEDGER_CAPACITY', 429)
    # The caller obtained populate_existing under the row lock; preserve all
    # other settings namespaces, including concurrent AI/day quota updates.
    module.module_settings = {**(module.module_settings or {}), KEY: deepcopy(state)}


def audit(state, action, *, actor=None, device=None, task=None):
    state['audit'].append({'action': action, 'actor': actor, 'device': device, 'task': task, 'at': now_ms()})


async def site_scope(session, tenant_id, site_id, *, lock=True):
    query = select(SeoSite).where(SeoSite.id == site_id, SeoSite.tenant_id == tenant_id)
    if lock:
        query = query.with_for_update()
    site = await session.scalar(query.execution_options(populate_existing=True))
    if site is None or site.status != 'active':
        deny('SCOPE_FORBIDDEN', 403)
    return site


async def connection_scope(session, tenant_id, site_id, account_id):
    if not isinstance(account_id, str) or not re.fullmatch(r'seo-connection-[1-9][0-9]{0,17}', account_id):
        deny('SCOPE_FORBIDDEN', 403)
    connection_id = int(account_id.removeprefix('seo-connection-'))
    # Select safe fields only: never load platform credentials for this feature.
    table = SeoDistributionConnection.__table__
    row = (await session.execute(select(table.c.id, table.c.tenant_id, table.c.platform_code,
        table.c.enabled, table.c.config).where(table.c.id == connection_id)
        .with_for_update(read=True))).mappings().first()
    if (row is None or row['tenant_id'] != tenant_id or row['platform_code'] != 'wechat_browser'
            or row['enabled'] is not True):
        deny('SCOPE_FORBIDDEN', 403)
    from app.security.seo_advisor_connections import ensure_connection_binding
    await ensure_connection_binding(session, SimpleNamespace(tenant_id=tenant_id), [row], site_id)
    return connection_id


def proof_for(ctx):
    return {'user_id': ctx.user_id, 'tenant_id': ctx.tenant_id, 'advisor': ctx.is_advisor,
            'grant_id': ctx.grant_id, 'auth_exp': ctx.auth_exp}


async def authorize_actor(session, proof, tenant_id, site_id, task_request=None):
    """Rebuild current human authority. Never manufacture a privileged context."""
    from app.config import get_settings
    from app.models.user import User
    from app.models.role import Role
    from app.security.auth import _build_context
    from app.security.advisor_scope import account_locked
    from app.security.advisor_tenant_auth import apply_advisor_claims
    from app.security.advisor_write_commit import recheck_advisor_before_commit
    from app.security.advisor_write_routes import WRITE_ROUTES
    user = await session.scalar(select(User).where(User.id == proof.get('user_id'))
        .with_for_update(read=True).execution_options(populate_existing=True))
    if user is None or not user.is_active or account_locked(user):
        deny('ACTOR_AUTHORIZATION_REVOKED', 403)
    role = await session.scalar(select(Role).where(Role.id == user.role_id)
        .with_for_update(read=True).execution_options(populate_existing=True))
    ctx = await _build_context(user, session)
    if proof.get('advisor') is True:
        if not get_settings().advisor_scoped_content_writes_enabled or proof.get('tenant_id') != tenant_id:
            deny('ACTOR_AUTHORIZATION_REVOKED', 403)
        ctx = await apply_advisor_claims(ctx, user, role, {
            'scope_kind': 'advisor_tenant', 'aud': 'advisor-business',
            'tid': tenant_id, 'gid': proof.get('grant_id'),
            'exp': proof.get('auth_exp'), 'auth_exp': proof.get('auth_exp'),
        }, session)
        template = PREFIX + '/tasks'
        body = task_request or {}
        request = Request({'type': 'http', 'method': 'POST', 'path': template,
            'path_params': {}, 'query_string': f'tenant_id={tenant_id}&site_id={site_id}'.encode(),
            'headers': [], 'route': SimpleNamespace(path=template)})
        rule = WRITE_ROUTES[('POST', template)]
        ctx.advisor_write_rule, ctx.advisor_write_scope = rule, (request, body, rule)
        await recheck_advisor_before_commit(session, ctx)
    else:
        ctx.ensure_tenant(tenant_id)
        if not ctx.can_edit('settings.accounts') or not ctx.can_edit('seo.content'):
            deny('ACTOR_AUTHORIZATION_REVOKED', 403)
    return ctx


def settings_payload(state, site_id):
    scope = state['scopes'].get(str(site_id), {})
    return {'schema': 1, 'enabled': state['enabled'], 'revision': state['revision'],
        'scope_enabled': scope.get('enabled') is True, 'scope_revision': scope.get('revision', 0),
        'human_confirmation_required': True,
        'devices': [{'id': d['id'], 'label': d['label'], 'active': not d['revoked'] and d['expires'] > now_ms(),
                     'expires_at': d['expires'], 'account_id': d['account_id'], 'platform': 'wechat-article'}
                    for d in state['devices'].values() if d['site_id'] == site_id],
        'tasks': [task_payload(t) for t in state['tasks'].values() if t['site_id'] == site_id]}


def task_payload(task):
    return {'taskId': task['wire']['id'], 'nativePublicationId': task['publication_id'],
        'deviceId': task['target']['deviceId'], 'reportedOutcome': task['outcome'],
        'delivery': 'received' if any(t['events'] for t in task['streams'].values()) else 'pending',
        'last_code': task.get('last_code'), 'verification': deepcopy(task['verification']),
        'publicationVerified': task['verification']['state'] == 'verified'}


async def set_settings(session, module, state, site_id, body, ctx):
    scope = state['scopes'].get(str(site_id), {'enabled': False, 'revision': 0})
    if body['expected_revision'] != state['revision'] or body['expected_scope_revision'] != scope['revision']:
        deny('SOURCE_CHANGED')
    if body['enabled'] and not state['enabled']:
        # Reopening the tenant for this site must not reactivate older sites,
        # including sites outside this advisor's current assignment.
        for key, other in state['scopes'].items():
            if key != str(site_id) and other.get('enabled') is True:
                state['scopes'][key] = {**other, 'enabled': False, 'revision': other['revision'] + 1}
    state['enabled'] = body['enabled']
    state['revision'] += 1
    state['scopes'][str(site_id)] = {'enabled': body['scope_enabled'], 'revision': scope['revision'] + 1}
    audit(state, 'settings_changed', actor=ctx.user_id)
    store(module, state)
    return settings_payload(state, site_id)


async def create_pairing(session, module, state, site_id, body, ctx):
    label = body.get('label')
    if (not isinstance(label, str) or not label.strip() or len(label) > 80
            or any(unicodedata.category(c).startswith('C') for c in label)):
        deny('INVALID_SHAPE', 422)
    if body['expected_revision'] != state['revision']:
        deny('SOURCE_CHANGED')
    await connection_scope(session, module.tenant_id, site_id, body['account_id'])
    now = now_ms()
    if (sum(not d['revoked'] and d['expires'] > now for d in state['devices'].values()) >= 20
            or sum(not p['consumed'] and p['expires'] > now for p in state['pairings'].values()) >= 20):
        deny('REPORT_LEDGER_CAPACITY', 429)
    code, pairing_id, device_id = secrets.token_urlsafe(24), str(uuid4()), str(uuid4())
    state['pairings'][sha(code)] = {'id': pairing_id, 'device_id': device_id, 'site_id': site_id,
        'label': label.strip(), 'account_id': body['account_id'], 'expires': now + 600000,
        'consumed': False, 'actor': proof_for(ctx)}
    state['revision'] += 1
    audit(state, 'pairing_created', actor=ctx.user_id, device=device_id)
    store(module, state)
    return {'schema': 1, 'pairing_id': pairing_id, 'pairing_code': code, 'expires_at': now + 600000}


async def claim_pairing(session, code):
    code_hash = sha(code)
    locator = await session.scalar(select(TenantModule).where(TenantModule.module_code == 'seo',
        TenantModule.module_settings[KEY]['pairings'].has_key(code_hash))  # noqa: W601
        .execution_options(populate_existing=True))
    if locator is None or not module_is_available(locator):
        deny('PAIRING_CODE_UNAVAILABLE')
    hint = registry(locator.module_settings)['pairings'].get(code_hash)
    if not hint:
        deny('PAIRING_CODE_UNAVAILABLE')
    if len([at for at in hint.get('claim_failures', []) if at > now_ms() - 60000]) >= 10:
        deny('DEVICE_RATE_LIMITED', 429)
    await site_scope(session, locator.tenant_id, hint['site_id'])
    module = await locked_module(session, locator.tenant_id)
    state = registry(module.module_settings)
    pairing = state['pairings'].get(code_hash)
    now = now_ms()
    if pairing and len([at for at in pairing.get('claim_failures', []) if at > now - 60000]) >= 10:
        deny('DEVICE_RATE_LIMITED', 429)
    if not pairing or pairing['consumed'] or pairing['expires'] <= now:
        deny('PAIRING_CODE_UNAVAILABLE')
    await authorize_actor(session, pairing['actor'], module.tenant_id, pairing['site_id'])
    await connection_scope(session, module.tenant_id, pairing['site_id'], pairing['account_id'])
    # Pending codes cannot reserve device capacity forever. Recheck under the
    # same module lock at consumption, including codes issued before this release.
    if sum(not d['revoked'] and d['expires'] > now for d in state['devices'].values()) >= 20:
        deny('REPORT_LEDGER_CAPACITY', 429)
    device_id = pairing['device_id']
    # Preserve the frozen client schema: 64 base64url characters, no locator.
    credential = secrets.token_urlsafe(48)
    state['devices'][device_id] = {'id': device_id, 'site_id': pairing['site_id'],
        'binding_id': str(uuid4()), 'label': pairing['label'], 'account_id': pairing['account_id'],
        'credential_hash': sha(credential), 'expires': now + 90 * 86400000,
        'revoked': False, 'transport_seq': 0, 'request_hash': None,
        'last_acks': [], 'last_stream': None, 'actor': pairing['actor']}
    pairing['consumed'] = True
    audit(state, 'pairing_claimed', device=device_id)
    store(module, state)
    # Commit before the single-use plaintext can leave the service.
    await session.commit()
    return {'schema': 1, 'pairing_id': pairing['id'], 'claimed_at': now,
        'device': {'id': device_id, 'label': pairing['label'], 'active': True,
                   'credential': credential, 'credential_once': True},
        'bindings_configured': False, 'automatic_submit': False}


async def record_claim_failure(session, code):
    """Persist only failures of a known code, after rolling back failed work.

    Lock only the module and never acquire other locks here. This separate
    transaction cannot accidentally commit partial authorization/claim work.
    """
    code_hash = sha(code)
    tenant_id = await session.scalar(select(TenantModule.tenant_id).where(
        TenantModule.module_code == 'seo',
        TenantModule.module_settings[KEY]['pairings'].has_key(code_hash)))  # noqa: W601
    if tenant_id is None:
        return False
    module = await session.scalar(select(TenantModule).where(
        TenantModule.tenant_id == tenant_id, TenantModule.module_code == 'seo')
        .with_for_update().execution_options(populate_existing=True))
    state = registry(module.module_settings)
    pairing = state['pairings'].get(code_hash)
    if pairing is None:
        return False
    now = now_ms()
    failures = [at for at in pairing.get('claim_failures', []) if at > now - 60000]
    pairing['claim_failures'] = (failures + [now])[-10:]
    store(module, state)
    await session.commit()
    return True


def profile_name(value):
    if not isinstance(value, str):
        return ''
    return ' '.join(''.join(c for c in value if not unicodedata.category(c).startswith('C')).split())[:120]


async def device_profile(session, module, device):
    from app.models.tenant import Tenant
    # Explicit safe columns: do not load the tenant/account ORM objects, which
    # include credentials or unrelated customer information.
    customer = await session.scalar(select(Tenant.name).where(Tenant.id == module.tenant_id))
    scope = await session.scalar(select(SeoSite.name).where(
        SeoSite.id == device['site_id'], SeoSite.tenant_id == module.tenant_id))
    account = await session.scalar(select(SeoDistributionConnection.name).where(
        SeoDistributionConnection.id == int(device['account_id'].removeprefix('seo-connection-')),
        SeoDistributionConnection.tenant_id == module.tenant_id))
    return {'schema': 1, 'device_id': device['id'], 'customer_name': profile_name(customer),
            'scope_name': profile_name(scope), 'account_name': profile_name(account),
            'label': profile_name(device['label'])}


def credential_locator(value):
    if not isinstance(value, str) or re.fullmatch(r'[A-Za-z0-9_-]{64}', value) is None:
        deny('DEVICE_CREDENTIAL_INVALID', 401)
    return sha(value)


async def authenticate(session, credential, *, require_enabled=True):
    credential_hash = credential_locator(credential)
    # Only the exact hash security field can locate a device, never labels or
    # untrusted tenant/device identifiers. The lookup is restricted to SEO.
    tenant_id = await session.scalar(select(TenantModule.tenant_id).where(
        TenantModule.module_code == 'seo',
        func.jsonb_path_exists(TenantModule.module_settings,
            cast(f'$.{KEY}.devices.* ? (@.credential_hash == $h)', JSONPATH),
            cast({'h': credential_hash}, JSONB))).limit(1))
    if tenant_id is None:
        deny('DEVICE_CREDENTIAL_INVALID', 401)
    # Lock site before module, matching existing advisor/workflow lock order.
    # The first read is only an untrusted locator. Recheck the fresh locked row.
    locator = await session.scalar(select(TenantModule.module_settings).where(
        TenantModule.tenant_id == tenant_id, TenantModule.module_code == 'seo'))
    if locator is None:
        deny('DEVICE_CREDENTIAL_INVALID', 401)
    state_hint = registry(locator)
    hint = next((d for d in state_hint['devices'].values()
                 if hmac.compare_digest(d['credential_hash'], credential_hash)), None)
    if hint is None:
        deny('DEVICE_CREDENTIAL_INVALID', 401)
    device_id = hint['id']
    await site_scope(session, tenant_id, hint['site_id'])
    module = await locked_module(session, tenant_id)
    state = registry(module.module_settings)
    device = state['devices'].get(device_id)
    if device is None or not hmac.compare_digest(device['credential_hash'], credential_hash):
        deny('DEVICE_CREDENTIAL_INVALID', 401)
    if device['revoked']:
        deny('DEVICE_REVOKED', 403)
    if device['expires'] <= now_ms():
        deny('DEVICE_CREDENTIAL_EXPIRED', 401)
    if device['site_id'] != hint['site_id']:
        deny('SCOPE_FORBIDDEN', 403)
    if require_enabled and not enabled(state, device['site_id']):
        deny('REPORTING_DISABLED', 403)
    await connection_scope(session, tenant_id, device['site_id'], device['account_id'])
    return module, state, device


def transport_request(device, method, path, raw, seq, sent_at, *, stream):
    if not positive(seq) or not positive(sent_at) or abs(now_ms() - sent_at) > 300000:
        deny('CLOCK_SKEW', 422)
    fingerprint = digest([method, path, hashlib.sha256(raw).hexdigest(), seq, sent_at])
    if seq == device['transport_seq']:
        if device['request_hash'] != fingerprint or device['last_stream'] != stream:
            deny('REPLAY_REJECTED')
        return True
    if seq < device['transport_seq']:
        deny('REPLAY_REJECTED')
    device['transport_seq'] = seq
    device['request_hash'] = fingerprint
    device['last_stream'] = stream
    device['last_acks'] = []
    return False


async def native_snapshot(session, tenant_id, site_id, publication_id, *, task=None):
    from app.api import seo as api
    row = await session.scalar(select(SeoContentPublication).where(
        SeoContentPublication.id == publication_id, SeoContentPublication.tenant_id == tenant_id,
    ).with_for_update().execution_options(populate_existing=True))
    if (row is None or row.platform_code != 'wechat_browser' or api._is_offline_receipt_publication(row)
            or row.status not in {'manual_required', 'failed', 'preparing', 'published'}):
        deny('TASK_NOT_FOUND', 404)
    content = await api._distribution_content(session, tenant_id, row.content_asset_id, site_id, lock=True)
    api._require_content_ready(content)
    if not await api._content_confirmation_schema_ready(session):
        deny('REPORT_SCHEMA_UNAVAILABLE', 503)
    await api._require_active_content_confirmation(session, content)
    if (content.version_count or 1) != row.source_version:
        deny('SOURCE_CHANGED')
    title, body = row.adapted_title or content.title, row.adapted_content or content.humanized_content or content.draft or ''
    if row.variant_id is not None:
        variant = await session.scalar(select(SeoDistributionVariant).where(SeoDistributionVariant.id == row.variant_id)
            .with_for_update(read=True).execution_options(populate_existing=True))
        if (variant is None or variant.tenant_id != tenant_id or variant.content_asset_id != content.id
                or variant.connection_id != row.connection_id or variant.source_version != row.source_version
                or variant.platform_code != 'wechat_browser' or variant.status not in {'approved', 'published'}
                or variant.title != title or variant.content != body):
            deny('REVIEW_REQUIRED')
    elif row.adapted_title is not None or row.adapted_content is not None:
        prepared = api._prepare_distribution_variant(content.title,
            content.humanized_content or content.draft or '', 'wechat_browser')
        if title != prepared['title'] or body != prepared['content']:
            deny('REVIEW_REQUIRED')
    soup = BeautifulSoup(body, 'html.parser')
    # Controlled asset transport is intentionally not implemented in phase one;
    # reject every image-bearing task, including CSS/background/media embeds.
    if soup.select('img,video,audio,svg,picture,source,iframe,object,embed,style,[style]'):
        deny('ASSET_TRANSPORT_UNAVAILABLE', 422)
    if not title or len(title.encode('utf-16-le')) // 2 > 200 or not body or len(body.encode('utf-16-le')) // 2 > 100000:
        deny('INVALID_SHAPE', 422)
    snapshot = {'version': f'seo-{row.id}-v{row.source_version}', 'title': title, 'body': body, 'assets': []}
    payload_hash = api._content_confirmation_hash(content)
    if task and (payload_hash != task['payload_hash'] or content_digest(snapshot) != task['content_digest']
                 or row.connection_id != task['connection_id']):
        deny('SOURCE_CHANGED')
    return row, content, snapshot, payload_hash


async def admit_task(session, module, state, site_id, body, ctx):
    if not enabled(state, site_id):
        deny('REPORTING_DISABLED', 403)
    device = state['devices'].get(body['device_id'])
    if not device or device['site_id'] != site_id or device['revoked'] or device['expires'] <= now_ms():
        deny('SCOPE_FORBIDDEN', 403)
    connection_id = await connection_scope(session, module.tenant_id, site_id, device['account_id'])
    row, content, snapshot, payload_hash = await native_snapshot(session, module.tenant_id, site_id, body['publication_id'])
    if row.source_version != body['source_version'] or payload_hash != body['payload_hash'] or row.connection_id != connection_id:
        deny('SOURCE_CHANGED')
    request_hash = digest(body)
    for task in state['tasks'].values():
        if task['request_id'] == body['request_id']:
            if task['request_hash'] != request_hash or task['actor']['user_id'] != ctx.user_id:
                deny('IDEMPOTENCY_CONFLICT')
            return task_payload(task)
        if task['publication_id'] == row.id and task['outcome'] != 'failed':
            deny('IDEMPOTENCY_CONFLICT')
    if row.status == 'published':
        deny('INVALID_STATE')
    if len(state['tasks']) >= 1000 or sum(t['wire']['leaseExpiresAt'] > now_ms() and t['outcome'] not in {'failed', 'human-reported-published'} for t in state['tasks'].values()) >= 100:
        deny('REPORT_LEDGER_CAPACITY', 429)
    target = {'customerId': str(module.tenant_id), 'projectId': f'seo-{site_id}', 'deviceId': device['id'],
              'accountId': device['account_id'], 'platform': 'wechat-article'}
    task_id = str(uuid4())
    wire = {**target, 'contractVersion': 1, 'id': task_id,
        'idempotencyKey': digest([row.id, row.source_version, target, len(state['tasks'])]),
        'grantId': str(uuid4()), 'publicationGrantId': str(uuid4()),
        'action': 'publish', 'leaseId': str(uuid4()), 'leaseExpiresAt': now_ms() + 3600000}
    if ctx.is_advisor:
        wire['leaseExpiresAt'] = min(wire['leaseExpiresAt'], ctx.auth_exp * 1000)
    task = {'wire': wire, 'target': target, 'site_id': site_id, 'publication_id': row.id,
        'connection_id': connection_id, 'payload_hash': payload_hash, 'source_version': row.source_version,
        'content_version': snapshot['version'], 'content_digest': content_digest(snapshot),
        'actor': proof_for(ctx), 'request': deepcopy(body), 'request_id': body['request_id'],
        'request_hash': request_hash, 'outcome': 'queued',
        'streams': {s: {'high': 0, 'events': {}} for s in ('receipt', 'observation')},
        'verification': {'state': 'pending', 'reason': 'not_reported', 'checkedAt': None}}
    state['tasks'][task_id] = task
    audit(state, 'task_authorized', actor=ctx.user_id, device=device['id'], task=task_id)
    store(module, state)
    return task_payload(task)


async def live_task(session, module, device, task, *, success=True):
    if (task is None or task['target']['deviceId'] != device['id'] or task['site_id'] != device['site_id']
            or task['target']['accountId'] != device['account_id']):
        deny('TASK_NOT_FOUND', 404)
    ctx = await authorize_actor(session, task['actor'], module.tenant_id, device['site_id'], task['request'])
    if success and task['wire']['leaseExpiresAt'] <= now_ms():
        deny('LEASE_EXPIRED')
    return ctx


async def envelope(session, module, state, device, acks):
    tasks, grants = [], []
    target = {'customerId': str(module.tenant_id), 'projectId': f"seo-{device['site_id']}",
              'deviceId': device['id'], 'accountId': device['account_id'], 'platform': 'wechat-article'}
    for task in state['tasks'].values():
        if task['target']['deviceId'] != device['id'] or task['wire']['leaseExpiresAt'] <= now_ms() or task['outcome'] in {'human-reported-published', 'failed'}:
            continue
        await live_task(session, module, device, task)
        _, _, content, _ = await native_snapshot(session, module.tenant_id, device['site_id'], task['publication_id'], task=task)
        for purpose, key in (('task', 'grantId'), ('publication', 'publicationGrantId')):
            grants.append({**target, 'purpose': purpose, 'id': task['wire'][key],
                'advisorId': str(task['actor']['user_id']), 'contentVersion': task['content_version'],
                'contentDigest': task['content_digest'], 'actions': ['publish'],
                'expiresAt': task['wire']['leaseExpiresAt'], 'revoked': False})
        if not task['streams']['receipt']['events']:
            tasks.append({**task['wire'], 'content': content, 'contentDigest': task['content_digest']})
    return {'contractVersion': 1, 'deviceAuthorized': True, 'receiptAcks': acks,
        'pausedTaskIds': [], 'binding': [target], 'paused': False, 'grants': grants, 'tasks': tasks}


async def apply_events(session, module, state, device, events, stream):
    from app.api.seo import complete_manual_publication_in_transaction
    acks = []
    if len({e.get('receiptId' if stream == 'receipt' else 'observationId') for e in events}) != len(events):
        deny('INVALID_SHAPE', 422)
    for event in sorted(events, key=lambda e: e.get('sequence', 0)):
        task = state['tasks'].get(event.get('taskId'))
        is_success = event.get('code') == 'HUMAN_PUBLISHED'
        ctx = await live_task(session, module, device, task, success=is_success)
        if is_success and (event['at'] > now_ms() + 300000 or event['at'] < task['wire']['leaseExpiresAt'] - 3900000):
            deny('CLOCK_SKEW', 422)
        ack, fresh = admit_event(state, task, event, stream)
        if fresh:
            terminal = task['outcome'] in {'human-reported-published', 'failed'}
            # Non-success events on an old version are immutable historical
            # observations; do not mutate current native publication state.
            row = content = None
            try:
                row, content, _, _ = await native_snapshot(session, module.tenant_id, device['site_id'], task['publication_id'], task=task)
            except HTTPException:
                if is_success:
                    raise
            if not is_success and task['wire']['leaseExpiresAt'] <= now_ms():
                row = content = None
            if is_success:
                await complete_manual_publication_in_transaction(session, row, content,
                    page_url=event['publicUrl'], published_at=datetime.utcfromtimestamp(event['at'] / 1000),
                    actor_id=ctx.user_id, action='device_report')
                task['outcome'] = 'human-reported-published'
                task['page_url'] = event['publicUrl']
                task['verification'] = {'state': 'pending', 'reason': 'not_checked', 'checkedAt': None}
            elif event['code'] not in {'ACCEPTED', 'DISPATCHED', 'PREFLIGHT_OK'}:
                if not terminal:
                    task['outcome'] = event['status']
                if row is not None and row.status != 'published' and not terminal:
                    row.status = 'failed' if event['status'] == 'failed' else 'manual_required'
                    row.last_error = event['code']
            if row is not None and not is_success:
                session.add(SeoPublishAttempt(tenant_id=module.tenant_id, publication_id=row.id,
                    action='device_report', status='recorded', response_summary={'code': event['code'],
                        'outcome': event['status'], 'requires_manual_review': event['status'] == 'unknown'},
                    created_by=ctx.user_id, completed_at=datetime.utcnow()))
            task['last_code'] = event['code']
            audit(state, 'event_received', device=device['id'], task=task['wire']['id'])
        acks.append(ack)
    return acks
