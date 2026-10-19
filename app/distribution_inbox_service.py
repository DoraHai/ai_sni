"""Transactional inbox. No native publication, platform fetch or v1 writes."""
from datetime import datetime, timedelta, timezone, date
import hashlib
import hmac
import re
import secrets
import json
from uuid import uuid4

from sqlalchemy import select, func, text, or_
from app.models.distribution_inbox import DistributionInboxDevice as Device, DistributionInboxReceipt as Receipt
from app.models.user import User
from app.models.role import Role
from app.models.advisor_tenant_grant import AdvisorTenantGrant as Grant
from app.models.module_workspace import TenantModule, SeoSite, GeoProject
from app.models.seo import SeoSiteAdvisorAssignment, SeoContentAsset
from app.security.advisor_scope import is_advisor, account_locked
from app.security.distribution_inbox_auth import is_inbox_admin
from app.distribution_inbox_protocol import (fail, clean_text, validate_event, validate_revision,
    UNLABELED_ROWS, UNLABELED_BYTES, TOTAL_ROWS, TOTAL_BYTES)
from app.distribution_inbox_projection import personal_receipt, publication_receipt


def now():
    return datetime.now(timezone.utc)


def iso(value):
    return value.astimezone(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z') if value else None


def sha(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


async def schema_ready(session):
    for name in (Device.__tablename__, Receipt.__tablename__):
        if not await session.scalar(text('SELECT to_regclass(:name)'), {'name': name}):
            fail('INBOX_SCHEMA_NOT_READY', 503)


async def lock_people(session, *ids):
    # Stable order also covers administrator processing a departed owner's box.
    rows = list(await session.scalars(select(User).where(User.id.in_(set(ids))).order_by(User.id)
        .with_for_update().execution_options(populate_existing=True)))
    return {u.id: u for u in rows}


async def person(session, uid, *, locked=None):
    user = locked if locked is not None else await session.get(User, uid, populate_existing=True)
    if user is None or not user.is_active or account_locked(user):
        fail('INBOX_FORBIDDEN', 403)
    role = await session.scalar(select(Role).where(Role.id == user.role_id).with_for_update(read=True)
        .execution_options(populate_existing=True))
    if not is_inbox_admin(user, role) and not is_advisor(role):
        fail('INBOX_FORBIDDEN', 403)
    return user, role, is_inbox_admin(user, role)


async def actor(session, ctx, *, locked=None, identity=False):
    if ctx.user_id is None or ctx.is_superadmin:
        fail('INBOX_FORBIDDEN', 403)
    user, role, admin = await person(session, ctx.user_id, locked=locked)
    if not admin and (not ctx.is_advisor or ctx.scope_kind != ('advisor_identity' if identity else 'advisor_tenant')):
        fail('INBOX_FORBIDDEN', 403)
    if admin and ctx.scope_kind is not None:
        fail('INBOX_FORBIDDEN', 403)
    return user, role, admin


async def create_pairing(session, ctx, label):
    people = await lock_people(session, ctx.user_id)
    await actor(session, ctx, locked=people.get(ctx.user_id), identity=True)
    stamp = now()
    devices = list(await session.scalars(select(Device).where(Device.owner_user_id == ctx.user_id)))
    if sum(d.state == 'pending' and d.pairing_expires_at > stamp for d in devices) >= 20:
        fail('DEVICE_LIMIT_REACHED', 429)
    code = 'DHT2-' + secrets.token_urlsafe(24)
    row = Device(id=str(uuid4()), owner_user_id=ctx.user_id, label=label or '回传电脑', state='pending',
        revision=0, pairing_digest=sha(code), pairing_expires_at=stamp+timedelta(minutes=10),
        created_at=stamp, rate_buckets={})
    session.add(row)
    await session.flush()
    return {'schema': 2, 'pairingId': row.id, 'pairingCode': code, 'expiresAt': iso(row.pairing_expires_at), 'revision': 0}


async def claim(session, body):
    owner = await session.scalar(select(Device.owner_user_id).where(Device.pairing_digest == sha(body['pairingCode'])))
    if owner is None:
        fail('PAIRING_CODE_UNAVAILABLE', 409)
    people = await lock_people(session, owner)
    row = await session.scalar(select(Device).where(Device.pairing_digest == sha(body['pairingCode']))
        .with_for_update().execution_options(populate_existing=True))
    stamp = now()
    recent = [t for t in (row.rate_buckets or {}).get('claim', []) if t > stamp.timestamp()-60]
    if len(recent) >= 10:
        fail('RATE_LIMITED', 429)
    row.rate_buckets = {**(row.rate_buckets or {}), 'claim': [*recent, stamp.timestamp()]}
    session.info['inbox_claim_rate_changed'] = True
    try:
        user, _, _ = await person(session, owner, locked=people.get(owner))
    except Exception as exc:
        from app.distribution_inbox_protocol import ProtocolError
        if isinstance(exc, ProtocolError):
            fail('PAIRING_CODE_UNAVAILABLE', 409)
        raise
    if not row or row.state != 'pending' or row.pairing_expires_at <= stamp:
        fail('PAIRING_CODE_UNAVAILABLE', 409)
    if await session.scalar(select(func.count()).select_from(Device).where(Device.owner_user_id == owner,
            Device.state == 'active', Device.credential_expires_at > stamp)) >= 20:
        fail('DEVICE_LIMIT_REACHED', 429)
    credential = 'dht2_' + row.id + '.' + secrets.token_urlsafe(32)
    row.state, row.claim_request_id = 'active', body['requestId']
    row.credential_digest, row.credential_expires_at = sha(credential), stamp+timedelta(days=90)
    row.revision += 1
    return {'schema': 2, 'deviceId': row.id, 'credential': credential,
        'credentialExpiresAt': iso(row.credential_expires_at),
        'owner': {'displayName': user.display_name or user.username}, 'automaticSubmit': False}


async def authenticate_device(session, credential):
    match = re.fullmatch(r'dht2_([0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12})\.[A-Za-z0-9_-]{43}', credential)
    if not match:
        fail('DEVICE_CREDENTIAL_INVALID', 401)
    did = match.group(1)
    owner = await session.scalar(select(Device.owner_user_id).where(Device.id == did))
    if owner is None:
        fail('DEVICE_CREDENTIAL_INVALID', 401)
    people = await lock_people(session, owner)
    try:
        await person(session, owner, locked=people.get(owner))
    except Exception as exc:
        from app.distribution_inbox_protocol import ProtocolError
        if isinstance(exc, ProtocolError):
            fail('DEVICE_CREDENTIAL_INVALID', 401)
        raise
    row = await session.scalar(select(Device).where(Device.id == did).with_for_update().execution_options(populate_existing=True))
    if (row is None or row.state != 'active' or not row.credential_expires_at or row.credential_expires_at <= now()
            or not hmac.compare_digest(row.credential_digest or '', sha(credential))):
        fail('DEVICE_CREDENTIAL_INVALID', 401)
    return row


def ack(row):
    return {'schema': 2, 'eventId': row.event_id, 'deviceId': row.device_id, 'payloadDigest': row.payload_digest,
        'receiptId': row.id, 'receivedAt': iso(row.received_at)}


async def existing_ack(session, device, body):
    row = await session.scalar(select(Receipt).where(Receipt.device_id == device.id, Receipt.event_id == body.get('eventId')))
    if row:
        if row.payload_digest != body.get('payloadDigest'):
            fail('EVENT_DIGEST_CONFLICT', 409)
        return ack(row)


async def usage(session, owner):
    rows = list((await session.execute(select(Receipt.label_state, Receipt.state, Receipt.content_bytes, Receipt.history)
        .where(Receipt.owner_user_id == owner))).all())
    unlabeled = [r for r in rows if r.label_state != 'active' and r.state != 'deleted']
    return len(unlabeled), sum(r.content_bytes for r in unlabeled), len(rows), sum(r.content_bytes + len(json.dumps(r.history, ensure_ascii=False).encode('utf-8')) for r in rows)


async def receive(session, device, body, raw_size):
    previous = await existing_ack(session, device, body)
    if previous:
        return previous
    cleaned = validate_event(body)
    count, size, total, total_size = await usage(session, device.owner_user_id)
    if count >= UNLABELED_ROWS or size+raw_size > UNLABELED_BYTES or total >= TOTAL_ROWS or total_size+raw_size > TOTAL_BYTES:
        fail('INBOX_CAPACITY_EXCEEDED', 429)
    stamp = now()
    minute, hour = int(stamp.timestamp())//60, int(stamp.timestamp())//3600
    bucket = device.rate_buckets or {}
    per_minute = bucket.get('minuteCount', 0) if bucket.get('minute') == minute else 0
    all_buckets = list(await session.scalars(select(Device.rate_buckets).where(Device.owner_user_id == device.owner_user_id)))
    per_hour = sum(b.get('hourCount', 0) for b in all_buckets if b.get('hour') == hour)
    if per_minute >= 60 or per_hour >= 300:
        fail('RATE_LIMITED', 429)
    device.rate_buckets = {'minute': minute, 'minuteCount': per_minute+1, 'hour': hour,
        'hourCount': (bucket.get('hourCount', 0) if bucket.get('hour') == hour else 0)+1}
    cleaned.pop('platform_kind')
    row = Receipt(id=str(uuid4()), owner_user_id=device.owner_user_id, device_id=device.id,
        event_id=body['eventId'], attempt_id=body['attemptId'], payload_digest=body['payloadDigest'], received_at=stamp,
        result=body['result'], reason_code=body['reasonCode'], content_bytes=raw_size, state='pending', label_state='pending',
        revision=0, history=[], verification_status='unlinked', **cleaned)
    session.add(row)
    await session.flush()
    return ack(row)


async def mutate_device(session, ctx, did, revision, *, cancel=False):
    owner = await session.scalar(select(Device.owner_user_id).where(Device.id == did))
    if owner is None:
        fail('RECEIPT_NOT_FOUND', 404)
    people = await lock_people(session, ctx.user_id, owner)
    _, _, admin = await actor(session, ctx, locked=people.get(ctx.user_id), identity=True)
    if owner != ctx.user_id and not admin:
        fail('RECEIPT_NOT_FOUND', 404)
    row = await session.scalar(select(Device).where(Device.id == did).with_for_update().execution_options(populate_existing=True))
    if row.revision != revision:
        fail('REVISION_CONFLICT', 409)
    if cancel and row.state != 'pending':
        fail('PAIRING_CODE_UNAVAILABLE', 409)
    row.state, row.revision = 'revoked', row.revision+1
    return {'schema': 2, 'id': row.id, 'revision': row.revision, 'state': row.state}


async def target_allowed(session, uid, tenant, module, scope, *, write=False, ctx=None):
    """Fresh permissions and shared target reads; GEO writes stay in GEO.

    GEO assignment mirrors production-geo's geo_service_plan.advisor_user_id
    and geo_business_scope. No GEO runtime imports or HTTP credential forwarding.
    """
    user, role, admin = await person(session, uid)
    if write and (role.permissions or {}).get(module+'.content') != 'edit':
        return False
    if user.tenant_id is not None and admin and user.tenant_id != tenant:
        return False
    if not admin:
        if (role.permissions or {}).get(module+'.content') not in (('edit',) if write else ('view', 'edit')):
            return False
        grant_query = select(Grant).where(Grant.user_id == uid, Grant.tenant_id == tenant, Grant.revoked_at.is_(None))
        if write:
            grant_query = grant_query.with_for_update(read=True)
        grant = await session.scalar(grant_query.execution_options(populate_existing=True))
        if grant is None or (write and (ctx is None or ctx.grant_id != grant.id or ctx.tenant_id != tenant
                or not ctx.auth_exp or ctx.auth_exp <= now().timestamp())):
            return False
        # Existing business sessions require the legacy default to remain granted.
        if write and not await session.scalar(select(Grant.id).where(Grant.user_id == uid,
                Grant.tenant_id == user.tenant_id, Grant.revoked_at.is_(None)).with_for_update(read=True)):
            return False
    query = select(TenantModule).where(TenantModule.tenant_id == tenant, TenantModule.module_code == module)
    if write:
        query = query.with_for_update(read=True)
    row = await session.scalar(query.execution_options(populate_existing=True))
    if row is None or row.status not in {'active','trial'} or row.expires_at is not None and row.expires_at < date.today():
        return False
    if scope is not None:
        if module == 'geo':
            from app.models.geo_optimization import GeoOptimizationBusiness
            project = await session.scalar(select(GeoProject).where(GeoProject.id == scope,
                GeoProject.tenant_id == tenant, GeoProject.tenant_module_id == row.id, GeoProject.status == 'active')
                .execution_options(populate_existing=True))
            if project is None:
                return False
            settings = project.project_settings or {}
            plan, binding = settings.get('geo_service_plan') or {}, settings.get('geo_business_scope') or {}
            if not isinstance(plan, dict) or not isinstance(binding, dict):
                return False
            ids = binding.get('business_ids', [])
            if not isinstance(ids, list) or any(type(i) is not int or i < 1 for i in ids) or len(ids) != len(set(ids)):
                return False
            actual = set(await session.scalars(select(GeoOptimizationBusiness.id).where(
                GeoOptimizationBusiness.tenant_id == tenant, GeoOptimizationBusiness.id.in_(ids))))
            if actual != set(ids):
                return False
            return admin or (type(plan.get('advisor_user_id')) is int and plan['advisor_user_id'] == uid
                and (role.permissions or {}).get('geo.assets') == 'edit'
                and (role.permissions or {}).get('geo.content') == 'edit')
        if not admin:
            query = select(SeoSiteAdvisorAssignment).where(SeoSiteAdvisorAssignment.tenant_id == tenant,
                SeoSiteAdvisorAssignment.site_id == scope, SeoSiteAdvisorAssignment.advisor_user_id == uid,
                SeoSiteAdvisorAssignment.active.is_(True))
            if write:
                query = query.with_for_update(read=True)
            if await session.scalar(query.execution_options(populate_existing=True)) is None:
                return False
        query = select(SeoSite).where(SeoSite.id == scope, SeoSite.tenant_id == tenant, SeoSite.status == 'active',
            SeoSite.tenant_module_id == row.id)
        if write:
            query = query.with_for_update(read=True)
        if await session.scalar(query.execution_options(populate_existing=True)) is None:
            return False
    return True


def row_dict(row):
    values = {col.name: iso(v) if isinstance(v := getattr(row, col.name), datetime) else v for col in Receipt.__table__.columns}
    if row.state == 'pending' and row.received_at <= now()-timedelta(days=90):
        values['state'] = 'archived'
    return values


async def geo_article_options(session, tenant, project):
    """Only a read adapter. GEO rechecks this exact reference on every write."""
    from app.models.geo_content import GeoContentTask, GeoArticleVersion
    from app.models.geo_prompt import GeoPrompt
    from app.models.geo_optimization import GeoOptimizationUnit, GeoOptimizationBusiness
    binding = (project.project_settings or {}).get('geo_business_scope') or {}
    ids = binding.get('business_ids', [])
    if not ids:
        return []
    # A business referenced by multiple projects is not an unambiguous article
    # ownership grant. Do not expose titles via such stale bindings.
    projects = list(await session.scalars(select(GeoProject).where(GeoProject.tenant_id == tenant)))
    valid = [bid for bid in ids if sum(bid in (((p.project_settings or {}).get('geo_business_scope') or {}).get('business_ids') or []) for p in projects) == 1]
    tasks = list(await session.scalars(select(GeoContentTask).join(GeoPrompt, GeoContentTask.prompt_id == GeoPrompt.id)
        .join(GeoOptimizationUnit, GeoPrompt.unit_id == GeoOptimizationUnit.id)
        .join(GeoOptimizationBusiness, GeoOptimizationUnit.business_id == GeoOptimizationBusiness.id)
        .where(GeoContentTask.tenant_id == tenant, GeoPrompt.tenant_id == tenant, GeoOptimizationUnit.tenant_id == tenant,
            GeoOptimizationBusiness.tenant_id == tenant, GeoContentTask.business_id == GeoOptimizationBusiness.id,
            GeoOptimizationBusiness.id.in_(valid), GeoContentTask.review_status == 'approved')))
    items = []
    for task in tasks:
        master = await session.scalar(select(GeoArticleVersion).where(GeoArticleVersion.task_id == task.id,
            GeoArticleVersion.kind == 'master').order_by(GeoArticleVersion.version_no.desc(), GeoArticleVersion.id.desc()).limit(1))
        if master and master.body_markdown:
            items.append({'id': task.id, 'title': task.title, 'version': master.version_no, 'digest': sha(master.body_markdown)})
    return items


async def project(session, row, ctx, admin):
    visible = row.label_state == 'active' and await target_allowed(session, ctx.user_id, row.tenant_id, row.module, row.scope_id)
    duplicate = bool(row.url_hash and await session.scalar(select(Receipt.id).where(Receipt.owner_user_id == row.owner_user_id,
        Receipt.url_hash == row.url_hash, Receipt.id != row.id, Receipt.state != 'deleted').limit(1)))
    return personal_receipt(row_dict(row), actor_id=ctx.user_id, inbox_admin=admin,
        target_visible=bool(visible), own_duplicate=duplicate)


async def owned_receipt(session, ctx, rid, *, identity=False):
    owner = await session.scalar(select(Receipt.owner_user_id).where(Receipt.id == rid))
    if owner is None:
        fail('RECEIPT_NOT_FOUND', 404)
    people = await lock_people(session, ctx.user_id, owner)
    _, _, admin = await actor(session, ctx, locked=people.get(ctx.user_id), identity=identity)
    row = await session.scalar(select(Receipt).where(Receipt.id == rid).with_for_update().execution_options(populate_existing=True))
    if row is None or row.state == 'deleted' or row.owner_user_id != ctx.user_id and not admin:
        fail('RECEIPT_NOT_FOUND', 404)
    return row, admin


def revise(row, ctx, action, reason=None):
    # Keep metadata bounded without silently dropping history.
    if len(row.history) >= 512:
        fail('RATE_LIMITED', 429)
    row.revision += 1
    row.history = [*row.history, {'action': action, 'actor': ctx.user_id, 'at': iso(now()), 'revision': row.revision,
        'tenant': row.tenant_id, 'module': row.module, 'scope': row.scope_id, 'article': row.article_id,
        'reason': clean_text(reason, 200, nullable=True)}]


async def clean_receipt(session, ctx, rid, revision, action):
    row, _ = await owned_receipt(session, ctx, rid, identity=True)
    if row.revision != revision:
        fail('REVISION_CONFLICT', 409)
    if row.label_state == 'active':
        fail('INBOX_FORBIDDEN', 403)
    revise(row, ctx, action)
    if action == 'archive':
        row.state = 'archived'
    else:
        row.state, row.deleted_at, row.content_bytes = 'deleted', now(), 0
        for key in ('attempt_id','occurred_at','platform','title','reported_account','result','reason_code','public_url',
                'canonical_url','url_hash','normalizer_version','published_account','article_digest','article_version'):
            setattr(row, key, None)
    return {'schema': 2, 'id': row.id, 'revision': row.revision, 'state': row.state}


async def label(session, ctx, rid, body, tenant, *, unlabel=False):
    from app.config import get_settings
    row, admin = await owned_receipt(session, ctx, rid)
    if row.revision != body['expectedRevision']:
        fail('REVISION_CONFLICT', 409)
    if not admin and not get_settings().advisor_scoped_content_writes_enabled:
        fail('INBOX_FORBIDDEN', 403)
    if row.label_state == 'active' and (row.tenant_id != tenant or row.module != 'seo'):
        fail('CROSS_TARGET_REQUIRES_UNLABEL', 409)
    if unlabel and row.label_state != 'active':
        fail('REVISION_CONFLICT', 409)
    scope = row.scope_id if unlabel else body.get('scopeId')
    if not await target_allowed(session, ctx.user_id, tenant, 'seo', scope, write=True, ctx=ctx):
        fail('INBOX_FORBIDDEN', 403)
    if row.label_state == 'active' and not await target_allowed(session, ctx.user_id, tenant, 'seo', row.scope_id, write=True, ctx=ctx):
        fail('INBOX_FORBIDDEN', 403)
    if not unlabel and body.get('articleId') is not None:
        from app.api.seo import _content_confirmation_hash, _require_content_ready, _require_active_content_confirmation, _content_confirmation_schema_ready
        article = await session.scalar(select(SeoContentAsset).where(SeoContentAsset.id == body['articleId'],
            SeoContentAsset.tenant_id == tenant, SeoContentAsset.site_id == scope).with_for_update(read=True)
            .execution_options(populate_existing=True))
        if (article is None or article.version_count != body['articleVersion'] or _content_confirmation_hash(article) != body['articleDigest']):
            fail('REVISION_CONFLICT', 409)
        _require_content_ready(article)
        if not await _content_confirmation_schema_ready(session):
            fail('INBOX_SCHEMA_NOT_READY', 503)
        await _require_active_content_confirmation(session, article)
    if not unlabel and row.result == 'success' and row.url_hash:
        other = await session.scalar(select(Receipt).where(Receipt.id != row.id, Receipt.label_state == 'active',
            Receipt.result == 'success', Receipt.tenant_id == tenant, Receipt.module == 'seo',
            func.coalesce(Receipt.scope_id, 0) == (scope or 0), Receipt.url_hash == row.url_hash))
        if other:
            if other.canonical_url != row.canonical_url:
                fail('URL_HASH_COLLISION', 409)
            fail('DUPLICATE_LINK', 409)
    revise(row, ctx, 'unlabel' if unlabel else 'label', body.get('reason'))
    if unlabel:
        row.state, row.label_state = 'pending', 'revoked'
        row.tenant_id = row.module = row.scope_id = row.article_id = row.article_version = row.article_digest = row.published_account = None
    else:
        row.tenant_id, row.module, row.scope_id = tenant, 'seo', scope
        row.article_id, row.article_version, row.article_digest = body.get('articleId'), body.get('articleVersion'), body.get('articleDigest')
        row.published_account = clean_text(body.get('publishedAccount'), 60, nullable=True)
        row.state = row.label_state = 'active'
    row.verification_status = 'unavailable' if row.article_id else 'unlinked'
    row.history = [*row.history[:-1], {**row.history[-1], 'newTenant': row.tenant_id, 'newModule': row.module,
        'newScope': row.scope_id, 'newArticle': row.article_id}]
    await session.flush()
    return await project(session, row, ctx, admin)
