"""Bounded UTF-8 receipts; preview and confirmation share the same validation."""
from __future__ import annotations

import csv
import io
import json
import re
from datetime import datetime, timezone
from urllib.parse import urlsplit, urlunsplit

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.geo.content.gate import PublishGateError
from app.geo.content.backfill import CHANNEL_ALIASES, resolve_backfill_source
from app.geo.project_scope import project_scope, prompt_ids_for_businesses
from app.models import GeoContentTask, GeoChannelVariant, GeoPublication, GeoPublishingChannel

MAX_BYTES = 2 * 1024 * 1024
MAX_ROWS = 200
FIELDS = {"article_id", "platform", "channel_name", "public_url", "published_at", "note", "variant_id",
          "tenant_id", "project_id", "status"}
SCOPE_ERROR = "这条回执不属于当前客户、项目或文章，请核对后重试"


def parse_receipts(data: bytes, filename: str) -> list:
    if len(data) > MAX_BYTES:
        raise ValueError("文件太大，请控制在 2 MB 以内")
    try:
        source = data.decode("utf-8-sig")
        if filename.lower().endswith(".json"):
            try:
                rows = json.loads(source)
            except (ValueError, RecursionError):
                raise ValueError("文件读不懂，请使用 UTF-8 编码的 JSON 模板") from None
        elif filename.lower().endswith(".csv"):
            reader = csv.DictReader(io.StringIO(source, newline=""), strict=True)
            headers = reader.fieldnames or []
            if (len(headers) != len(set(headers)) or not {"article_id", "platform", "public_url"} <= set(headers)
                    or not set(headers) <= FIELDS):
                raise ValueError("表头不符合 GEO 回执格式，请下载本页模板填写")
            rows = []
            for row in reader:
                if None in row or any(v is None for v in row.values()):
                    raise ValueError("表格有缺列或多列，请按模板检查")
                rows.append(row)
                if len(rows) > MAX_ROWS:
                    raise ValueError("每次只能导入 1 至 200 行，请分批上传")
        else:
            raise ValueError("请选择 CSV 或 JSON 回执文件")
    except (UnicodeError, json.JSONDecodeError, csv.Error, RecursionError):
        raise ValueError("文件读不懂，请使用 UTF-8 编码的 CSV 或 JSON 模板") from None
    if not isinstance(rows, list) or not 1 <= len(rows) <= MAX_ROWS:
        raise ValueError("每次只能导入 1 至 200 行，请分批上传")
    return rows


def positive_id(value):
    if type(value) not in (str, int) or not re.fullmatch(r"[1-9][0-9]{0,18}", str(value)):
        raise ValueError(SCOPE_ERROR)
    result = int(value)
    if result > 9223372036854775807:
        raise ValueError(SCOPE_ERROR)
    return result


def https_url(value):
    if not isinstance(value, str) or not 8 <= len(value) <= 2000:
        raise ValueError("请填写完整的 https:// 发布链接（最多 2000 个字）")
    try:
        parsed = urlsplit(value)
        if (not value.startswith("https://") or not parsed.hostname or parsed.username is not None
                or parsed.password is not None or re.search(r"[\s\\\x00-\x1f\x7f]", value)):
            raise ValueError()
        port = parsed.port
        if port == 0:
            raise ValueError()
    except ValueError:
        raise ValueError("发布链接必须以 https:// 开头，且不能包含空格或账号信息") from None
    host = parsed.hostname.lower()
    if ":" in host:
        host = f"[{host}]"
    netloc = host + (f":{port}" if port and port != 443 else "")
    # Preserve query strings: some publishing platforms identify an article there.
    key = urlunsplit(("https", netloc, parsed.path or "/", parsed.query, ""))
    return value, key


def published_time(value):
    if value in (None, ""):
        return None
    try:
        if not isinstance(value, str) or not re.fullmatch(
                r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,6})?(?:Z|[+-]\d\d:\d\d)", value):
            raise ValueError()
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.astimezone(timezone.utc).replace(tzinfo=None)
    except (ValueError, OverflowError):
        raise ValueError("发布时间请按模板填写，并带上时区；不确定可留空") from None


async def import_receipts(session, *, ctx, tenant_id, project_id, task_id, rows, dry_run):
    from app.geo.content import routes

    ctx.ensure_tenant(tenant_id)
    if not ctx.can_edit("geo.content"):
        raise HTTPException(403, "当前账号不能回填发布链接")
    # Entitlement takes the tenant lock, also used by project binding changes.
    await routes.ensure_geo_entitlement(session, tenant_id)
    _, businesses = await project_scope(session, tenant_id, project_id)
    prompts = await prompt_ids_for_businesses(session, tenant_id, businesses)
    task = await session.scalar(select(GeoContentTask).where(
        GeoContentTask.id == task_id, GeoContentTask.tenant_id == tenant_id,
        GeoContentTask.prompt_id.in_(prompts),
        (GeoContentTask.business_id.in_(businesses) | GeoContentTask.business_id.is_(None)),
    ).with_for_update().execution_options(populate_existing=True))
    if task is None:
        raise HTTPException(404, SCOPE_ERROR)
    variants = await routes._variants(session, task.id, fresh=True)
    by_channel = {v.channel: v for v in variants}
    by_id = {v.id: v for v in variants}
    article = await routes._latest_article(session, task.id, fresh=True)
    gate_reason = ""
    if task.review_status != "approved":
        gate_reason = "这篇文章还没通过客户审核，整批不能导入，请先完成审核"
    else:
        rule_input = await routes._build_rule_input(session, task, article, fresh=True, refresh_citations=False)
        tenant = await routes._ensure_tenant_exists(session, tenant_id, fresh=True)
        brand, _ = await routes._brand_context_for_task(session, task, tenant, fresh=True)
        try:
            routes.assert_can_publish(rule_input, task=task, brand=brand)
        except PublishGateError:
            gate_reason = "这篇文章还没达到发布要求，请回编辑器检查后重新预览"
    # Read registry only: preview must never seed defaults or write anything.
    registry = routes.registry_row_dicts(list(await session.scalars(select(GeoPublishingChannel).where(
        GeoPublishingChannel.tenant_id == tenant_id))))
    aliases = {alias: {channel} for alias, channel in CHANNEL_ALIASES.items()}
    for channel, variant in by_channel.items():
        aliases.setdefault(channel, set()).add(channel)
        profile = routes.get_profile(channel)
        if profile:
            aliases.setdefault(profile.display_name, set()).add(channel)
    # Keep names of existing channel drafts compatible; never guess unknown names.
    for item in registry:
        if item.get("channel_type") in by_channel and item.get("name"):
            aliases.setdefault(item["name"], set()).add(item["channel_type"])
    existing = list(await session.scalars(select(GeoPublication).join(
        GeoChannelVariant, GeoChannelVariant.id == GeoPublication.variant_id).join(
        GeoContentTask, GeoContentTask.id == GeoChannelVariant.task_id).where(
        GeoContentTask.tenant_id == tenant_id)))
    existing_urls, existing_records = set(), {}
    for publication in existing:
        try:
            key = https_url(publication.published_url)[1]
            existing_urls.add(key)
        except ValueError:
            key = publication.published_url
        existing_records.setdefault((publication.variant_id, publication.channel), set()).add(key)
    results, pending, seen_urls, seen_records = [], [], set(), {}
    for index, row in enumerate(rows, 1):
        item = {"row_number": index, "platform": "—", "public_url": "", "status": "不能导入", "reason": ""}
        try:
            if not isinstance(row, dict) or not set(row) <= FIELDS:
                raise ValueError("这一行字段不符合 GEO 回执模板，请按模板填写")
            if positive_id(row.get("article_id")) != task_id:
                raise ValueError(SCOPE_ERROR)
            for key, expected in (("tenant_id", tenant_id), ("project_id", project_id)):
                if row.get(key) not in (None, "") and positive_id(row[key]) != expected:
                    raise ValueError(SCOPE_ERROR)
            platform = row.get("platform")
            if not isinstance(platform, str) or not platform or len(platform) > 120:
                raise ValueError("请按模板填写渠道名称或代码；自定义渠道请填“其他”，并在 channel_name 列填写名称")
            item["platform"] = platform
            candidates = aliases.get(platform, set())
            if len(candidates) != 1:
                raise ValueError("认不出这个渠道，请按模板填写渠道名称或代码；自定义渠道请填“其他”，并在 channel_name 列填写名称")
            channel = next(iter(candidates))
            source_id = None
            if row.get("variant_id") not in (None, ""):
                source_id = positive_id(row["variant_id"])
                if source_id not in by_id:
                    raise ValueError(SCOPE_ERROR)
            if channel != "other" and row.get("channel_name") not in (None, ""):
                raise ValueError("只有“其他”渠道需要填写 channel_name 列，请核对渠道")
            variant, destination, channel_name = resolve_backfill_source(
                channel=channel, custom_channel_name=row.get("channel_name"),
                source_variant_id=source_id, variants=variants,
            )
            if channel_name:
                item["platform"] = f"其他：{channel_name}"
            if article is None or variant.article_version_id != article.id:
                raise ValueError("这条渠道稿已落后母稿，请重新生成并审核")
            url, url_key = https_url(row.get("public_url"))
            item["public_url"] = url
            when = published_time(row.get("published_at"))
            note = row.get("note") or None
            if note is not None and (not isinstance(note, str) or len(note) > 1000):
                raise ValueError("备注最多填写 1000 个字")
            if row.get("status") not in (None, "", "published"):
                raise ValueError("只有已发布的回执能回填链接；未发布或结果不确定的请先核实")
            if gate_reason:
                raise ValueError(gate_reason)
            record_key = (variant.id, destination)
            if record_key in seen_records and seen_records[record_key] != url_key:
                raise ValueError("同一条渠道记录填了不同链接，请核对后只保留一条")
            if record_key in existing_records and url_key not in existing_records[record_key]:
                raise ValueError("这条渠道记录已有其他发布链接，请核对；导入不会覆盖原记录")
            if url_key in existing_urls or url_key in seen_urls or record_key in seen_records:
                item.update(status="无需导入", reason="这条链接或渠道记录已经登记，重复行会跳过")
            else:
                item.update(status="能导入", reason="核对通过，确认后回填")
                pending.append((item, variant, channel, destination, channel_name, url, note, when))
            seen_urls.add(url_key)
            seen_records[record_key] = url_key
        except ValueError as exc:
            item["reason"] = str(exc)
        results.append(item)
    rejected = any(item["status"] == "不能导入" for item in results)
    changed = 0
    if not dry_run and not rejected:
        try:
            for item, variant, channel, destination, channel_name, url, note, when in pending:
                created = await routes._write_publication(session, task=task, variant=variant,
                    channel=destination, channel_name=channel_name, published_url=url, note=note, published_at=when,
                    publish_mode=routes.publication_publish_mode(routes.publish_mode_for_channel(channel, registry)))
                item.update(status="已导入" if created else "无需导入", reason="已回填" if created else "已经登记，未重复写入")
                changed += int(bool(created))
            await session.commit()
        except (ValueError, HTTPException, IntegrityError):
            await session.rollback()
            raise HTTPException(409, "文章或发布条件已变化，整批未写入，请重新预览") from None
        except Exception:
            await session.rollback()
            raise
    return {"dry_run": dry_run, "committed": not dry_run and not rejected, "changed": changed,
            "can_confirm": not rejected, "total": len(results), "rows": results,
            "message": gate_reason or ("有不能导入的行，请修改后整批重新上传" if rejected else "请核对每行后确认导入")}
