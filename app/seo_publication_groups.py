"""Read-only publication index. Never creates publication or verification facts."""
from datetime import datetime, timezone, timedelta
import hashlib
import json
import re
from urllib.parse import urlsplit

import jwt
from fastapi import HTTPException
from sqlalchemy import DateTime, String, and_, case, cast, func, literal, or_, select, union_all

from sqlalchemy.ext.compiler import compiles
from sqlalchemy.sql.functions import FunctionElement

from app.models.distribution_inbox import DistributionInboxReceipt as R
from app.models.seo import SeoContentAsset as C, SeoContentPublication as P, SeoDistributionConnection as D

MAX_ID = 9007199254740991
REVISION_BUDGET = 20000


class _UtcNativeTime(FunctionElement):
    """Native columns store naive UTC; receipts and cursor binds are timestamptz."""
    type = DateTime(timezone=True)
    inherit_cache = True


@compiles(_UtcNativeTime)
def _utc_native_default(element, compiler, **kw):
    return compiler.process(list(element.clauses)[0], **kw)


@compiles(_UtcNativeTime, "postgresql")
def _utc_native_postgresql(element, compiler, **kw):
    return f"({_utc_native_default(element, compiler, **kw)} AT TIME ZONE 'UTC')"


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
    if not customer:
        allowed |= {"month", "source"}
    if (request.method != "GET" or request.url.path != path or
            request.scope.get("raw_path") != path.encode("ascii") or
            set(q) - allowed or len(q.multi_items()) != len(q) or
            "tenant_id" not in q or scope_key not in q):
        error("GROUPS_INVALID_QUERY")
    bucket = q.get("bucket", "linked")
    if bucket not in ({"linked", "unlinked"} if customer else {"linked", "unlinked", "invalid", "records"}):
        error("GROUPS_INVALID_QUERY")
    article = positive(q["article_id"]) if "article_id" in q else None
    if article is not None and bucket != "linked":
        error("GROUPS_INVALID_QUERY")
    if ({"month", "source"} & set(q)) and bucket != "records":
        error("GROUPS_INVALID_QUERY")
    month, source = q.get("month"), q.get("source", "all")
    if month == "9999-12":
        error("GROUPS_INVALID_QUERY")
    if (month is not None and not re.fullmatch(r"[1-9][0-9]{3}-(?:0[1-9]|1[0-2])", month)) or source not in {"all", "native", "external_report"}:
        error("GROUPS_INVALID_QUERY")
    cursor = q.get("cursor")
    if cursor is not None and (not cursor or len(cursor) > 4096):
        error("GROUPS_INVALID_CURSOR")
    return dict(tenant=positive(q["tenant_id"]), scope=positive(q[scope_key]),
                bucket=bucket, article=article, **({"month": month, "source": source} if bucket == "records" else {}), limit=positive(q.get("limit", "20"), 100), cursor=cursor)


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
                    P.platform_name, P.source_version, P.page_url, P.published_at,
                    D.name.label("account"), P.publish_mode).outerjoin(D, and_(D.id == P.connection_id, D.tenant_id == P.tenant_id)).join(C, and_(C.id == P.content_asset_id,
                    C.tenant_id == P.tenant_id)).where(content, P.tenant_id == tenant, P.status == "published")
    receipts = select(R.id.label("id"), R.article_id.label("article"), R.revision.label("revision"),
                      R.received_at.label("received"), C.id.label("visible_article"),
                      C.updated_at.label("content_updated"), C.title.label("content_title"), C.version_count,
                      R.platform, R.title, R.public_url, R.result, R.occurred_at, R.article_version,
                      R.published_account, R.reported_account, R.owner_user_id).outerjoin(C, and_(C.id == R.article_id, content)).where(
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
    if args["bucket"] == "records":
        return await read_records(session, ctx, args, customer=customer, authorization_revision=authorization_revision, admin=admin, writes=writes, secret=secret)
    tenant, scope, bucket, article, limit = (args[k] for k in ("tenant", "scope", "bucket", "article", "limit"))
    n, e = sources(tenant, scope)
    data_revision, watermarks = await revision(session, n, e, customer=customer)
    rev = digest([data_revision, authorization_revision])
    binding = digest(["seo-time-desc", ctx.user_id, customer, tenant, scope, bucket, article])
    after = decode_cursor(args["cursor"], binding, rev, watermarks, secret)
    valid = e.c.visible_article.is_not(None)
    events = union_all(select(n.c.article.label("article"), literal(1).label("n"), literal(0).label("e"),
                              func.coalesce(n.c.published_at, n.c.updated).label("event_at")),
                       select(e.c.article, literal(0), literal(1),
                              func.coalesce(e.c.occurred_at, e.c.received)).where(valid)).subquery("events")
    grouped = select(events.c.article, func.sum(events.c.n).label("native_count"),
                     func.sum(events.c.e).label("external_count"),
                     func.max(events.c.event_at).label("latest_at")).group_by(events.c.article).subquery("groups")
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
            if (not isinstance(after, list) or len(after) != 2 or type(after[1]) is not int
                    or not 0 < after[1] <= MAX_ID):
                error("GROUPS_INVALID_CURSOR")
            try:
                stamp = datetime.fromisoformat(after[0])
                if stamp.tzinfo is None:
                    raise ValueError()
            except (TypeError, ValueError):
                error("GROUPS_INVALID_CURSOR")
            statement = statement.where(or_(grouped.c.latest_at < stamp,
                and_(grouped.c.latest_at == stamp, grouped.c.article < after[1])))
        rows = list((await session.execute(statement.order_by(
            grouped.c.latest_at.desc(), grouped.c.article.desc()).limit(limit + 1))).all())
        more, rows = len(rows) > limit, rows[:limit]
        items = [{**identity(tenant, scope, r.article), "title": r.title, "current_version_no": r.version_count,
                  "native_count": int(r.native_count), "external_count": int(r.external_count),
                  "latest_at": iso(r.latest_at), "details_loaded": False} for r in rows]
        if more:
            next_after = [iso(rows[-1].latest_at), rows[-1].article]
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


async def read_records(session, ctx, args, *, customer, authorization_revision, admin, writes, secret):
    """One advisor table. Exact article ID + exact nonempty URL folds a receipt into its native row."""
    if customer:
        error("GROUPS_FORBIDDEN", 403)
    tenant, scope, limit = args["tenant"], args["scope"], args["limit"]
    month, source = args.get("month"), args.get("source", "all")
    n, e = sources(tenant, scope)
    data_revision, watermarks = await revision(session, n, e, customer=False)
    rev = digest([data_revision, authorization_revision])
    binding = digest(["seo-records-v1", ctx.user_id, tenant, scope, month, source])
    after = decode_cursor(args["cursor"], binding, rev, watermarks, secret)
    exact = and_(e.c.visible_article.is_not(None), e.c.article == n.c.article,
                 e.c.public_url.is_not(None), e.c.public_url != "", e.c.public_url == n.c.page_url)
    has_receipt = select(e.c.id).where(exact).exists()
    has_native = select(n.c.id).where(exact).exists()
    native_rows = select(literal("native").label("source"), cast(n.c.id, String).label("source_key"),
        n.c.article, n.c.title, n.c.platform_name.label("channel"), n.c.account,
        n.c.page_url.label("url"), literal("published").label("status"),
        _UtcNativeTime(func.coalesce(n.c.published_at, n.c.updated)).label("event_at"), has_receipt.label("also_reported"),
        literal(False).label("can_link"), literal(False).label("invalid"), n.c.publish_mode)
    external_rows = select(literal("external_report"), e.c.id, e.c.visible_article,
        case((and_(e.c.article.is_not(None), e.c.visible_article.is_(None)), None), else_=e.c.title),
        e.c.platform, func.coalesce(e.c.published_account, e.c.reported_account), e.c.public_url, e.c.result,
        func.coalesce(e.c.occurred_at, e.c.received), literal(False),
        and_(literal(writes), or_(literal(admin), e.c.owner_user_id == ctx.user_id)),
        and_(e.c.article.is_not(None), e.c.visible_article.is_(None)), literal(None)).where(~has_native)
    records = union_all(native_rows, external_rows).subquery("records")
    statement = select(records)
    if source == "native":
        statement = statement.where(records.c.source == "native")
    elif source == "external_report":
        statement = statement.where(or_(records.c.source == "external_report", records.c.also_reported.is_(True)))
    if month:
        year, number = map(int, month.split("-"))
        start = datetime(year, number, 1, tzinfo=timezone.utc) - timedelta(hours=8)
        end = datetime(year + (number == 12), 1 if number == 12 else number + 1, 1, tzinfo=timezone.utc) - timedelta(hours=8)
        statement = statement.where(records.c.event_at >= start, records.c.event_at < end)
    total = int(await session.scalar(select(func.count()).select_from(statement.subquery())) or 0)
    if after is not None:
        if not isinstance(after, list) or len(after) != 3 or after[1] not in {"native", "external_report"} or not isinstance(after[2], str):
            error("GROUPS_INVALID_CURSOR")
        try:
            stamp = datetime.fromisoformat(after[0])
            if stamp.tzinfo is None:
                raise ValueError()
        except (TypeError, ValueError):
            error("GROUPS_INVALID_CURSOR")
        statement = statement.where(or_(records.c.event_at < stamp,
            and_(records.c.event_at == stamp, records.c.source < after[1]),
            and_(records.c.event_at == stamp, records.c.source == after[1], records.c.source_key < after[2])))
    rows = list((await session.execute(statement.order_by(records.c.event_at.desc(), records.c.source.desc(),
        records.c.source_key.desc()).limit(limit + 1))).all())
    more, rows = len(rows) > limit, rows[:limit]
    items = [{**identity(tenant, scope, r.article), "key": f"native:seo:{r.source_key}" if r.source == "native" else f"external:{r.source_key}",
        "source": r.source, "native_publication_id": int(r.source_key) if r.source == "native" else None,
        "external_receipt_id": r.source_key if r.source == "external_report" else None,
        "title": r.title, "channel": r.channel, "account": r.account,
        "url": safe_url(r.url), "status": r.status, "event_at": iso(r.event_at),
        "also_reported": bool(r.also_reported), "can_link": bool(r.can_link), "invalid": bool(r.invalid),
        "publish_mode": r.publish_mode} for r in rows]
    return {"schema": 1, "read_only": True, "completeness": "complete_snapshot",
        "context": {"module": "seo", "tenant_id": tenant, "scope_id": scope, "bucket": "records",
                    "article_id": None, "revision": rev, "month": month, "source": source},
        "items": items, "counts": {"total": total, "loaded": len(items)}, "has_more": more,
        "next_cursor": encode_cursor([iso(rows[-1].event_at), rows[-1].source, rows[-1].source_key],
            binding, rev, watermarks, secret) if more else None}
