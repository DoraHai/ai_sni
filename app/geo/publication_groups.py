"""SELECT-only GEO publication groups. Task identity never means version identity."""
from datetime import date, datetime, timedelta, timezone
import re

from fastapi import HTTPException
from sqlalchemy import and_, func, or_, select, union, union_all

from app.geo.project_client_protocol import digest, encode_cursor, decode_cursor, fail, positive, safe_url
from app.geo.project_client_store import bounded, authorize, load_content
from app.models import (GeoProject, TenantModule, GeoContentTask as Task,
    GeoArticleVersion as Article, GeoChannelVariant as Variant, GeoPublication as Publication,
    GeoOptimizationBusiness as Business, GeoOptimizationUnit as Unit, GeoPrompt as Prompt)
from app.models.advisor_tenant_grant import AdvisorTenantGrant as Grant
from app.models.distribution_inbox import DistributionInboxReceipt as Receipt

ROW_BUDGET = 10000
INTERNAL = '/api/v1/geo/distribution/v2/publication-groups'


async def parameters(request, *, client=False):
    path = request.url.path
    expected = (r'/api/v1/geo/projects/[1-9][0-9]*/client/publication-groups' if client else re.escape(INTERNAL))
    if (request.method != 'GET' or not re.fullmatch(expected, path)
            or request.scope.get('raw_path') != path.encode('ascii', errors='replace')):
        fail(404, 'NOT_FOUND', '记录不存在')
    allowed = {'tenant_id', 'bucket', 'article_id', 'limit', 'cursor'} | (set() if client else {'scope_id'})
    if not client:
        allowed |= {'month', 'source'}
    pairs = request.query_params.multi_items()
    raw = dict(pairs)
    required = {'tenant_id'} | (set() if client else {'scope_id'})
    if len(pairs) != len(raw) or set(raw) - allowed or not required <= set(raw) or await request.body():
        fail(422, 'INVALID_QUERY', '不接受重复、未知参数或缺失范围及请求正文')
    bucket = raw.get('bucket', 'linked')
    if bucket not in ({'linked', 'unlinked'} if client else {'linked', 'unlinked', 'invalid', 'records'}):
        fail(422, 'INVALID_QUERY', '记录分区无效')
    article = positive(raw['article_id']) if 'article_id' in raw else None
    for key in ('tenant_id', 'scope_id', 'article_id'):
        if key in raw and not re.fullmatch('[1-9][0-9]{0,15}', raw[key]):
            fail(422, 'INVALID_QUERY', 'ID 必须是有效正整数')
    if article is not None and bucket not in {'linked', 'records'}:
        fail(422, 'INVALID_QUERY', '文章明细只支持已关联分区')
    if {'month', 'source'} & set(raw) and bucket != 'records':
        fail(422, 'INVALID_QUERY', '筛选只支持发布记录表')
    month, source = raw.get('month'), raw.get('source', 'all')
    if (month is not None and not re.fullmatch(r'[1-9][0-9]{3}-(0[1-9]|1[0-2])', month)) or source not in {'all', 'native', 'external_report'}:
        fail(422, 'INVALID_QUERY', '月份或来源无效')
    limit = raw.get('limit', '20')
    if not re.fullmatch('[0-9]{1,3}', limit) or not 1 <= int(limit) <= 100:
        fail(422, 'INVALID_QUERY', '每页数量必须为 1–100')
    return {**({'month': month, 'source': source} if bucket == 'records' else {}), 'tenant_id': positive(raw['tenant_id']),
        'project_id': positive(request.path_params['project_id'] if client else raw['scope_id']),
        'bucket': bucket, 'article_id': article, 'limit': int(limit), 'client': client}, (
        decode_cursor(raw['cursor']) if 'cursor' in raw else None)


async def internal_scope(session, ctx, params):
    """Fresh predicates equivalent to inbox target reads, without row locks."""
    from app.geo.content.inbox_policy import fresh_actor
    from app.geo.project_scope import binding
    from app.geo.project_workflows import plan_for
    from app.geo.tenant_scope import ensure_geo_entitlement
    from app.geo.project_client_store import ProjectRecords
    from app.geo.tenant16_demo import is_tenant16_demo
    from app.geo.demo_runtime import is_demo_environment
    actor = await fresh_actor(session, ctx, lock=False)
    tid, pid = params['tenant_id'], params['project_id']
    if is_tenant16_demo(ctx, tid) or is_demo_environment():
        fail(403, 'DEMO_UNSUPPORTED', '此只读接口不支持演示数据源')
    ctx.ensure_tenant(tid)
    if not actor.admin:
        grant = await session.scalar(select(Grant).where(Grant.id == ctx.advisor_scope.grant_id,
            Grant.user_id == actor.user.id, Grant.tenant_id == tid, Grant.revoked_at.is_(None)))
        default = await session.scalar(select(Grant.id).where(Grant.user_id == actor.user.id,
            Grant.tenant_id == actor.user.tenant_id, Grant.revoked_at.is_(None)))
        if grant is None or default is None:
            fail(403, 'FORBIDDEN', '无权读取此范围')
    elif actor.user.tenant_id not in {None, tid}:
        fail(403, 'FORBIDDEN', '无权读取此范围')
    await ensure_geo_entitlement(session, tid, lock_binding=False)
    module = await session.scalar(select(TenantModule).where(TenantModule.tenant_id == tid,
        TenantModule.module_code == 'geo'))
    if module is None or module.status not in {'active', 'trial'} or (module.expires_at and module.expires_at < date.today()):
        fail(403, 'FORBIDDEN', '模块不可用')
    projects = await bounded(session, GeoProject, [GeoProject.tenant_id == tid],
        ['id', 'tenant_id', 'tenant_module_id', 'status', 'project_settings'])
    project = next((p for p in projects if p.id == pid), None)
    if project is None or project.status != 'active' or project.tenant_module_id != module.id:
        fail(404, 'NOT_FOUND', '项目或记录不存在')
    bound = binding(project)
    bids = bound['business_ids']
    if any(set(binding(p)['business_ids']) & set(bids) for p in projects if p.id != pid):
        fail(403, 'FORBIDDEN', '项目范围存在冲突')
    if not actor.admin and plan_for(project).get('advisor_user_id') != actor.user.id:
        fail(403, 'FORBIDDEN', '项目未分配给当前顾问')
    if not actor.admin:
        from app.security.advisor_write_reads import assigned_scope
        owned, allowed_businesses = await assigned_scope(session, ctx)
        if pid not in owned or not set(bids).issubset(allowed_businesses):
            fail(403, 'FORBIDDEN', '项目业务分配已改变')
    records = ProjectRecords(project, (project.project_settings or {}).get('geo_business_scope', {}).get('revision', 0))
    businesses = await bounded(session, Business, [Business.tenant_id == tid, Business.id.in_(bids),
        Business.status == 'active'], ['id', 'status'])
    records.businesses = {b.id: b for b in businesses}
    units = await bounded(session, Unit, [Unit.tenant_id == tid, Unit.business_id.in_(records.businesses),
        Unit.status == 'active'], ['id', 'business_id', 'status'])
    records.units = {u.id: u for u in units}
    prompts = await bounded(session, Prompt, [Prompt.tenant_id == tid, Prompt.unit_id.in_(records.units),
        Prompt.status == 'active'], ['id', 'unit_id', 'status'])
    records.prompts = {p.id: p for p in prompts}
    tasks = await bounded(session, Task, [Task.tenant_id == tid, Task.prompt_id.in_(records.prompts)],
        ['id', 'prompt_id', 'business_id', 'title', 'status', 'updated_at'])
    records.tasks = {t.id: t for t in tasks if t.business_id in {
        None, records.units[records.prompts[t.prompt_id].unit_id].business_id}}
    return records, actor


def queries(records, params):
    """Both sources share an already-authorized task set; no title/URL matching."""
    native = select(Publication.id, Variant.task_id.label('task_id'),
        Variant.id.label('variant_id'), Article.id.label('article_version_id'), Article.version_no,
        Publication.channel, Publication.published_url, Publication.published_at,
        Publication.updated_at, Publication.status).join(Variant, Publication.variant_id == Variant.id).join(
        Article, and_(Article.id == Variant.article_version_id, Article.task_id == Variant.task_id)).where(
        Variant.task_id.in_(records.tasks))
    if params['client']:
        native = native.where(Variant.id.in_(records.variants), Article.id.in_(records.articles))
    receipt = select(Receipt.id, Receipt.article_id.label('task_id'), Receipt.article_version,
        Receipt.platform, Receipt.title, Receipt.public_url, Receipt.result, Receipt.received_at,
        Receipt.occurred_at, Receipt.revision, Receipt.owner_user_id,
        Receipt.published_account, Receipt.reported_account).where(
        Receipt.tenant_id == params['tenant_id'], Receipt.module == 'geo',
        Receipt.scope_id == params['project_id'], Receipt.state == 'active',
        Receipt.label_state == 'active', Receipt.deleted_at.is_(None))
    valid = Receipt.article_id.in_(records.tasks)
    if params['client']:
        valid = and_(valid, select(Article.id).where(Article.id.in_(records.articles),
            Article.task_id == Receipt.article_id, Article.version_no == Receipt.article_version).exists())
    return native, receipt.where(valid), receipt.where(Receipt.article_id.is_(None)), receipt.where(
        Receipt.article_id.is_not(None), ~valid)


async def rows(session, query, *, limit=None):
    result = (await session.execute(query.limit(limit or ROW_BUDGET + 1))).mappings().all()
    if len(result) > ROW_BUDGET:
        fail(503, 'READ_UNAVAILABLE', '当前数据量超出读取预算，请缩小范围后重试')
    return [dict(r) for r in result]


def stamp(value):
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc).isoformat() if value.tzinfo is None else value.isoformat()


def external(row, *, params, actor, ctx, invalid=False):
    url, state = safe_url(row['public_url'])
    linked = row['task_id'] is not None and not invalid
    item = {'source': 'external_report', 'source_key': 'external:' + row['id'],
        'group_article_id': row['task_id'] if linked else None,
        'task_id': row['task_id'] if linked else None, 'content_id': None,
        'article_version_id': None, 'article_version_no': row['article_version'] if linked else None,
        'native_publication_id': None, 'external_receipt_id': row['id'],
        'channel': row['platform'], 'url': url, 'url_state': state,
        'reported_at': stamp(row['occurred_at']), 'received_at': stamp(row['received_at']),
        'published_at': None, 'status': row['result'],
        'verification': {'status': 'unavailable' if linked else 'unlinked', 'evidence_valid': False}}
    if not linked and not invalid:
        item['title'] = row['title']
    if not params['client']:
        from app.config import get_settings
        item['can_label'] = bool(actor and (actor.admin or (row['owner_user_id'] == ctx.user_id
            and ctx.can_edit('geo.content') and get_settings().advisor_scoped_content_writes_enabled)))
    return item


def record_page(ns, es, us, ins, records, params, actor, ctx, decoded):
    """Display-only exact task + stored URL dedupe; native facts stay intact."""
    items, targets = [], {}
    for r in ns:
        url, state = safe_url(r['published_url'])
        item = {'source': 'native', 'source_key': f"native:geo:{r['id']}",
            'native_publication_id': r['id'], 'external_receipt_id': None,
            'task_id': r['task_id'], 'title': records.tasks[r['task_id']].title,
            'channel': r['channel'], 'account': None, 'url': url, 'url_state': state,
            'status': r['status'], 'event_at': stamp(r['published_at'] or r['updated_at']),
            'has_external_report': False, 'external_receipt_ids': []}
        items.append(item)
        if r['published_url']:
            # If native rows already repeat, preserve all native facts and attach
            # the external annotation to one stable (lowest native ID) row only.
            targets.setdefault((r['task_id'], r['published_url']), item)
    for r, invalid in [(r, False) for r in es + us] + [(r, True) for r in ins]:
        target = targets.get((r['task_id'], r['public_url'])) if not invalid and r['task_id'] is not None else None
        if target is not None:
            target['has_external_report'] = True
            target['external_receipt_ids'].append(r['id'])
            continue
        item = external(r, params=params, actor=actor, ctx=ctx, invalid=invalid)
        item.update(title=r['title'], account=r['published_account'] or r['reported_account'],
            event_at=stamp(r['occurred_at'] or r['received_at']),
            has_external_report=True, external_receipt_ids=[r['id']], association_invalid=invalid)
        items.append(item)
    def key(item):
        at = datetime.fromisoformat(item['event_at']) if item['event_at'] else None
        return (-(at.timestamp()) if at else 253402300800, item['source_key'])
    filtered = []
    for item in items:
        if params['article_id'] is not None and item['task_id'] != params['article_id']:
            continue
        if params['source'] == 'native' and item['source'] != 'native':
            continue
        if params['source'] == 'external_report' and not item['has_external_report']:
            continue
        if params['month']:
            at = datetime.fromisoformat(item['event_at']) if item['event_at'] else None
            if at is None or at.astimezone(timezone(timedelta(hours=8))).strftime('%Y-%m') != params['month']:
                continue
        filtered.append(item)
    filtered.sort(key=key)
    total = len(filtered)
    if decoded:
        last = decoded['last']
        if len(last) != 2 or type(last[0]) not in {int, float} or not isinstance(last[1], str):
            fail(400, 'INVALID_CURSOR', '分页游标无效')
        filtered = [item for item in filtered if key(item) > tuple(last)]
    more = len(filtered) > params['limit']
    selected = filtered[:params['limit']]
    return selected, more, list(key(selected[-1])) if selected else [], total


async def response(request, ctx, session, *, client=False):
    params, decoded = await parameters(request, client=client)
    actor = None
    if client:
        records = await authorize(session, ctx, params, request)
        await load_content(session, records, params)
    else:
        records, actor = await internal_scope(session, ctx, params)
    aid = params['article_id']
    if aid is not None and aid not in records.tasks:
        fail(404, 'NOT_FOUND', '项目或记录不存在')
    native, linked, unlinked, invalid = queries(records, params)
    versions = await rows(session, select(Article.task_id, Article.id, Article.version_no).where(
        Article.task_id.in_(records.tasks), Article.kind == 'master').order_by(Article.id))
    current_versions = {}
    for version in versions:
        current_versions[version['task_id']] = max(current_versions.get(version['task_id'], 0), version['version_no'])
    # Bounded minimal source scans detect additions, deletions, relabels and edits.
    # No successful partial totals if the revision verification budget is exceeded.
    ns = await rows(session, native.order_by(Publication.id))
    es = await rows(session, linked.order_by(Receipt.id))
    us = await rows(session, unlinked.order_by(Receipt.id))
    ins = [] if client else await rows(session, invalid.order_by(Receipt.id))
    if sum(map(len, (versions, ns, es, us, ins))) > ROW_BUDGET:
        fail(503, 'READ_UNAVAILABLE', '当前数据量超出读取预算，请缩小范围后重试')
    context = digest({'module': 'geo', 'actor': ctx.user_id, 'permissions': ctx.permissions,
        'role': ctx.role_name, **params})
    snapshot = digest({'scope': records.fingerprint,
        'tasks': [(t.id, t.title, t.status, str(t.updated_at)) for t in sorted(records.tasks.values(), key=lambda t: t.id)],
        'versions': versions,
        'sources': [[{k: str(v) for k, v in r.items()} for r in source] for source in (ns, es, us, ins)]})
    marks = {'native': max((r['id'] for r in ns), default=0),
        'external': len(es) + len(us) + len(ins)}
    if decoded:
        if decoded['context'] != context:
            fail(400, 'INVALID_CURSOR', '账号、客户、范围或筛选已改变，请刷新')
        if decoded['scope'] != snapshot or decoded['watermarks'] != marks:
            fail(409, 'SCOPE_CHANGED', '数据或权限范围已改变，请刷新')
    # UNION and group pagination execute in SQL, independently of detail pages.
    nsub, esub = native.subquery(), linked.subquery()
    groups = union(select(nsub.c.task_id), select(esub.c.task_id)).subquery()
    counts = {'native_records': len(ns), 'external_records': len(es) + len(us) + len(ins),
        'article_groups': await session.scalar(select(func.count()).select_from(groups)),
        'unlinked_records': len(us)}
    if not client:
        counts['invalid_records'] = len(ins)
    bucket, limit = params['bucket'], params['limit']
    if bucket == 'records':
        items, more, last, total = record_page(ns, es, us, ins, records, params, actor, ctx, decoded)
        counts['filtered_records'] = total
    elif bucket == 'linked' and aid is None:
        events = union_all(select(nsub.c.task_id,
            func.coalesce(nsub.c.published_at, nsub.c.updated_at).label('event_at')),
            select(esub.c.task_id, func.coalesce(esub.c.occurred_at, esub.c.received_at).label('event_at'))).subquery()
        latest = select(events.c.task_id, func.max(events.c.event_at).label('latest_at')).group_by(events.c.task_id).subquery()
        # ISO timestamps in cursors retain the exact stable SQL ordering key.
        q = select(latest.c.task_id, latest.c.latest_at).order_by(latest.c.latest_at.desc().nulls_last(), latest.c.task_id.desc())
        if decoded:
            last = decoded['last']
            if len(last) != 2 or type(last[1]) is not int or (last[0] is not None and not isinstance(last[0], str)):
                fail(400, 'INVALID_CURSOR', '分页游标无效')
            if last[0] is None:
                q = q.where(latest.c.latest_at.is_(None), latest.c.task_id < last[1])
            else:
                from datetime import datetime
                try:
                    at = datetime.fromisoformat(last[0])
                except ValueError:
                    fail(400, 'INVALID_CURSOR', '分页游标无效')
                q = q.where(or_(latest.c.latest_at < at, latest.c.latest_at.is_(None),
                    and_(latest.c.latest_at == at, latest.c.task_id < last[1])))
        page = (await session.execute(q.limit(limit + 1))).all()
        more, page = len(page) > limit, page[:limit]
        ids = [r.task_id for r in page]
        nc = dict((await session.execute(select(nsub.c.task_id, func.count()).where(
            nsub.c.task_id.in_(ids)).group_by(nsub.c.task_id))).all())
        ec = dict((await session.execute(select(esub.c.task_id, func.count()).where(
            esub.c.task_id.in_(ids)).group_by(esub.c.task_id))).all())
        items = [{'group_article_id': i, 'task_id': i, 'content_id': None,
            'title': records.tasks[i].title, 'native_count': nc.get(i, 0), 'external_count': ec.get(i, 0),
            'current_version_no': current_versions.get(i), 'details_loaded': False} for i in ids]
        last = [page[-1].latest_at.isoformat() if page[-1].latest_at else None, ids[-1]] if ids else []
    else:
        if bucket == 'linked':
            ordered = [(0, r['id'], r) for r in ns if r['task_id'] == aid] + [
                (1, r['id'], r) for r in es if r['task_id'] == aid]
        else:
            ordered = [(0, r['id'], r) for r in (us if bucket == 'unlinked' else ins)]
        # UUID keys are never compared with native integer keys.
        def key(entry):
            rank, pk, r = entry
            if bucket == 'linked':
                at = (r['published_at'] or r['updated_at']) if rank == 0 else (r['occurred_at'] or r['received_at'])
                return (-(at.replace(tzinfo=timezone.utc).timestamp() if at.tzinfo is None else at.timestamp()) if at else 253402300800, rank, str(pk))
            return (-r['received_at'].timestamp(), pk)
        ordered.sort(key=key)
        if decoded:
            try:
                last = decoded['last']
                if len(last) != (3 if bucket == 'linked' else 2):
                    raise ValueError()
                ordered = [e for e in ordered if key(e) > tuple(last)]
            except (ValueError, TypeError):
                fail(400, 'INVALID_CURSOR', '分页游标无效')
        selected = ordered[:limit + 1]
        more, selected = len(selected) > limit, selected[:limit]
        items = []
        for rank, pk, r in selected:
            if bucket != 'linked' or rank == 1:
                item = external(r, params=params, actor=actor, ctx=ctx, invalid=bucket == 'invalid')
            else:
                url, state = safe_url(r['published_url'])
                item = {'source': 'native', 'source_key': f'native:geo:{pk}',
                    'group_article_id': aid, 'task_id': aid, 'content_id': None,
                    'article_version_id': r['article_version_id'], 'article_version_no': r['version_no'],
                    'variant_id': r['variant_id'], 'native_publication_id': pk, 'external_receipt_id': None,
                    'channel': r['channel'], 'url': url, 'url_state': state,
                    'published_at': stamp(r['published_at']), 'reported_at': None, 'received_at': None,
                    'status': r['status'], 'verification': {'status': 'not_projected', 'evidence_valid': False}}
            item['current_version_no'] = current_versions.get(aid) if aid else None
            items.append(item)
        last = list(key(selected[-1])) if selected else []
    cursor = encode_cursor({'v': 1, 'context': context, 'scope': snapshot, 'week_end': None,
        'watermarks': marks, 'last': last}) if more else None
    return {'schema': 1, 'read_only': True,
        'context': {'module': 'geo', 'tenant_id': params['tenant_id'], 'scope_id': params['project_id'],
            **({'month': params['month'], 'source': params['source']} if bucket == 'records' else {}),
            'bucket': bucket, 'article_id': aid, 'audience': 'client' if client else 'internal'},
        'items': items, 'counts': {**counts, 'loaded_items': len(items)},
        'next_cursor': cursor, 'has_more': more,
        'completeness': {'complete': True, 'visibility': 'visible_current_master' if client else 'authorized_history',
            'pagination_complete': not more, 'revision': snapshot}}
