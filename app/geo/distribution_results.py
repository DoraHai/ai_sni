"""Adopt verified results and read scoped native public-text monitor summaries.

This is a trusted server adapter, not an HTTP body/approval write API. Callers
own the transaction. Public-page monitoring remains a separate observation;
neither human nor machine registration implies AI citation or visibility.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.geo.content.routes import _write_publication
from app.geo.distribution_sources import PLATFORM_CHANNELS, authorize_scope, load_source
from app.geo.project_scope import project_scope, prompt_ids_for_businesses
from app.geo.publication_monitor import initial_state, state_for, store_state
from app.models import GeoChannelVariant, GeoContentTask, GeoMediaPlacement, GeoPublication

_FIELDS = frozenset({"event_id", "task_id", "source_revision", "content_digest",
    "platform", "public_url", "reported_at", "verification", "verified_at", "verified_by"})

_MONITOR_STATES = frozenset({"not_queued", "pending", "running", "observed", "failed",
    "unreachable", "mismatch", "version_changed", "unavailable"})


def _monitor_view(publication_id: int, state: str, observed_at=None, next_check_at=None) -> dict:
    # Native publication_monitor does not persist a reliable observation source
    # or independent evidence ID. publish_mode is a publishing mechanism, not
    # evidence provenance; never infer manual/auto from it or arbitrary JSON.
    return {"module": "geo", "publication_id": publication_id, "basis": "public-text",
        "state": state, "evidence_source": "none", "observed_at": observed_at,
        "next_check_at": next_check_at, "evidence_id": None,
        "code": "GEO_MONITOR_" + state.upper()}


def _monitor_forbidden() -> HTTPException:
    return HTTPException(403, {"code": "GEO_MONITOR_SCOPE_FORBIDDEN",
        "message": "当前账号无权读取该项目的发布监测记录"})


def _monitor_milliseconds(value) -> int | None:
    if value is None:
        return None
    if not isinstance(value, str) or not 1 <= len(value) <= 64 or not value.isascii():
        raise ValueError("Invalid monitor timestamp")
    parsed = datetime.fromisoformat(value.removesuffix("Z") + ("+00:00" if value.endswith("Z") else ""))
    if parsed.tzinfo is None:
        raise ValueError("Monitor timestamp requires timezone")
    stamp = int(parsed.astimezone(timezone.utc).timestamp() * 1000)
    if not 0 <= stamp <= 4_102_444_800_000:
        raise ValueError("Invalid monitor timestamp")
    return stamp


def _stored_monitor_view(publication_id: int, metadata) -> dict:
    absent = _monitor_view(publication_id, "not_queued")
    if metadata is None:
        return absent
    if not isinstance(metadata, dict):
        raise ValueError("Invalid monitor container")
    if "publication_monitor" not in metadata:
        return absent
    entries = metadata["publication_monitor"]
    if not isinstance(entries, dict):
        raise ValueError("Invalid monitor entries")
    if str(publication_id) not in entries:
        return absent
    entry = entries[str(publication_id)]
    if not isinstance(entry, dict) or not isinstance(entry.get("state"), str):
        raise ValueError("Invalid monitor entry")
    state = "observed" if entry["state"] == "healthy" else entry["state"]
    if state not in _MONITOR_STATES:
        raise ValueError("Invalid GEO monitor state")
    observed_at = _monitor_milliseconds(entry.get("checked_at"))
    next_check_at = _monitor_milliseconds(entry.get("next_check_at"))
    if state == "observed" and observed_at is None:
        raise ValueError("A public-text observation requires its actual timestamp")
    return _monitor_view(publication_id, state, observed_at, next_check_at)


async def publication_monitor_status(session: AsyncSession, actor_user_id: int,
    tenant_id: int, scope_id: int, publication_id: int) -> dict:
    """Read current native public-text monitor state, without fetch or writes.

    Historical body/review revisions do not block this scoped history read.
    Authorization still uses the current native advisor/tenant/project gates.
    """
    if any(type(value) is not int or value <= 0
           for value in (actor_user_id, tenant_id, scope_id, publication_id)):
        raise _monitor_forbidden()
    unavailable = _monitor_view(publication_id, "unavailable")
    try:
        # A connection savepoint isolates missing DB structures without flushing
        # caller-owned pending ORM objects (Session.begin_nested would flush).
        with session.no_autoflush:
            connection = await session.connection()
            async with connection.begin_nested():
                await authorize_scope(session, actor_user_id, tenant_id, scope_id)
                _project, business_ids = await project_scope(session, tenant_id, scope_id)
                row = (await session.execute(select(
                    GeoPublication.variant_id.label("pub_variant_id"),
                    GeoChannelVariant.id.label("variant_id"),
                    GeoChannelVariant.task_id.label("variant_task_id"),
                    GeoChannelVariant.adapt_meta.label("metadata"),
                    GeoContentTask.id.label("task_id"), GeoContentTask.tenant_id,
                    GeoContentTask.business_id, GeoContentTask.prompt_id)
                    .select_from(GeoPublication)
                    .join(GeoChannelVariant, GeoChannelVariant.id == GeoPublication.variant_id)
                    .join(GeoContentTask, GeoContentTask.id == GeoChannelVariant.task_id)
                    .where(GeoPublication.id == publication_id))).mappings().first()
                if row is None:
                    raise _monitor_forbidden()
                prompt_ids = await prompt_ids_for_businesses(session, tenant_id, business_ids)
                if (row["tenant_id"] != tenant_id or row["business_id"] not in business_ids
                    or row["prompt_id"] not in prompt_ids or row["pub_variant_id"] != row["variant_id"]
                    or row["variant_task_id"] != row["task_id"]):
                    raise _monitor_forbidden()
                return _stored_monitor_view(publication_id, row["metadata"])
    except HTTPException as exc:
        # Scope adapters also use 404/409 for invalid or foreign bindings. This
        # history projection deliberately exposes only an authorization denial.
        if exc.status_code == 401:
            raise
        if exc.status_code in {403, 404, 409}:
            raise _monitor_forbidden() from exc
        return unavailable
    except (SQLAlchemyError, AttributeError, KeyError, TypeError, ValueError, OverflowError, OSError):
        return unavailable


def _problem(code: str, status: int = 409) -> HTTPException:
    return HTTPException(status, {"code": code, "message": {
        "geo_distribution_result_invalid": "发布核验结果格式无效",
        "geo_distribution_result_source_changed": "稿件或审核版本已变化，不能登记该发布结果",
        "geo_distribution_result_conflict": "同一分发任务或核验事件已有不同的发布结果",
        "geo_distribution_result_identity_mismatch": "核验人必须是当前实名顾问",
        "geo_distribution_result_record_changed": "原生发布记录已变化，请人工核查",
    }[code]})


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False)


def content_digest(content: dict) -> str:
    """Exactly the broker's ordered approved-content tuple, including assets."""
    value = [content["version"], content["title"], content["body"], [
        [a["id"], a["sha256"], a["mediaType"], a["bytes"]] for a in content["assets"]]]
    return hashlib.sha256(json.dumps(value, ensure_ascii=False,
        separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def _content_identity(content: dict) -> str:
    # Native publication/monitor bookkeeping updates variant.updated_at. Keep
    # replay checks sensitive to text/images while ignoring that bookkeeping.
    return hashlib.sha256(_canonical({k: content[k] for k in ("title", "body", "assets")}).encode()).hexdigest()


def _validate(payload: dict, actor_user_id: int) -> dict:
    try:
        if not isinstance(payload, dict) or set(payload) != _FIELDS:
            raise ValueError()
        value = dict(payload)
        for key in ("event_id", "task_id"):
            if not isinstance(value[key], str):
                raise ValueError()
            value[key] = str(UUID(value[key]))
        for key in ("source_revision", "content_digest", "platform", "public_url", "verification"):
            if not isinstance(value[key], str):
                raise ValueError()
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", value["source_revision"]):
            raise ValueError()
        if not re.fullmatch(r"[a-f0-9]{64}", value["content_digest"]):
            raise ValueError()
        if value["platform"] not in PLATFORM_CHANNELS or value["verification"] not in {"human-verified", "machine-verified"}:
            raise ValueError()
        for key in ("reported_at", "verified_at"):
            if type(value[key]) is not int or not 946684800000 <= value[key] <= 4102444800000:
                raise ValueError()
        if value["verified_at"] < value["reported_at"] or type(value["verified_by"]) is not int or value["verified_by"] <= 0:
            raise ValueError()
        raw = value["public_url"]
        if len(raw) > 2000 or any(ord(ch) <= 32 for ch in raw):
            raise ValueError()
        parsed = urlsplit(raw)
        host = "mp.weixin.qq.com" if value["platform"] == "wechat-article" else "www.xiaohongshu.com"
        pattern = r"/s/[A-Za-z0-9_-]+" if value["platform"] == "wechat-article" else r"/explore/[a-f0-9]+"
        if parsed.scheme != "https" or parsed.netloc != host or not re.fullmatch(pattern, parsed.path):
            raise ValueError()
        if raw != urlunsplit(("https", host, parsed.path, "", "")):
            raise ValueError()
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise _problem("geo_distribution_result_invalid", 422) from exc
    if value["verified_by"] != actor_user_id:
        raise _problem("geo_distribution_result_identity_mismatch", 403)
    return value


def _return(record: dict, verification: str, idempotent: bool, monitor_state: str) -> dict:
    return {"module": "geo", "publication_id": int(record["publication_id"]),
        "placement_id": int(record["placement_id"]), "monitor_state": monitor_state,
        "verification": verification, "idempotent": idempotent}


async def record_publication(session: AsyncSession, actor_user_id: int,
    tenant_id: int, scope_id: int, variant_id: int, publication: dict) -> dict:
    """Adopt one verified result; never commit or fetch an external URL here."""
    # A caller may catch a failed adapter and persist the broker's retry state.
    # Savepoints ensure such a commit cannot leak a partial native publication.
    async with session.begin_nested():
        return await _record_publication(session, actor_user_id, tenant_id,
            scope_id, variant_id, publication)


async def _record_publication(session: AsyncSession, actor_user_id: int,
    tenant_id: int, scope_id: int, variant_id: int, publication: dict) -> dict:
    value = _validate(publication, actor_user_id)
    # Reauthorize even an idempotent repeat: current tenant/service, project,
    # advisor assignment, role, current mother/channel稿 and client review.
    source = await load_source(session, actor_user_id, tenant_id, scope_id,
        variant_id, value["platform"])
    variant = await session.get(GeoChannelVariant, variant_id)
    task = await session.get(GeoContentTask, int(variant.task_id))
    # Fixed advisory key order also serializes duplicate UUIDs across different
    # native tasks, where the native task locks alone would not be sufficient.
    keys = sorted(("geo-distribution-event:" + value["event_id"],
        "geo-distribution-task:" + value["task_id"],
        f"geo-distribution-placement:{tenant_id}:{task.prompt_id}:{value['public_url']}"))
    for key in keys:
        await session.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"), {"key": key})
    identity = {"tenant_id": tenant_id, "scope_id": scope_id, "variant_id": variant_id,
        **{k: value[k] for k in ("task_id", "source_revision", "content_digest", "platform", "public_url")}}
    identity_hash = hashlib.sha256(_canonical(identity).encode()).hexdigest()
    payload_hash = hashlib.sha256(_canonical(value).encode()).hexdigest()
    event = (await session.execute(text("SELECT * FROM geo_distribution_publication_events WHERE event_id=CAST(:id AS uuid)"),
        {"id": value["event_id"]})).mappings().first()
    if event is not None and (str(event["task_id"]) != value["task_id"] or event["payload_sha256"] != payload_hash):
        raise _problem("geo_distribution_result_conflict")
    existing = (await session.execute(text("SELECT * FROM geo_distribution_publications WHERE task_id=CAST(:id AS uuid)"),
        {"id": value["task_id"]})).mappings().first()
    created = existing is None
    if existing is not None:
        if existing["identity_sha256"] != identity_hash:
            raise _problem("geo_distribution_result_conflict")
        if existing["content_identity_sha256"] != _content_identity(source["content"]):
            raise _problem("geo_distribution_result_source_changed")
        pub = await session.get(GeoPublication, int(existing["publication_id"]), populate_existing=True)
        placement = await session.get(GeoMediaPlacement, int(existing["placement_id"]), populate_existing=True)
        if (pub is None or pub.variant_id != variant_id or pub.published_url != value["public_url"]
            or pub.status != "published" or placement is None or placement.tenant_id != tenant_id
            or placement.published_url != value["public_url"] or placement.status != "published"):
            raise _problem("geo_distribution_result_record_changed")
        record = dict(existing)
    else:
        if source["source_revision"] != value["source_revision"] or content_digest(source["content"]) != value["content_digest"]:
            raise _problem("geo_distribution_result_source_changed")
        await _write_publication(session, task=task, variant=variant,
            channel=PLATFORM_CHANNELS[value["platform"]], published_url=value["public_url"],
            note=f"分发任务 {value['task_id']}；{value['verification']}；登记时间不代表平台首次发布时间；AI 引用尚未评估",
            publish_mode="manual_export", published_at=datetime.fromtimestamp(value["reported_at"] / 1000, timezone.utc).replace(tzinfo=None))
        pub = await session.scalar(select(GeoPublication).where(
            GeoPublication.variant_id == variant_id, GeoPublication.published_url == value["public_url"])
            .order_by(GeoPublication.id).limit(1).execution_options(populate_existing=True))
        placement = await session.scalar(select(GeoMediaPlacement).where(
            GeoMediaPlacement.tenant_id == tenant_id, GeoMediaPlacement.related_prompt_id == task.prompt_id,
            GeoMediaPlacement.published_url == value["public_url"]).order_by(GeoMediaPlacement.id).limit(1).with_for_update())
        if placement is None:
            placement = GeoMediaPlacement(tenant_id=tenant_id, name=source["content"]["title"][:200],
                channel_type="social", channel_key=PLATFORM_CHANNELS[value["platform"]],
                target_url=value["public_url"], published_url=value["public_url"], status="published",
                authority_note="经分发结果核验登记；权威度与 AI 引用尚未评估", related_prompt_id=task.prompt_id,
                created_by=actor_user_id, priority=0)
            session.add(placement)
        elif placement.status != "published":
            raise _problem("geo_distribution_result_record_changed")
        if not state_for(variant, pub):
            store_state(variant, pub, {**initial_state(variant), "baseline_source": "distribution_result_registration"})
        await session.flush()
        record = {**identity, "publication_id": int(pub.id), "placement_id": int(placement.id),
            "identity_sha256": identity_hash, "content_identity_sha256": _content_identity(source["content"])}
        await session.execute(text("""INSERT INTO geo_distribution_publications
            (task_id,tenant_id,scope_id,variant_id,source_revision,content_digest,platform,public_url,
             publication_id,placement_id,identity_sha256,content_identity_sha256)
            VALUES (CAST(:task_id AS uuid),:tenant_id,:scope_id,:variant_id,:source_revision,:content_digest,
             :platform,:public_url,:publication_id,:placement_id,:identity_sha256,:content_identity_sha256)"""), record)
    if event is None:
        await session.execute(text("""INSERT INTO geo_distribution_publication_events
            (event_id,task_id,verification,verified_at,verified_by,reported_at,payload_sha256)
            VALUES (CAST(:event_id AS uuid),CAST(:task_id AS uuid),:verification,:verified_at,:verified_by,:reported_at,:payload_sha256)"""),
            {**value, "payload_sha256": payload_hash})
    return _return(record, value["verification"], not created, state_for(variant, pub).get("state", "pending"))
