"""Versioned onsite delivery. Providers never approve, publish, or attest facts."""
from copy import deepcopy
import asyncio
from datetime import datetime, timezone, timedelta
import hashlib
import json
import re
from urllib.parse import urlsplit, urljoin
from xml.etree import ElementTree

from bs4 import BeautifulSoup
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field
from typing import Literal

LABELS = {"title": "页面 Title", "description": "页面 Description", "meta_keywords": "页面 Keywords", "keyword": "关键词部署",
          "internal_link": "内链部署", "robots": "robots 文件", "sitemap": "网站地图",
          "canonical": "SEO 架构与规范地址", "structured_content": "官网结构化内容",
          "knowledge": "知识库内容", "faq": "常见问题 FAQ", "schema": "Schema 标记", "llms": "llms.txt"}
KINDS = {"seo": set(LABELS) - {"structured_content", "knowledge", "faq", "schema", "llms"},
         "geo": {"structured_content", "knowledge", "faq", "schema", "llms"}}
PHASES = {"draft": "待制定方案", "review": "待人工审核", "implementation": "待网站实施",
          "recheck": "待系统复检", "acceptance": "待人工验收", "done": "已验收", "cancelled": "已取消"}

class Item(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    id: str = Field(pattern=r"^[a-z0-9_-]{1,60}$")
    kind: Literal["title", "description", "meta_keywords", "keyword", "internal_link", "robots", "sitemap",
                  "canonical", "structured_content", "knowledge", "faq", "schema", "llms"]
    target_url: str = Field(min_length=8, max_length=2048)
    expected: str = Field(default="", max_length=12000)
    instruction: str = Field(min_length=1, max_length=1000)

class Change(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    action: Literal["save_proposal", "approve", "implement", "recheck", "accept", "cancel"]
    expected_revision: int = Field(ge=1)
    items: list[Item] | None = Field(None, min_length=1, max_length=30)
    note: str = Field(default="", max_length=4000)
    owner_name: str | None = Field(None, min_length=1, max_length=100)

def now():
    return datetime.now(timezone.utc).isoformat()

def host_scope(domain):
    value = urlsplit(domain if "://" in domain else "https://" + domain)
    host = (value.hostname or "").lower().rstrip(".").removeprefix("www.")
    if not host or "." not in host:
        raise HTTPException(409, "网站域名尚未配置")
    return frozenset({host, "www." + host})

def scoped_url(value, domain):
    try:
        p = urlsplit(value)
        if (p.scheme not in {"http", "https"} or p.hostname is None or p.username or p.password
                or p.fragment or p.port not in {None, 80, 443}
                or p.hostname.lower().rstrip(".") not in host_scope(domain)
                or any(c.isspace() or ord(c) < 32 for c in value) or "\\" in value):
            raise ValueError()
    except ValueError as exc:
        raise HTTPException(422, "实施与证据地址必须属于当前网站，使用无凭证的 HTTP(S) 地址") from exc
    return value

def proposal_hash(items):
    return hashlib.sha256(json.dumps(items, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()

def validate_items(items, module, domain, required_ids=None, ready=False):
    values = [Item.model_validate(i).model_dump() for i in items]
    ids = [i["id"] for i in values]
    if not values or len(values) > 30 or len(ids) != len(set(ids)):
        raise HTTPException(422, "清单必须有 1–30 项且编号不能重复")
    if required_ids is not None and set(ids) != set(required_ids):
        raise HTTPException(422, "请保留当前任务全部清单项目")
    if len({i["target_url"] for i in values}) > 10:
        raise HTTPException(422, "一项任务最多复检 10 个页面，请拆分任务")
    for item in values:
        if item["kind"] not in KINDS[module]:
            raise HTTPException(422, "清单类型与当前模块不符")
        scoped_url(item["target_url"], domain)
        if item["kind"] in {"internal_link", "canonical"} and item["expected"]:
            scoped_url(item["expected"], domain)
        if ready and not item["expected"].strip():
            raise HTTPException(422, "请填写每项明确的预期内容或文件内容后再审核")
        if item["kind"] == "schema" and item["expected"]:
            try:
                schema = json.loads(item["expected"])
                if not isinstance(schema, dict) or not ("@type" in schema or "@graph" in schema):
                    raise ValueError()
            except ValueError as exc:
                raise HTTPException(422, "Schema 预期内容须为带 @type 或 @graph 的 JSON 对象") from exc
    return values

def new_workflow(module, work_type, month, domain, items, actor, owner, source=None):
    if work_type == "monthly" and not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", month or ""):
        raise HTTPException(422, "月度任务必须指定 YYYY-MM 服务月份")
    items = validate_items(items, module, domain)
    return dict(schema=1, module=module, work_type=work_type, month=month if work_type == "monthly" else None,
                domain=domain, revision=1, phase="draft", items=items, owner_name=owner,
                advisor_user_id=actor, source=source or {}, created_at=now(), updated_at=now(),
                history=[dict(action="create", actor=actor, at=now())])

def allowed_actions(w, can_write):
    if not can_write or w["phase"] in {"done", "cancelled"}:
        return []
    result = ["save_proposal", "cancel"]
    result += {"draft": [], "review": ["approve"], "implementation": ["implement"],
               "recheck": ["recheck"], "acceptance": ["recheck", "accept"]}.get(w["phase"], [])
    return result

def prepare_change(stored, req, module, domain, actor):
    w = deepcopy(stored)
    if w["revision"] != req.expected_revision:
        raise HTTPException(409, "任务版本已变化，请重新读取核对后操作")
    if w["domain"] != domain:
        raise HTTPException(409, "网站域名已变化，请重新建立任务")
    if req.action not in allowed_actions(w, True):
        raise HTTPException(409, "当前任务阶段不允许此操作")
    if req.action != "save_proposal" and (req.items is not None or req.owner_name is not None):
        raise HTTPException(422, "清单与实施负责人仅可在保存方案时修改")
    if req.action not in {"save_proposal", "recheck"} and not req.note.strip():
        raise HTTPException(422, "请填写审核、实施或验收的说明与依据")
    if req.action == "save_proposal":
        if req.items is None:
            raise HTTPException(422, "请提交完整方案清单")
        items = validate_items([i.model_dump() for i in req.items], module, domain,
                               [i["id"] for i in w["items"]])
        old_kinds = {i["id"]: i["kind"] for i in w["items"]}
        if any(old_kinds[i["id"]] != i["kind"] for i in items):
            raise HTTPException(422, "不能改变任务清单的验收类型")
        w.update(items=items, phase="review", owner_name=req.owner_name or w["owner_name"])
        for key in ("approval", "implementation", "recheck", "acceptance"):
            w.pop(key, None)
    elif req.action == "approve":
        validate_items(w["items"], module, domain, ready=True)
        w.update(phase="implementation", approval=dict(hash=proposal_hash(w["items"]),
                                                      actor=actor, note=req.note, at=now()))
    elif req.action == "implement":
        if w.get("approval", {}).get("hash") != proposal_hash(w["items"]):
            raise HTTPException(409, "当前方案没有有效审核")
        w.update(phase="recheck", implementation=dict(actor=actor, note=req.note, at=now()))
    elif req.action == "accept":
        check = w.get("recheck") or {}
        age = datetime.now(timezone.utc) - datetime.fromisoformat(check.get("at") or "1970-01-01T00:00:00+00:00")
        if (not check.get("passed") or check.get("hash") != proposal_hash(w["items"])
                or age > timedelta(hours=24)):
            raise HTTPException(409, "需要当前审核版本 24 小时内的通过复检")
        w.update(phase="done", acceptance=dict(actor=actor, note=req.note, at=now(),
                                              hash=proposal_hash(w["items"])))
    elif req.action == "cancel":
        w.update(phase="cancelled", cancellation=dict(actor=actor, note=req.note, at=now()))
    if len(w["history"]) >= 100:
        raise HTTPException(409, "任务历史达到上限，请保留记录并建立后续任务")
    w["revision"] += 1
    w["updated_at"] = now()
    w["history"].append(dict(action=req.action, actor=actor, note=req.note, at=w["updated_at"]))
    return w

def _contains(observed, expected):
    if isinstance(expected, dict):
        return isinstance(observed, dict) and all(k in observed and _contains(observed[k], v) for k, v in expected.items())
    if isinstance(expected, list):
        return isinstance(observed, list) and all(any(_contains(o, e) for o in observed) for e in expected)
    return observed == expected

def check_item(item, doc):
    html, url = doc["body"], doc["url"]
    kind, expected = item["kind"], item["expected"]
    soup = BeautifulSoup(html, "html.parser")
    observed, passed = "", False
    if kind == "title":
        nodes = soup.find_all("title")
        observed = nodes[0].get_text(" ", strip=True) if len(nodes) == 1 else ""
        passed = observed == expected
    elif kind in {"description", "meta_keywords"}:
        nodes = soup.select('meta[name="' + ("keywords" if kind == "meta_keywords" else "description") + '" i]')
        observed = str(nodes[0].get("content", "")).strip() if len(nodes) == 1 else ""
        passed = observed == expected
    elif kind in {"internal_link", "canonical"}:
        nodes = soup.select("a[href]" if kind == "internal_link" else 'link[rel="canonical"]')
        links = [urljoin(url, str(n.get("href") or "")) for n in nodes]
        observed = expected if expected in links else ""
        passed = bool(observed) and (kind != "canonical" or len(links) == 1)
    elif kind == "schema":
        values = []
        for node in soup.select('script[type="application/ld+json"]'):
            try:
                values.append(json.loads(node.get_text()))
            except ValueError:
                continue
        passed = any(_contains(v, json.loads(expected)) for v in values)
        observed = "审核 JSON 已匹配" if passed else "未匹配审核 JSON"
    elif kind in {"robots", "llms", "sitemap"}:
        observed = html
        passed = expected.strip() in html
        if kind == "robots":
            passed = passed and bool(re.search(r"(?im)^\s*User-agent\s*:", html))
        elif kind == "llms":
            passed = passed and bool(re.search(r"(?m)^#\s+\S", html))
        else:
            try:
                root = ElementTree.fromstring(html)
                passed = passed and root.tag.split("}")[-1] in {"urlset", "sitemapindex"}
            except ElementTree.ParseError:
                passed = False
    else:
        for node in soup.select("script,style,noscript,nav,footer,header,template,[hidden]"):
            node.decompose()
        root = soup.select_one("main") or soup.select_one("article") or soup.body or soup
        observed = root.get_text(" ", strip=True)
        passed = expected in observed
    return dict(id=item["id"], kind=kind, target_url=item["target_url"], final_url=url,
                passed=bool(passed), body_sha256=hashlib.sha256(html.encode()).hexdigest(),
                observed_excerpt=observed[:500], check_type="static_page_match",
                limit="页面存在与审核内容匹配；事实、适用条件和业务质量仍须人工验收")

async def recheck(w, fetch):
    results, documents = [], {}
    semaphore = asyncio.Semaphore(3)
    targets = {i["target_url"]: i["kind"] for i in w["items"]}
    async def read(target, kind):
        async with semaphore:
            try:
                return target, await fetch(target, kind)
            except (HTTPException, ValueError, TimeoutError, OSError):
                return target, None
    try:
        async with asyncio.timeout(65):
            documents = dict(await asyncio.gather(*(read(url, kind) for url, kind in targets.items())))
    except TimeoutError:
        documents = {}
    for item in w["items"]:
        target = item["target_url"]
        try:
            doc = documents.get(target)
            if doc is None:
                raise ValueError("页面读取失败")
            scoped_url(doc["url"], w["domain"])
            results.append(check_item(item, doc))
        except (HTTPException, ValueError, TimeoutError, OSError) as exc:
            results.append(dict(id=item["id"], target_url=target, passed=False,
                                reason="页面读取或范围核验失败"))
    passed = all(r["passed"] for r in results)
    w["recheck"] = dict(hash=proposal_hash(w["items"]), at=now(), passed=passed, results=results)
    w["phase"] = "acceptance" if passed else "recheck"
    return w

def reserve_recheck(settings):
    day = datetime.now(timezone(timedelta(hours=8))).date().isoformat()
    quota = (settings or {}).get("onsite_recheck_quota") or {}
    count = int(quota.get("count") or 0) if quota.get("day") == day else 0
    if count >= 20:
        raise HTTPException(429, "本站今日站内任务复检已达 20 次上限")
    return {**(settings or {}), "onsite_recheck_quota": {"day": day, "count": count + 1}}

