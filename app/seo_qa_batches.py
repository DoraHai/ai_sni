"""Persistent QA worker. Each tick handles one item; PostgreSQL owns the worker lock."""
from copy import deepcopy
from datetime import datetime, timezone
import logging
from fastapi import HTTPException
from sqlalchemy import select, text
from app.database import async_session_factory, engine
from app.models.seo_qa import SeoQaBatch
from app.models.user import User
from app.security.auth import AuthContext, _build_context

logger = logging.getLogger(__name__)
LOCK_ID = 736204091


async def current_actor(session, batch):
    if batch.actor == 'api_key':
        return AuthContext(None,'queued-api-key','api_key',None,{},True)
    user = await session.get(User, int(batch.actor))
    if user is None or not user.is_active:
        raise HTTPException(403,'创建批次的账号已停用')
    ctx = await _build_context(user,session)
    ctx.ensure_tenant(batch.tenant_id)
    if not ctx.can_edit('seo.content'):
        raise HTTPException(403,'创建批次的账号已失去内容编辑权限')
    return ctx


async def checkpoint(sessions,batch_id,index,**changes):
    async with sessions() as session:
        row = await session.scalar(select(SeoQaBatch).where(SeoQaBatch.id==batch_id).with_for_update())
        if row is None: return 'cancelled'
        items = deepcopy(row.items)
        items[index].update(changes)
        row.items = items
        remaining=any(i['state'] in ('pending','generating','saving') for i in items)
        if not remaining and row.status!='cancelled': row.status='completed'
        elif row.status not in ('paused','cancelled'): row.status='running'
        row.updated_at = datetime.now(timezone.utc)
        await session.commit()
        return row.status


async def process_next(sessions=async_session_factory):
    from app.api.seo_qa import DraftRequest, AnswerInput, generate_question_draft, create_answer, access
    async with sessions() as session:
        batch = await session.scalar(select(SeoQaBatch).where(SeoQaBatch.status.in_(['queued','running']))
            .order_by(SeoQaBatch.updated_at,SeoQaBatch.id).limit(1))
        if batch is None: return False
        index = next((n for n,i in enumerate(batch.items) if i['state'] in ('pending','generating','saving')),None)
        if index is None:
            batch.status='completed';await session.commit();return True
        batch_id=batch.id;item=deepcopy(batch.items[index]);tenant_id=batch.tenant_id;site_id=batch.site_id
    try:
        state=await checkpoint(sessions,batch_id,index,state='saving' if item['draft'] else 'generating',error=None)
        if state in ('paused','cancelled'): return True
        if not item['draft']:
            async with sessions() as session:
                batch=await session.get(SeoQaBatch,batch_id)
                ctx=await current_actor(session,batch)
                item['draft']=await generate_question_draft(DraftRequest(**item['request']),ctx,session)
            state=await checkpoint(sessions,batch_id,index,draft=item['draft'],state='saving')
            if state=='cancelled': return True
        async with sessions() as session:
            batch=await session.get(SeoQaBatch,batch_id)
            if batch.status=='cancelled': return True
            ctx=await current_actor(session,batch)
            await access(session,ctx,tenant_id,site_id,True)
            payload={k:v for k,v in item['draft'].items() if k not in ('action','operation_id')}
            saved=await create_answer(AnswerInput(tenant_id=tenant_id,site_id=site_id,**payload),ctx,session)
        await checkpoint(sessions,batch_id,index,state='done',answer_id=saved['id'],error=None)
    except Exception as exc:
        detail=exc.detail if isinstance(exc,HTTPException) else '后台执行异常，可重试本题；已生成的正文会保留'
        if isinstance(detail,dict) and detail.get('code')=='operation_running':
            await checkpoint(sessions,batch_id,index,state='pending',error=detail.get('message'))
        else:
            message=detail.get('message',str(detail)) if isinstance(detail,dict) else str(detail)
            await checkpoint(sessions,batch_id,index,state='failed',error=message[:1000])
            if not isinstance(exc,HTTPException): logger.exception('QA batch %s item %s failed',batch_id,index)
    return True


async def run_qa_batches():
    # Session advisory lock survives helper commits and is released on process death.
    async with engine.connect() as connection:
        locked=await connection.scalar(text('SELECT pg_try_advisory_lock(:key)'),{'key':LOCK_ID})
        if not locked: return
        try:
            await process_next()
        finally:
            await connection.rollback()
            await connection.execute(text('SELECT pg_advisory_unlock(:key)'),{'key':LOCK_ID})
            await connection.commit()
