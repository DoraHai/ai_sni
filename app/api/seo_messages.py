"""Authenticated human text discussion scoped to one SEO article."""
from datetime import datetime, timezone
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, PositiveInt, field_validator
from sqlalchemy import select, func, text
from sqlalchemy.dialects.postgresql import insert
from app.seo_demo_source import get_seo_session as get_session, require_seo_scoped_auth as require_scoped_auth
from app.models.user import User
from app.models.module_workspace import SeoSite
from app.models.seo import SeoContentAsset, SeoSiteAdvisorAssignment
from app.models.seo_messages import SeoContentConversation as Conversation, SeoConversationParticipant as Participant, SeoContentMessage as Message
from app.module_scope import ensure_module_access, seo_site_is_operational

SCHEMA = "0106_seo_content_messages"
router = APIRouter(prefix="/workbench/content-assets/{content_id}/conversation", tags=["SEO human messages"])
Db = Depends(get_session)
Auth = Depends(require_scoped_auth)


def error(status, code, message):
    return HTTPException(status, {"code": code, "message": message})


class Scope(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tenant_id: PositiveInt
    site_id: PositiveInt


class Send(Scope):
    request_id: UUID
    body: str = Field(min_length=1, max_length=4000)

    @field_validator("body")
    @classmethod
    def nonempty(cls, value):
        if not value.strip() or "\x00" in value:
            raise ValueError("消息须为非空文本且不能包含NUL")
        return value


class Read(Scope):
    last_read_message_id: PositiveInt


async def scope(session, ctx, tenant_id, site_id, content_id, *, write=False):
    ctx.ensure_tenant(tenant_id)
    if ctx.user_id is None or not ctx.can_view("seo.content"):
        raise error(403, "conversation_forbidden", "需要获授权的实名客户或站点顾问")
    await ensure_module_access(session, ctx, tenant_id, "seo")
    revisions = list((await session.execute(text("SELECT version_num FROM alembic_version"))).scalars())
    if revisions != [SCHEMA]:
        raise error(503, "conversation_schema_unavailable", "站内沟通结构尚未就绪")
    # Shared locks keep account activation and assignment stable through this request.
    user = await session.scalar(select(User).where(User.id == ctx.user_id).with_for_update(read=True))
    if not user or not user.is_active or (user.tenant_id is not None and user.tenant_id != tenant_id):
        raise error(403, "conversation_forbidden", "账号无权参与当前会话")
    site = await session.get(SeoSite, site_id)
    content = await session.scalar(select(SeoContentAsset).where(SeoContentAsset.id == content_id,
        SeoContentAsset.tenant_id == tenant_id, SeoContentAsset.site_id == site_id).with_for_update(read=True))
    if not site or site.tenant_id != tenant_id or not content:
        raise error(404, "conversation_content_not_found", "当前客户网站下未找到稿件")
    assignments = list(await session.scalars(select(SeoSiteAdvisorAssignment).where(
        SeoSiteAdvisorAssignment.advisor_user_id == user.id).order_by(SeoSiteAdvisorAssignment.id)
        .with_for_update(read=True)))
    if ctx.can_edit("seo.content") or assignments:
        assignment = next((row for row in assignments if row.tenant_id == tenant_id and row.site_id == site_id), None)
        if not ctx.can_edit("seo.content") or not assignment or not assignment.active:
            raise error(403, "conversation_forbidden", "当前账号没有活动站点顾问分配")
        kind = "advisor"
    elif user.tenant_id == tenant_id and ctx.tenant_id == tenant_id:
        kind = "customer"
    else:
        raise error(403, "conversation_forbidden", "客户账号须绑定当前客户")
    operational = await seo_site_is_operational(session, tenant_id, site_id)
    if write and not operational:
        raise error(409, "conversation_site_inactive", "站点停用期间不能发送或更新已读")
    return {"id": user.id, "name": user.display_name or user.username, "kind": kind}, operational


async def conversation(session, tenant_id, site_id, content_id, *, create=False):
    if create:
        await session.execute(insert(Conversation).values(tenant_id=tenant_id, site_id=site_id,
            content_asset_id=content_id).on_conflict_do_nothing(index_elements=[Conversation.content_asset_id]))
    query = select(Conversation).where(Conversation.tenant_id == tenant_id, Conversation.site_id == site_id,
                                      Conversation.content_asset_id == content_id)
    return await session.scalar(query.with_for_update() if create else query)


async def participant(session, conv, user_id):
    await session.execute(insert(Participant).values(conversation_id=conv.id, user_id=user_id)
        .on_conflict_do_nothing(index_elements=[Participant.conversation_id, Participant.user_id]))
    return await session.get(Participant, (conv.id, user_id), populate_existing=True)


async def read_state(session, conv, user_id):
    if conv is None:
        return {"last_read_message_id": 0, "latest_message_id": None, "unread_count": 0}
    cursor = await session.scalar(select(Participant.last_read_message_id).where(
        Participant.conversation_id == conv.id, Participant.user_id == user_id)) or 0
    latest = await session.scalar(select(func.max(Message.id)).where(Message.conversation_id == conv.id))
    unread = await session.scalar(select(func.count()).select_from(Message).where(Message.conversation_id == conv.id,
        Message.id > cursor, Message.sender_user_id != user_id))
    return {"last_read_message_id": cursor, "latest_message_id": latest, "unread_count": int(unread or 0)}


def payload(row):
    return {"id": row.id, "conversation_id": row.conversation_id, "body": row.body,
        "sender": {"id": row.sender_user_id, "name": row.sender_name, "kind": row.sender_kind},
        "created_at": row.created_at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")}


@router.get("")
async def get_conversation(content_id: PositiveInt, tenant_id: PositiveInt, site_id: PositiveInt, session=Db, ctx=Auth):
    actor, operational = await scope(session, ctx, tenant_id, site_id, content_id)
    conv = await conversation(session, tenant_id, site_id, content_id)
    return {"scope": {"tenant_id": tenant_id, "site_id": site_id, "content_id": content_id},
        "conversation_id": conv.id if conv else None, "actor": actor,
        "allowed_actions": {"read": True, "send": operational, "mark_read": operational},
        "read_state": await read_state(session, conv, actor["id"]), "semantics": "human_messages_only"}


@router.get("/messages")
async def list_messages(content_id: PositiveInt, tenant_id: PositiveInt, site_id: PositiveInt,
        limit: int = Query(20, ge=1, le=100), before_id: PositiveInt | None = None, session=Db, ctx=Auth):
    actor, _ = await scope(session, ctx, tenant_id, site_id, content_id)
    conv = await conversation(session, tenant_id, site_id, content_id)
    rows = []
    if conv:
        query = select(Message).where(Message.conversation_id == conv.id)
        if before_id is not None:
            if not await session.scalar(select(Message.id).where(Message.conversation_id == conv.id, Message.id == before_id)):
                raise error(404, "conversation_cursor_not_found", "历史游标不属于当前会话")
            query = query.where(Message.id < before_id)
        rows = list(await session.scalars(query.order_by(Message.id.desc()).limit(limit + 1)))
    elif before_id is not None:
        raise error(404, "conversation_cursor_not_found", "当前会话没有该游标")
    more = len(rows) > limit
    rows = list(reversed(rows[:limit]))
    return {"conversation_id": conv.id if conv else None, "items": [payload(row) for row in rows],
        "has_more": more, "next_before_id": rows[0].id if more else None,
        "read_state": await read_state(session, conv, actor["id"])}


@router.post("/messages")
async def send_message(content_id: PositiveInt, req: Send, session=Db, ctx=Auth):
    actor, _ = await scope(session, ctx, req.tenant_id, req.site_id, content_id, write=True)
    conv = await conversation(session, req.tenant_id, req.site_id, content_id, create=True)
    if conv is None:
        raise error(409, "conversation_scope_conflict", "会话范围异常，不能发送")
    await participant(session, conv, actor["id"])
    existing = await session.scalar(select(Message).where(Message.conversation_id == conv.id,
        Message.sender_user_id == actor["id"], Message.request_id == req.request_id))
    if existing:
        if existing.body != req.body:
            raise error(409, "message_request_conflict", "此请求编号已用于另一条消息")
        result = {"message": payload(existing), "replayed": True}
    else:
        row = Message(conversation_id=conv.id, sender_user_id=actor["id"], sender_name=actor["name"],
            sender_kind=actor["kind"], request_id=req.request_id, body=req.body, created_at=datetime.now(timezone.utc))
        session.add(row)
        await session.flush()
        result = {"message": payload(row), "replayed": False}
    await session.commit()
    return result


@router.post("/read")
async def mark_read(content_id: PositiveInt, req: Read, session=Db, ctx=Auth):
    actor, _ = await scope(session, ctx, req.tenant_id, req.site_id, content_id, write=True)
    # Lock an existing conversation; marking read cannot create an empty one.
    conv = await session.scalar(select(Conversation).where(Conversation.tenant_id == req.tenant_id,
        Conversation.site_id == req.site_id, Conversation.content_asset_id == content_id).with_for_update())
    if conv is None or not await session.scalar(select(Message.id).where(
            Message.conversation_id == conv.id, Message.id == req.last_read_message_id)):
        raise error(404, "conversation_cursor_not_found", "已读位置不属于当前会话")
    reader = await participant(session, conv, actor["id"])
    reader.last_read_message_id = max(reader.last_read_message_id, req.last_read_message_id)
    await session.flush()
    result = {"conversation_id": conv.id, "read_state": await read_state(session, conv, actor["id"])}
    await session.commit()
    return result
