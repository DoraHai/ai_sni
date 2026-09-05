"""Bounded external backlink inputs; index entries remain unverified candidates."""
import csv
import io
import ipaddress
from collections import Counter
from datetime import datetime, timedelta
from urllib.parse import urlparse

import httpx
from app.config import get_settings
from app.seo_backlinks import belongs_to_site
from app.seo_serp import canonical_url


def candidate_url(value):
    value = str(value or "").strip()
    parsed = urlparse(value)
    try:
        parsed.port
    except ValueError as exc:
        raise ValueError("URL 端口格式错误") from exc
    if len(value) > 2000 or parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password or any(c.isspace() for c in value):
        raise ValueError("必须填写完整、无账号信息的 HTTP(S) URL")
    host = parsed.hostname.rstrip(".").lower()
    if "." not in host or host.endswith((".local", ".localhost", ".internal")):
        raise ValueError("不能导入内网地址")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address and not address.is_global:
        raise ValueError("不能导入内网地址")
    return canonical_url(value)


def normalize_candidate(item, domain):
    source = candidate_url(item.get("source_url"))
    target = candidate_url(item.get("target_url"))
    if belongs_to_site(source, domain):
        raise ValueError("来源属于当前网站，应在内链模块管理")
    if not belongs_to_site(target, domain):
        raise ValueError("目标链接不属于当前网站")
    return {"source_url": source, "target_url": target, "anchor_text": str(item.get("anchor_text") or "")[:1000]}


def parse_backlink_csv(raw, domain):
    if len(raw) > 2 * 1024 * 1024:
        raise ValueError("CSV 文件不能超过 2 MB")
    try:
        decoded = raw.decode("utf-16") if raw.startswith((b"\xff\xfe", b"\xfe\xff")) else raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            decoded = raw.decode("gb18030")
        except UnicodeDecodeError as exc:
            raise ValueError("请使用 UTF-8 或 GB18030 编码的 CSV") from exc
    aliases = {"source_url": {"source_url", "url_from", "referring page url", "source url", "来源页面", "来源页面 url"},
               "target_url": {"target_url", "url_to", "target url", "目标页面", "目标页面 url"},
               "anchor_text": {"anchor_text", "anchor", "anchor text", "锚文本"}}
    reader = csv.DictReader(io.StringIO(decoded, newline=""), strict=True)
    try:
        headers = reader.fieldnames or []
    except csv.Error as exc:
        raise ValueError("CSV 表头格式错误") from exc
    mapping = {key: next((header for header in headers if header.strip().lower() in names), None) for key, names in aliases.items()}
    if not mapping["source_url"] or not mapping["target_url"]:
        raise ValueError("缺少来源页面和目标页面列，请下载模板")
    items, errors, seen = [], [], set()
    total = duplicate = 0
    try:
        for number, record in enumerate(reader, 2):
            total += 1
            if total > 500:
                raise ValueError("每批最多导入 500 行")
            try:
                if None in record:
                    raise ValueError("列数不匹配，请使用正确的 CSV 引号")
                value = normalize_candidate({key: record.get(header) for key, header in mapping.items() if header}, domain)
                pair = (value["source_url"], value["target_url"])
                if pair in seen:
                    duplicate += 1
                    continue
                seen.add(pair)
                items.append({**value, "line": number})
            except ValueError as exc:
                errors.append({"line": number, "reason": str(exc)})
    except csv.Error as exc:
        raise ValueError("CSV 格式错误或单个字段过长") from exc
    return {"items": items, "errors": errors, "total": total, "duplicates": duplicate}


async def import_candidates(session, tenant_id, site_id, items, source):
    from sqlalchemy.dialects.postgresql import insert
    from app.models.seo import SeoBacklink
    created = 0
    for item in items:
        new_id = await session.scalar(insert(SeoBacklink).values(
            tenant_id=tenant_id, site_id=site_id, source_url=item["source_url"], target_url=item["target_url"],
            source_domain=urlparse(item["source_url"]).hostname, anchor_text=item["anchor_text"], status="active", missing_checks=0,
            verification={"state": "pending", "provenance": {"source": source, "imported_at": datetime.utcnow().isoformat()}},
        ).on_conflict_do_nothing(constraint="uq_seo_backlink_site_source_target").returning(SeoBacklink.id))
        created += int(new_id is not None)
    return {"created": created, "existing": len(items) - created}


def index_status():
    settings = get_settings()
    ready = bool(settings.seo_backlink_index_enabled and settings.seo_dataforseo_login.strip() and settings.seo_dataforseo_password.strip())
    return {"configured": ready, "provider": "DataForSEO", "limit": 100,
            "message": "单次最多 100 条供应商索引候选，每个网站每日最多查询一次；供应商按调用计费。" if ready else "未启用外链索引服务；可先导入 CSV 或扫描来源页面。"}


async def fetch_index_candidates(domain):
    if not index_status()["configured"]:
        raise ValueError("外链索引服务未启用或未配置凭据")
    settings = get_settings()
    # Fixed official origin; never send provider credentials to a configurable mirror.
    async with httpx.AsyncClient(timeout=20, follow_redirects=False) as client:
        try:
            response = await client.post("https://api.dataforseo.com/v3/backlinks/backlinks/live",
                auth=(settings.seo_dataforseo_login, settings.seo_dataforseo_password),
                json=[{"target": domain, "limit": 100, "mode": "one_per_domain", "backlinks_status_type": "live"}])
            response.raise_for_status()
            body = response.json()
            tasks = body.get("tasks") or []
            if body.get("status_code") != 20000 or len(tasks) != 1 or tasks[0].get("status_code") != 20000:
                code = tasks[0].get("status_code") if tasks else body.get("status_code")
                raise ValueError(f"外链索引服务拒绝请求（代码 {code}），请检查权限、余额或套餐")
            results = tasks[0].get("result") or []
            if len(results) != 1 or not isinstance(results[0], dict):
                raise ValueError("外链索引服务返回异常")
            records = results[0].get("items") or []
            if not isinstance(records, list) or len(records) > 100:
                raise ValueError("外链索引服务返回超出范围")
            items, rejected = [], 0
            for record in records:
                try:
                    items.append(normalize_candidate({"source_url":record.get("url_from"), "target_url":record.get("url_to"), "anchor_text":record.get("anchor")}, domain))
                except (ValueError, AttributeError):
                    rejected += 1
            return {"items":items,"rejected":rejected}
        except (httpx.HTTPError, TypeError, AttributeError) as exc:
            raise ValueError("外链索引请求失败，未自动重试；可导入供应商导出的 CSV") from exc


def backlink_analysis(rows, now=None):
    now = now or datetime.utcnow()
    days = [(now-timedelta(days=n)).date().isoformat() for n in range(29,-1,-1)]
    trend = {day:{"date":day,"new":0,"lost":0} for day in days}
    domains, anchors, targets, attributes = Counter(), Counter(), Counter(), Counter()
    found = lost = pending = issues = 0
    for row in rows:
        evidence = row.verification or {}
        if row.status == "disavow":
            continue
        domains[row.source_domain] += 1
        anchors[row.anchor_text or "（无锚文本）"] += 1
        targets[row.target_url] += 1
        found += int(evidence.get("state") == "found")
        lost += int(row.status == "lost")
        pending += int(evidence.get("state", "pending") == "pending")
        issues += int(evidence.get("state") in {"unreachable", "blocked"})
        if evidence.get("state") == "found":
            rel = evidence.get("rel") or []
            for key in (rel or ["未声明 nofollow"]):
                attributes[key] += 1
        if evidence.get("state") != "pending" and row.first_seen_at and row.first_seen_at.date().isoformat() in trend:
            trend[row.first_seen_at.date().isoformat()]["new"] += 1
        for day in {h.get("checked_at", "")[:10] for h in evidence.get("history", []) if h.get("transition") == "lost"}:
            if day in trend:
                trend[day]["lost"] += 1
    def top(values):
        return [{"name":key,"count":count} for key,count in values.most_common(10)]
    total = sum(domains.values())
    return {"monitored":total,"verified":found,"lost":lost,"pending":pending,"unavailable":issues,
            "referring_domains":len(domains),"top_domain_share":round(max(domains.values(), default=0)/max(total,1)*100,1),
            "domains":top(domains),"anchors":top(anchors),"targets":top(targets),"attributes":top(attributes),"trend":list(trend.values())}
