"""Transactional in-app outbox; no email, webhook or customer messaging side effects."""
from uuid import uuid4

from fastapi import HTTPException


def record_transition(params, phase, waiting_for, now):
    events = [{**e} for e in params.get("notification_outbox") or []]
    for event in events:
        if event.get("state") == "available":
            event["state"] = "superseded"
    if waiting_for in {"advisor", "customer_or_advisor"}:
        events.append({"id": str(uuid4()), "phase": phase, "waiting_for": waiting_for,
            "blocker": params.get("blocker"), "created_at": now.isoformat(),
            "channel": "in_app", "state": "available", "seen_by": {}})
    params["notification_outbox"] = events[-50:]


def visible_events(task, ctx, site, advisor):
    result = []
    customer = ctx.user_id is not None and ctx.tenant_id == site.tenant_id and ctx.can_view("seo.content")
    for event in (task.params or {}).get("notification_outbox") or []:
        if event.get("state") != "available" or task.status not in {"open", "in_progress"}:
            continue
        if not advisor and not (customer and event.get("waiting_for") == "customer_or_advisor"):
            continue
        result.append({k: v for k, v in event.items() if k != "seen_by"} | {
            "task_id": task.id, "title": task.title, "read": str(ctx.user_id) in (event.get("seen_by") or {}),
            "overdue": bool((task.params or {}).get("attention_overdue")),
            "content_id": (task.params or {}).get("content_id")})
    return result


def acknowledge(task, ctx, site, advisor, event_id, now):
    if ctx.user_id is None:
        raise HTTPException(403, "标记已读需要实际登录用户")
    if event_id not in {e["id"] for e in visible_events(task, ctx, site, advisor)}:
        raise HTTPException(409, "提醒已变化或当前用户无权处理，请重新读取")
    events = [{**e} for e in task.params["notification_outbox"]]
    for event in events:
        if event["id"] == event_id:
            seen = dict(event.get("seen_by") or {})
            if str(ctx.user_id) not in seen:
                seen[str(ctx.user_id)] = now.isoformat()
            event["seen_by"] = seen
    task.params = {**task.params, "notification_outbox": events}
