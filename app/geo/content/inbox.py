"""GEO projections over SEO-owned shared tables. Never creates native content."""
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import load_only

from app.distribution_inbox_protocol import fail, clean_text, UNLABELED_ROWS, UNLABELED_BYTES
from app.distribution_inbox_projection import personal_receipt, publication_receipt
from app.models import User
from app.models.distribution_inbox import DistributionInboxDevice as Device, DistributionInboxReceipt as Receipt
from app.geo.content.inbox_policy import fresh_actor, target_authorized


def timestamp(value):
    if value is None:
        return None
    return value.astimezone(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')


def row_values(row):
    value = {column.name: getattr(row, column.name) for column in Receipt.__table__.columns}
    for key in ('received_at', 'occurred_at'):
        value[key] = timestamp(value[key])
    return value


async def schema_ready(session):
    # Both tables must exist. Queries are read-only and never auto-create DDL.
    await session.scalar(select(Device.id).limit(1))
    await session.scalar(select(Receipt.id).limit(1))


async def locked_receipt(session, ctx, receipt_id):
    owner = await session.scalar(select(Receipt.owner_user_id).where(Receipt.id == receipt_id))
    if owner is None:
        fail('RECEIPT_NOT_FOUND', 404)
    # Shared mutation order: owner User -> receipt. No secret user columns.
    await session.scalars(select(User.id).where(User.id.in_({owner, ctx.user_id}))
        .order_by(User.id).with_for_update())
    actor = await fresh_actor(session, ctx, write=True)
    row = await session.scalar(select(Receipt).where(Receipt.id == receipt_id)
        .with_for_update().execution_options(populate_existing=True))
    if row is None or row.state == 'deleted' or (row.owner_user_id != ctx.user_id and not actor.admin):
        fail('RECEIPT_NOT_FOUND', 404)
    return actor, row


def history_entry(row, actor, action, reason):
    if len(row.history or []) >= 512:
        fail('RATE_LIMITED', 429)
    return {'action': action, 'at': timestamp(datetime.now(timezone.utc)),
            'actorId': actor.user.id, 'reason': clean_text(reason, 200, nullable=True),
            'previous': {'tenantId': row.tenant_id, 'module': row.module,
                         'scopeId': row.scope_id, 'articleId': row.article_id},
            'revision': row.revision}


async def label(session, ctx, receipt_id, tenant, data):
    actor, row = await locked_receipt(session, ctx, receipt_id)
    if row.label_state == 'active':
        if row.tenant_id != tenant or row.module != 'geo':
            fail('CROSS_TARGET_REQUIRES_UNLABEL', 409)
        await target_authorized(session, actor, tenant, row.scope_id)
    await target_authorized(session, actor, tenant, data.get('scopeId'),
        article=data if data.get('articleId') is not None else None)
    if row.revision != data['expectedRevision']:
        fail('REVISION_CONFLICT', 409)
    if row.result == 'success' and row.url_hash:
        duplicate = await session.scalar(select(Receipt).where(
            Receipt.id != row.id, Receipt.label_state == 'active', Receipt.result == 'success',
            Receipt.tenant_id == tenant, Receipt.module == 'geo',
            func.coalesce(Receipt.scope_id, 0) == (data.get('scopeId') or 0), Receipt.url_hash == row.url_hash).limit(1))
        if duplicate is not None:
            # No other row's identifiers, owner or target are disclosed.
            fail('DUPLICATE_LINK' if duplicate.canonical_url == row.canonical_url else 'URL_HASH_COLLISION', 409)
    row.history = [*(row.history or []), history_entry(row, actor, 'label', data.get('reason'))]
    row.tenant_id, row.module, row.scope_id = tenant, 'geo', data.get('scopeId')
    row.article_id, row.article_version, row.article_digest = (data.get(key) for key in ('articleId', 'articleVersion', 'articleDigest'))
    row.published_account = clean_text(data.get('publishedAccount'), 60, nullable=True)
    row.verification_status = 'unavailable' if row.article_id else 'unlinked'
    row.state = row.label_state = 'active'
    row.revision += 1
    await session.flush()
    # Recheck after the write, using held live authority/module/project locks.
    actor = await fresh_actor(session, ctx, write=True)
    await target_authorized(session, actor, tenant, row.scope_id,
        article=data if row.article_id is not None else None)
    return personal_receipt(row_values(row), actor_id=ctx.user_id, inbox_admin=actor.admin, target_visible=True)


async def unlabel(session, ctx, receipt_id, tenant, data):
    actor, row = await locked_receipt(session, ctx, receipt_id)
    if row.label_state != 'active' or row.module != 'geo' or row.tenant_id != tenant:
        fail('RECEIPT_NOT_FOUND', 404)
    await target_authorized(session, actor, tenant, row.scope_id)
    if row.revision != data['expectedRevision']:
        fail('REVISION_CONFLICT', 409)
    count, size = (await session.execute(select(func.count(Receipt.id), func.coalesce(func.sum(Receipt.content_bytes), 0)).where(
        Receipt.owner_user_id == row.owner_user_id, Receipt.state != 'deleted', Receipt.label_state != 'active'))).one()
    if count + 1 > UNLABELED_ROWS or size + row.content_bytes > UNLABELED_BYTES:
        fail('INBOX_CAPACITY_EXCEEDED', 429)
    row.history = [*(row.history or []), history_entry(row, actor, 'unlabel', data.get('reason'))]
    old_scope = row.scope_id
    row.tenant_id = row.module = row.scope_id = row.article_id = row.article_version = row.article_digest = row.published_account = None
    row.state, row.label_state, row.verification_status = 'pending', 'revoked', 'unlinked'
    row.revision += 1
    await session.flush()
    actor = await fresh_actor(session, ctx, write=True)
    await target_authorized(session, actor, tenant, old_scope)
    return personal_receipt(row_values(row), actor_id=ctx.user_id, inbox_admin=actor.admin)


async def publications(session, ctx, tenant, scope_id=None):
    actor = await fresh_actor(session, ctx)
    await target_authorized(session, actor, tenant, scope_id)
    query = select(Receipt).where(Receipt.tenant_id == tenant, Receipt.module == 'geo',
        Receipt.label_state == 'active', Receipt.state == 'active')
    if scope_id is not None:
        query = query.where(Receipt.scope_id == scope_id)
    rows = list(await session.scalars(query.order_by(Receipt.received_at.desc(), Receipt.id)))
    items, visible = [], set()
    for row in rows:
        if row.scope_id is None and row.owner_user_id != ctx.user_id and not actor.admin:
            continue
        if row.scope_id not in visible:
            try:
                await target_authorized(session, actor, tenant, row.scope_id)
            except HTTPException:
                continue
            except ValueError as error:
                from app.distribution_inbox_protocol import ProtocolError
                if not isinstance(error, ProtocolError):
                    raise
                continue
            visible.add(row.scope_id)
        items.append(publication_receipt(row_values(row), actor_id=ctx.user_id, expected_tenant=tenant,
            expected_module='geo', target_visible=True, inbox_admin=actor.admin))
    return {'schema': 2, 'items': items, 'total': len(items)}
