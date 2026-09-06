"""Operator reconciliation of ambiguous deliveries; never sends content itself."""
from datetime import datetime, timezone, timedelta
from typing import Literal

from fastapi import HTTPException
from pydantic import BaseModel, Field

from app.geo.audit import safe_fetch, GeoAuditError
from app.geo.publication_evidence import match_publication
from app.geo.content.multi_push import delivery_key
from app.geo.content.review import assert_review_approved


class DeliveryResolution(BaseModel):
    tenant_id: int
    action: Literal['confirm_published', 'allow_retry']
    note: str = Field(min_length=10, max_length=1000)
    published_url: str | None = Field(default=None, max_length=2000)
    confirmed_not_published: bool = False


def delivery_items(variants):
    fields = ('state', 'account_id', 'mode', 'article_id', 'updated_at', 'reason', 'recovery_history')
    return [dict(variant_id=v.id, channel=v.channel, delivery_key=key,
                 **{f: entry.get(f) for f in fields})
            for v in variants
            for key, entry in ((v.adapt_meta or {}).get('push_deliveries') or {}).items()]


async def resolve_delivery(session, *, task, variant, account, key, req, user_id):
    from app.geo.content.routes import _latest_article, _write_publication
    if user_id is None:
        raise HTTPException(403, '需要已登录的操作人员核对，API Key 不能代替人工确认')
    if len(req.note.strip()) < 10:
        raise HTTPException(422, '请填写至少 10 字的核对说明')
    await session.refresh(task, with_for_update=True)
    await session.refresh(variant)
    if variant.task_id != task.id or account is None or account.tenant_id != task.tenant_id:
        raise HTTPException(404, '当前客户的发布记录不存在')
    journal = dict((variant.adapt_meta or {}).get('push_deliveries') or {})
    entry = journal.get(key)
    if not entry or entry.get('account_id') != account.id:
        raise HTTPException(404, '发布记录不存在')
    if entry.get('state') not in {'unknown', 'sending', 'failed'}:
        raise HTTPException(409, '记录已处理，请刷新后查看')
    if entry.get('state') == 'sending':
        try:
            started = datetime.fromisoformat(entry['updated_at'].replace('Z', '+00:00'))
            if started.tzinfo is None:
                started = started.replace(tzinfo=timezone.utc)
        except (ValueError, KeyError, TypeError):
            raise HTTPException(409, '发送时间无效，需要管理员排查')
        if datetime.now(timezone.utc) - started < timedelta(minutes=10):
            raise HTTPException(409, '发送请求仍可能在执行，请至少等待 10 分钟后再核对')
    article = await _latest_article(session, task.id)
    if (article is None or article.id != variant.article_version_id
            or entry.get('article_id') != article.id
            or delivery_key(task, variant, account, entry.get('mode')) != key):
        raise HTTPException(409, '稿件版本已经变化，不能用当前稿件核销历史发送')
    try:
        assert_review_approved(task)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    history = list(entry.get('recovery_history') or [])
    if len(history) >= 100:
        raise HTTPException(409, '恢复操作次数已达上限，需要管理员排查')
    now = datetime.now(timezone.utc).isoformat()
    event = dict(action=req.action, user_id=user_id, note=req.note.strip(), at=now,
                 previous_state=entry['state'])
    if req.action == 'confirm_published':
        url = (req.published_url or '').strip()
        if entry.get('mode') != 'publish' or not url.startswith('https://'):
            raise HTTPException(422, '仅发布操作可核实上线，请填写 https 发布链接')
        try:
            document = await safe_fetch(url)
        except GeoAuditError as exc:
            raise HTTPException(409, '发布页抓取失败，尚不能核实上线') from exc
        await session.refresh(variant)
        latest = await _latest_article(session, task.id)
        if (latest is None or latest.id != article.id
                or delivery_key(task, variant, account, entry.get('mode')) != key):
            raise HTTPException(409, '核验期间稿件变化，请重新核对')
        evidence = match_publication(variant.title, variant.body_markdown, document.html)
        now = datetime.now(timezone.utc).isoformat()
        event['at'] = now
        event['evidence'] = dict(evidence, url=document.final_url, verified_at=now)
        await _write_publication(session, task=task, variant=variant, channel=variant.channel,
                                 published_url=document.final_url, note=req.note.strip(), publish_mode='auto_publish')
        updated = dict(entry, state='succeeded', result=dict(ok=True, mode='publish',
                       account_id=account.id, remote_url=document.final_url, reconciled=True))
    else:
        if not req.confirmed_not_published:
            raise HTTPException(422, '请先核对渠道后台，确认没有生成对应文章或草稿')
        updated = dict(entry, state='failed', reason='operator_confirmed_not_published')
    journal[key] = dict(updated, updated_at=now, recovery_history=[*history, event])
    variant.adapt_meta = {**(variant.adapt_meta or {}), 'push_deliveries': journal}
    await session.commit()
    return {'ok': True, 'state': journal[key]['state'], 'action': req.action}
