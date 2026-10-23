"""Read-only publication index. Never creates publication or verification facts."""
from datetime import datetime, timezone
import hashlib
import json
import re
from urllib.parse import urlsplit

import jwt
from fastapi import HTTPException
from sqlalchemy import and_, func, literal, or_, select, union_all

from app.models.distribution_inbox import DistributionInboxReceipt as R
from app.models.seo import SeoContentAsset as C, SeoContentPublication as P

MAX_ID = 9007199254740991
REVISION_BUDGET = 20000


def error(code, status=422):
    raise HTTPException(status, {"code": code, "message": {
        "GROUPS_REFRESH_REQUIRED": "记录或权限已变化，请刷新后重新加载",
        "GROUPS_READ_INCOMPLETE": "读取超出预算或来源不可用，请缩小范围后重试",
        "GROUPS_FORBIDDEN": "当前账号无权查看此范围的发布记录",
        "GROUPS_NOT_FOUND": "当前范围的记录不可查看",
        "GROUPS_INVALID_CURSOR": "分页位置已失效，请刷新后重试",
    }.get(code, "发布记录请求无效")})


def positive(value, maximum=MAX_ID):
    if not isinstance(value, str) or not re.fullmatch(r"[1-9][0-9]{0,15}", value):
        error("GROUPS_INVALID_QUERY")
    number = int(value)
    if number > maximum:
        error("GROUPS_INVALID_QUERY")
    return number


def query(request, *, customer):
    path = ("/api/v1/seo/workbench/publication-groups" if customer else
            "/api/v1/seo/distribution/v2/publication-groups")
    q = request.query_params
    scope_key = "site_id" if customer else "scope_id"
    allowed = {"tenant_id", scope_key, "bucket", "article_id", "limit", "cursor"}
    if (request.method != "GET" or request.url.path != path or
            request.scope.get("raw_path") != path.encode("ascii") or
            set(q) - allowed or len(q.multi_items()) != len(q) or
            "tenant_id" not in q or scope_key not in q):
        error("GROUPS_INVALID_QUERY")
    bucket = q.get("bucket", "linked")
    if bucket not in ({"linked", "unlinked"} if customer else {"linked", "unlinked", "invalid"}):
        error("GROUPS_INVALID_QUERY")
    article = positive(q["article_id"]) if "article_id" in q else None
    if article is not None and bucket != "linked":
        error("GROUPS_INVALID_QUERY")
    cursor = q.get("cursor")
    if cursor is not None and (not cursor or len(cursor) > 4096):
        error("GROUPS_INVALID_CURSOR")
    return dict(tenant=positive(q["tenant_id"]), scope=positive(q[scope_key]),
                bucket=bucket, article=article, limit=positive(q.get("limit", "50"), 100), cursor=cursor)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str, separators=(",", ":")).encode()).hexdigest()


def safe_url(value):
    try:
        u = urlsplit(value or "")
        if (u.scheme not in {"https", "http"} or not u.hostname or u.username is not None
                or u.password is not None or any(ord(c) < 33 for c in value) or "\\" in value):
            return None
        u.port  # Reject invalid ports as well.
        return value
    except ValueError:
        return None


def iso(value):
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def sources(tenant, scope):
    content = and_(C.tenant_id == tenant, C.site_id == scope)
    native = select(P.id.label("id"), P.content_asset_id.label("article"), P.updated_at.label("updated"),
                    C.updated_at.label("content_updated"), C.title, C.version_count,
                    P.platform_name, P.source_version, P.page_url, P.published_at).join(C, and_(C.id == P.content_asset_id,
                    C.tenant_id == P.tenant_id)).where(content, P.tenant_id == tenant, P.status == "published")
    receipts = select(R.id.label("id"), R.article_id.label("article"), R.revision.label("revision"),
                      R.received_at.label("received"), C.id.label("visible_article"),
                      C.updated_at.label("content_updated"), C.title.label("content_title"), C.version_count,
                      R.platform, R.title, R.public_url, R.result, R.occurred_at, R.article_version).outerjoin(C, and_(C.id == R.article_id, content)).where(
                          R.tenant_id == tenant, R.module == "seo", R.scope_id == scope,
                          R.state == "active", R.label_state == "active")
    return native.subquery("native"), receipts.subquery("external")


async def revision(session, native, external, *, customer):
    """Bounded metadata scan detects deletes/relabels too; never reads payload/body/history."""
    n = list((await session.execute(select(native).order_by(native.c.id).limit(REVISION_BUDGET + 1))).all())
    e_query = select(external)
    if customer:
        e_query = e_query.where(or_(external.c.article.is_(None), external.c.visible_article.is_not(None)))
    e = list((await session.execute(e_query.order_by(external.c.id).limit(REVISION_BUDGET + 1))).all())
    if len(n) > REVISION_BUDGET or len(e) > REVISION_BUDGET:
        error("GROUPS_READ_INCOMPLETE", 503)
    return digest([[list(row) for row in n], [list(row) for row in e]]), {
        "native": max((r.id for r in n), default=0), "external": max((r.id for r in e), default="")}


def decode_cursor(token, binding, rev, watermarks, secret):
    if not token:
        return None
    try:
        data = jwt.decode(token, secret, algorithms=["HS256"], options={"require": ["exp"]})
        if set(data) != {"exp", "v", "binding", "revision", "watermarks", "after"} or data["v"] != 1:
            raise ValueError()
        if data["binding"] != binding:
            error("GROUPS_INVALID_CURSOR")
        if data["revision"] != rev or data["watermarks"] != watermarks:
            error("GROUPS_REFRESH_REQUIRED", 409)
        return data["after"]
    except (jwt.InvalidTokenError, ValueError, TypeError):
        error("GROUPS_INVALID_CURSOR")


def encode_cursor(after, binding, rev, watermarks, secret):
    return jwt.encode({"exp": int(datetime.now(timezone.utc).timestamp()) + 900, "v": 1,
                       "binding": binding, "revision": rev, "watermarks": watermarks, "after": after},
                      secret, algorithm="HS256")


def identity(tenant, scope, article):
    return {"module": "seo", "tenant_id": tenant, "scope_id": scope,
            "group_article_id": article, "content_id": article, "task_id": None}


def native_dto(row, tenant, scope):
    return {**identity(tenant, scope, row.content_asset_id), "source": "native",
            "key": f"native:seo:{row.id}", "native_publication_id": row.id, "external_receipt_id": None,
            "article_version_id": None, "article_version_no": row.source_version,
            "channel": row.platform_name, "url": safe_url(row.page_url), "status": row.status,
            "verification": "see_native_evidence", "published_at": iso(row.published_at),
            "reported_at": None, "received_at": None}


def external_dto(row, tenant, scope, *, customer, invalid=False, can_link=False):
    dto = {**identity(tenant, scope, None if invalid else row.article_id), "source": "external_report",
           "key": f"external:{row.id}", "native_publication_id": None, "external_receipt_id": row.id,
           "article_version_id": None, "article_version_no": None if invalid else row.article_version,
           "channel": row.platform, "title": None if invalid else row.title,
           "url": safe_url(row.public_url), "status": row.result,
           "verification": "unavailable" if row.article_id else "unlinked", "published_at": None,
           "reported_at": iso(row.occurred_at), "received_at": iso(row.received_at)}
    if not customer:
        dto["can_link"] = can_link
    return dto


async def read_groups(session, ctx, args, *, customer, authorization_revision, admin=False, writes=False, secret):
    tenant, scope, bucket, article, limit = (args[k] for k in ("tenant", "scope", "bucket", "article", "limit"))
    n, e = sources(tenant, scope)
    data_revision, watermarks = await revision(session, n, e, customer=customer)
    rev = digest([data_revision, authorization_revision])
    binding = digest(["seo", ctx.user_id, customer, tenant, scope, bucket, article])
    after = decode_cursor(args["cursor"], binding, rev, watermarks, secret)
    valid = e.c.visible_article.is_not(None)
    events = union_all(select(n.c.article.label("article"), literal(1).label("n"), literal(0).label("e")),
                       select(e.c.article, literal(0), literal(1)).where(valid)).subquery("events")
    grouped = select(events.c.article, func.sum(events.c.n).label("native_count"),
                     func.sum(events.c.e).label("external_count")).group_by(events.c.article).subquery("groups")
    count = lambda statement: session.scalar(statement)
    counts = {"native": int(await count(select(func.count()).select_from(n)) or 0),
              "external": int(await count(select(func.count()).select_from(e).where(
                  or_(e.c.article.is_(None), valid) if customer else literal(True))) or 0),
              "articles": int(await count(select(func.count()).select_from(grouped)) or 0),
              "unlinked": int(await count(select(func.count()).select_from(e).where(e.c.article.is_(None))) or 0)}
    if not customer:
        counts["invalid"] = int(await count(select(func.count()).select_from(e).where(
            e.c.article.is_not(None), e.c.visible_article.is_(None))) or 0)
    next_after = None
    if bucket == "linked" and article is None:
        statement = select(grouped, C.title, C.version_count).join(C, and_(C.id == grouped.c.article,
                            C.tenant_id == tenant, C.site_id == scope))
        if after is not None:
            if type(after) is not int or not 0 < after <= MAX_ID:
                error("GROUPS_INVALID_CURSOR")
            statement = statement.where(grouped.c.article < after)
        rows = list((await session.execute(statement.order_by(grouped.c.article.desc()).limit(limit + 1))).all())
        more, rows = len(rows) > limit, rows[:limit]
        items = [{**identity(tenant, scope, r.article), "title": r.title, "current_version_no": r.version_count,
                  "native_count": int(r.native_count), "external_count": int(r.external_count),
                  "details_loaded": False} for r in rows]
        if more:
            next_after = rows[-1].article
    elif bucket == "linked":
        if not await session.scalar(select(C.id).where(C.id == article, C.tenant_id == tenant, C.site_id == scope)):
            error("GROUPS_NOT_FOUND", 404)
        rank, key = -1, None
        if after is not None:
            if (not isinstance(after, list) or len(after) != 2 or type(after[0]) is not int or
                    after[0] not in {0, 1} or
                    (after[0] == 0 and (type(after[1]) is not int or not 0 < after[1] <= MAX_ID)) or
                    (after[0] == 1 and (not isinstance(after[1], str) or not re.fullmatch(
                        r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", after[1])))):
                error("GROUPS_INVALID_CURSOR")
            rank, key = after
        native_rows = []
        if rank < 1:
            statement = select(P.id, P.content_asset_id, P.source_version, P.platform_name,
                               P.page_url, P.status, P.published_at).where(
                                   P.id.in_(select(n.c.id).where(n.c.article == article)))
            if rank == 0:
                statement = statement.where(P.id > key)
            native_rows = list((await session.execute(statement.order_by(P.id).limit(limit + 1))).all())
        remaining = limit + 1 - len(native_rows)
        external_rows = []
        if remaining > 0:
            statement = select(R.id, R.article_id, R.article_version, R.platform, R.title, R.public_url,
                               R.result, R.occurred_at, R.received_at).where(
                R.id.in_(select(e.c.id).where(valid, e.c.article == article)))
            if rank == 1:
                statement = statement.where(R.id > key)
            external_rows = list((await session.execute(statement.order_by(R.id).limit(remaining))).all())
        tagged = [(0, row.id, native_dto(row, tenant, scope)) for row in native_rows]
        tagged += [(1, row.id, external_dto(row, tenant, scope, customer=customer)) for row in external_rows]
        more, tagged = len(tagged) > limit, tagged[:limit]
        items = [r[2] for r in tagged]
        if more:
            next_after = [tagged[-1][0], tagged[-1][1]]
    else:
        condition = e.c.article.is_(None) if bucket == "unlinked" else and_(e.c.article.is_not(None), e.c.visible_article.is_(None))
        statement = select(R.id, R.article_id, R.article_version, R.platform, R.title, R.public_url,
                           R.result, R.occurred_at, R.received_at, R.owner_user_id).where(R.id.in_(select(e.c.id).where(condition)))
        if after is not None:
            if not isinstance(after, list) or len(after) != 2:
                error("GROUPS_INVALID_CURSOR")
            try:
                stamp = datetime.fromisoformat(after[0])
                if stamp.tzinfo is None or not isinstance(after[1], str):
                    raise ValueError()
            except (TypeError, ValueError):
                error("GROUPS_INVALID_CURSOR")
            statement = statement.where(or_(R.received_at < stamp, and_(R.received_at == stamp, R.id > after[1])))
        rows = list((await session.execute(statement.order_by(R.received_at.desc(), R.id).limit(limit + 1))).all())
        more, rows = len(rows) > limit, rows[:limit]
        items = [external_dto(r, tenant, scope, customer=customer, invalid=bucket == "invalid",
                              can_link=writes and (admin or r.owner_user_id == ctx.user_id)) for r in rows]
        if more:
            next_after = [iso(rows[-1].received_at), rows[-1].id]
    return {"schema": 1, "read_only": True,
            "context": {"module": "seo", "tenant_id": tenant, "scope_id": scope,
                        "bucket": bucket, "article_id": article, "revision": rev},
            "items": items, "counts": {**counts, "loaded": len(items)},
            "next_cursor": encode_cursor(next_after, binding, rev, watermarks, secret) if more else None,
            "has_more": more, "completeness": "complete_snapshot"}
