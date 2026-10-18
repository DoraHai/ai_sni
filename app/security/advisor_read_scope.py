"""Project ownership for every GEO ORM read, including aggregates and exports.

Attach to the request's session, never the session class or a background job.
Subqueries deliberately use Core columns so loader criteria cannot recurse.
"""
from sqlalchemy import and_, event, false, or_, select
from sqlalchemy.orm import with_loader_criteria


def predicates(ctx, projects, businesses, domains=(), prompt_ids=(), patrol_ids=()):
    from app import models as m
    tid = ctx.tenant_id
    unit = m.GeoOptimizationUnit.__table__.c
    prompt = m.GeoPrompt.__table__.c
    task = m.GeoContentTask.__table__.c
    variant = m.GeoChannelVariant.__table__.c
    report = m.GeoCompetitorReport.__table__.c
    snapshot = m.GeoAnswerSnapshot.__table__.c
    units = select(unit.id).where(unit.tenant_id == tid, unit.business_id.in_(businesses))
    prompts = select(prompt.id).where(prompt.tenant_id == tid, prompt.unit_id.in_(units))
    tasks = select(task.id).where(task.tenant_id == tid, task.prompt_id.in_(prompts),
        or_(task.business_id.is_(None), task.business_id.in_(businesses)))
    variants = select(variant.id).where(variant.task_id.in_(tasks))
    reports = select(report.id).where(report.tenant_id == tid, report.business_id.in_(businesses))
    # A mixed tenant-wide patrol cannot expose its cached summary or raw cells.
    # Show complete runs only when every stored sample belongs to this scope.
    visible_runs = select(snapshot.patrol_run_id).where(snapshot.tenant_id == tid,
        snapshot.prompt_id.in_(prompts), snapshot.patrol_run_id.is_not(None))
    foreign_runs = select(snapshot.patrol_run_id).where(snapshot.tenant_id == tid,
        ~snapshot.prompt_id.in_(prompts), snapshot.patrol_run_id.is_not(None))
    audit = m.GeoAuditRun.__table__.c
    audit_urls = []
    for domain in domains:
        for scheme in ('https://', 'http://'):
            for host in (domain, 'www.' + domain):
                base = scheme + host
                audit_urls += [audit.url == base, audit.url.startswith(base + '/', autoescape=True)]
    audits = select(audit.id).where(audit.tenant_id == tid, or_(false(), *audit_urls))
    result = {
        m.GeoProject: m.GeoProject.id.in_(projects),
        m.GeoOptimizationBusiness: m.GeoOptimizationBusiness.id.in_(businesses),
        m.GeoOptimizationUnit: m.GeoOptimizationUnit.business_id.in_(businesses),
        m.GeoPrompt: m.GeoPrompt.unit_id.in_(units),
        m.GeoFact: m.GeoFact.business_id.in_(businesses),
        m.GeoContentTask: and_(m.GeoContentTask.prompt_id.in_(prompts),
            or_(m.GeoContentTask.business_id.is_(None), m.GeoContentTask.business_id.in_(businesses))),
        m.GeoAnswerSnapshot: m.GeoAnswerSnapshot.prompt_id.in_(prompts),
        m.GeoArticleVersion: m.GeoArticleVersion.task_id.in_(tasks),
        m.GeoChannelVariant: m.GeoChannelVariant.task_id.in_(tasks),
        m.GeoTaskFact: and_(m.GeoTaskFact.task_id.in_(tasks), m.GeoTaskFact.fact_id.in_(
            select(m.GeoFact.__table__.c.id).where(m.GeoFact.__table__.c.tenant_id == tid,
                                                  m.GeoFact.__table__.c.business_id.in_(businesses)))),
        m.GeoPublication: m.GeoPublication.variant_id.in_(variants),
        m.GeoOptimizationPeriod: m.GeoOptimizationPeriod.business_id.in_(businesses),
        m.GeoCompetitorReport: m.GeoCompetitorReport.business_id.in_(businesses),
        m.GeoCompetitorReportVersion: m.GeoCompetitorReportVersion.report_id.in_(reports),
        m.GeoDailyMetric: m.GeoDailyMetric.business_id.in_(businesses),
        m.GeoMediaPlacement: m.GeoMediaPlacement.related_prompt_id.in_(prompts),
        m.GeoAuditRun: m.GeoAuditRun.id.in_(audits),
        m.GeoActionTicket: or_(m.GeoActionTicket.content_task_id.in_(tasks),
            m.GeoActionTicket.progress_first['params']['content_task_id'].as_integer().in_(tasks),
            m.GeoActionTicket.progress['onsite']['project_id'].as_integer().in_(projects),
            m.GeoActionTicket.progress['project_workflow']['project_id'].as_integer().in_(projects),
            m.GeoActionTicket.audit_id.in_(audits)),
        m.GeoAsyncJob: or_(and_(m.GeoAsyncJob.ref_type == 'content_task', m.GeoAsyncJob.ref_id.in_(tasks)),
            and_(m.GeoAsyncJob.ref_type == 'geo_project', m.GeoAsyncJob.ref_id.in_(projects))),
        m.GeoVisibilityPatrolRun: m.GeoVisibilityPatrolRun.id.in_(patrol_ids),
        m.GeoExpandRun: m.GeoExpandRun.roots[0]['advisor_project_id'].as_integer().in_(projects),
        m.GeoDeliverableArchive: m.GeoDeliverableArchive.pack_json['data_scope']['project_id'].as_integer().in_(projects),
    }
    # Shared destinations/settings contain no project-owned content. Keep them
    # customer-bound, while the existing serializers continue to omit credentials.
    for model in (m.GeoPublishingChannel, m.GeoChannelAccount, m.GeoTrackingEngine,
                  m.GeoVisibilityPatrolSettings, m.GeoAiSetting, m.GeoChannelPolishPrompt,
                  m.GeoCompetitorAlias):
        result[model] = model.tenant_id == tid if projects else false()
    for model, condition in list(result.items()):
        if hasattr(model, 'tenant_id'):
            result[model] = and_(model.tenant_id == tid, condition)
    return result


async def bind_read_scope(session, ctx, request=None, project_limit=None):
    if getattr(ctx, 'advisor_scope', None) is None or session.info.get('advisor_read_scope'):
        return
    from app.models import GeoProject, GeoPrompt, GeoOptimizationUnit, GeoVisibilityPatrolRun, GeoAnswerSnapshot
    from app.security.advisor_write_reads import assigned_scope
    projects, businesses = await assigned_scope(session, ctx)
    rows = list(await session.scalars(select(GeoProject).where(GeoProject.tenant_id == ctx.tenant_id)))
    if project_limit is not None:
        from app.geo.project_scope import binding
        projects &= set(project_limit)
        businesses &= {bid for p in rows if p.id in projects for bid in binding(p)['business_ids']}
        session.info['advisor_operation_project_limit'] = frozenset(projects)
    domains = {p.canonical_domain for p in rows if p.id in projects and p.canonical_domain
               and sum(other.canonical_domain == p.canonical_domain for other in rows) == 1}
    prompt_ids = list(await session.scalars(select(GeoPrompt.id).where(GeoPrompt.tenant_id == ctx.tenant_id,
        GeoPrompt.unit_id.in_(select(GeoOptimizationUnit.id).where(GeoOptimizationUnit.tenant_id == ctx.tenant_id,
                                                               GeoOptimizationUnit.business_id.in_(businesses))))))
    foreign_runs = set(await session.scalars(select(GeoAnswerSnapshot.patrol_run_id).where(
        GeoAnswerSnapshot.tenant_id == ctx.tenant_id, ~GeoAnswerSnapshot.prompt_id.in_(prompt_ids),
        GeoAnswerSnapshot.patrol_run_id.is_not(None))))
    runs = list(await session.scalars(select(GeoVisibilityPatrolRun).where(
        GeoVisibilityPatrolRun.tenant_id == ctx.tenant_id)))
    patrol_ids = {r.id for r in runs if r.id not in foreign_runs and patrol_in_scope(r, set(prompt_ids))}
    criteria = predicates(ctx, projects, businesses, domains, prompt_ids, patrol_ids)

    def restrict(state):
        if (state.is_select or state.is_update or state.is_delete) and not state.execution_options.get('advisor_scope_control'):
            current = session.info['advisor_read_scope'][3]
            options = tuple(with_loader_criteria(model, condition, include_aliases=True)
                            for model, condition in current.items())
            state.statement = state.statement.options(*options)

    event.listen(session.sync_session, 'do_orm_execute', restrict)
    session.info['advisor_read_scope'] = (ctx, frozenset(projects), frozenset(businesses), criteria)
    session.info['advisor_read_domains'] = domains
    session.info['advisor_read_prompt_ids'] = set(prompt_ids)
    session.info['advisor_read_patrol_ids'] = patrol_ids
    if request is not None:
        request.scope['geo_advisor_read_projects'] = (frozenset(projects), frozenset(businesses))


def patrol_in_scope(row, prompt_ids):
    summary = row.summary or {}
    frozen = summary.get('advisor_visibility_prompt_ids')
    items = row.items or []
    ids = {item.get('prompt_id') for item in items if isinstance(item, dict)}
    if len([item for item in items if isinstance(item, dict)]) != len(items) or None in ids:
        return False
    plan = summary.get('contract_plan') or {}
    cells = plan.get('cells') or []
    ids.update(c.get('prompt_id') for c in cells if isinstance(c, dict))
    if frozen is not None:
        if not isinstance(frozen, list) or any(type(p) is not int for p in frozen):
            return False
        ids.update(frozen)
    declared = summary.get('prompts', len(ids))
    return bool(ids and ids.issubset(prompt_ids) and type(declared) is int and declared <= len(ids))


async def recheck_read_projects(binding, expected):
    from app.database import async_session_factory
    from app.security.advisor_write_reads import assigned_scope
    from app.security.advisor_scope import deny
    from types import SimpleNamespace
    user_id, _claims, tenant_id, _menus = binding
    async with async_session_factory() as session:
        current = await assigned_scope(session, SimpleNamespace(user_id=user_id, tenant_id=tenant_id))
        if (frozenset(current[0]), frozenset(current[1])) != expected:
            deny(403, 'ADVISOR_ASSIGNMENT_REQUIRED', '项目分配已变化，请刷新后重试')


async def check_read_references(session, ctx, request):
    from app import models as m
    from app.security.advisor_scope import deny
    models = dict(project_id=m.GeoProject, business_id=m.GeoOptimizationBusiness,
        unit_id=m.GeoOptimizationUnit, prompt_id=m.GeoPrompt, fact_id=m.GeoFact,
        snapshot_id=m.GeoAnswerSnapshot, content_task_id=m.GeoContentTask,
        run_id=m.GeoVisibilityPatrolRun, patrol_run_id=m.GeoVisibilityPatrolRun,
        period_id=m.GeoOptimizationPeriod, report_id=m.GeoCompetitorReport,
        job_id=m.GeoAsyncJob, async_job_id=m.GeoAsyncJob, audit_id=m.GeoAuditRun,
        ticket_id=m.GeoActionTicket, archive_id=m.GeoDeliverableArchive,
        placement_id=m.GeoMediaPlacement)
    models['task_id'] = m.GeoActionTicket if '/integration/tasks' in request.url.path else m.GeoContentTask
    for key, value in list(request.path_params.items()) + list(request.query_params.multi_items()):
        model = models.get(key)
        if model is None:
            continue
        ident = await session.scalar(select(model.id).where(model.id == int(value)))
        if ident is None:
            deny(403, 'ADVISOR_ASSIGNMENT_REQUIRED', '这个对象不属于分配给你的有效项目')
