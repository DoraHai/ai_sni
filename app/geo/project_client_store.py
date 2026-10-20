"""SELECT-only project scope and bounded repository for client projections."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta

from fastapi import HTTPException
from sqlalchemy import and_, or_, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import load_only

from app.database import async_session_factory
from app.geo.demo_tenant import GeoDemoBindingUnavailable
from app.geo.project_scope import binding
from app.geo.project_client_protocol import digest, fail, public_host
from app.geo.content.time_windows import shanghai_day_bounds_utc_naive
from app.geo.tenant_scope import ensure_geo_entitlement
from app.models import (
    GeoProject, GeoOptimizationBusiness as Business, GeoOptimizationUnit as Unit,
    GeoPrompt as Prompt, GeoAnswerSnapshot as Answer, GeoVisibilityPatrolRun as Run,
    GeoPublishingChannel as Channel, GeoContentTask as Task, GeoArticleVersion as Article,
    GeoChannelVariant as Variant, GeoPublication as Publication,
)
from app.module_scope import ensure_module_access

# A complete response or a visible 503, never an apparently complete partial total.
ROW_BUDGET = 10000


async def client_read_session():
    async with async_session_factory(autoflush=False) as session:
        try:
            await session.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY'))
            await session.execute(text("SET LOCAL statement_timeout = '5000ms'"))
            yield session
        except SQLAlchemyError:
            fail(503, 'READ_UNAVAILABLE', '数据暂时无法读取，请稍后重试')
        finally:
            await session.rollback()


async def bounded(session, model, conditions, fields):
    statement = select(model).where(*conditions).options(
        load_only(*(getattr(model, name) for name in fields), raiseload=True)
    ).limit(ROW_BUDGET + 1)
    rows = list(await session.scalars(statement))
    if len(rows) > ROW_BUDGET:
        fail(503, 'READ_UNAVAILABLE', '当前数据量超出读取预算，请稍后重试')
    return rows


@dataclass
class ProjectRecords:
    project: object
    revision: int
    businesses: dict = field(default_factory=dict)
    units: dict = field(default_factory=dict)
    prompts: dict = field(default_factory=dict)
    answers: list = field(default_factory=list)
    runs: dict = field(default_factory=dict)
    own_domains: list = field(default_factory=list)
    tasks: dict = field(default_factory=dict)
    articles: dict = field(default_factory=dict)
    variants: dict = field(default_factory=dict)
    publications: list = field(default_factory=list)

    @property
    def fingerprint(self):
        return digest({'revision': self.revision, 'businesses': sorted(self.businesses),
                       'units': sorted((u.id, u.business_id) for u in self.units.values()),
                       'prompts': sorted((p.id, p.unit_id) for p in self.prompts.values())})


async def authorize(session, ctx, params, request=None):
    tid, pid = params['tenant_id'], params['project_id']
    if not (ctx.can_view('geo.assets') and ctx.can_view('geo.content')):
        fail(403, 'FORBIDDEN', '需要项目与内容查看权限')
    try:
        ctx.ensure_tenant(tid)
    except HTTPException:
        fail(403, 'FORBIDDEN', '无权访问该客户的数据')
    from app.geo.tenant16_demo import is_tenant16_demo
    from app.geo.demo_runtime import is_demo_environment
    if is_tenant16_demo(ctx, tid) or is_demo_environment():
        fail(403, 'DEMO_UNSUPPORTED', '此只读接口不支持演示数据源')
    try:
        policy = await ensure_geo_entitlement(session, tid, allow_demo_read=True, lock_binding=False)
    except GeoDemoBindingUnavailable:
        fail(403, 'DEMO_UNSUPPORTED', '此只读接口不支持演示数据源')
    except HTTPException:
        fail(403, 'MODULE_UNAVAILABLE', '当前客户的 GEO 模块不可用')
    if policy.is_demo:
        fail(403, 'DEMO_UNSUPPORTED', '此只读接口不支持演示数据源')
    try:
        module = await ensure_module_access(session, ctx, tid, 'geo')
    except HTTPException:
        fail(403, 'MODULE_UNAVAILABLE', '当前客户的 GEO 模块不可用')
    projects = await bounded(session, GeoProject, [GeoProject.id == pid, GeoProject.tenant_id == tid],
                             ['id', 'tenant_id', 'tenant_module_id', 'status', 'project_settings',
                              'name', 'brand_name', 'canonical_domain'])
    project = next(iter(projects), None)
    if project is None:
        fail(404, 'NOT_FOUND', '项目或记录不存在')
    if project.tenant_module_id != module.id:
        fail(403, 'MODULE_UNAVAILABLE', '项目模块绑定不可用')
    if getattr(ctx, 'advisor_scope', None) is not None:
        from app.security.advisor_write_reads import assigned_scope
        owned, businesses = await assigned_scope(session, ctx)
        if pid not in owned:
            fail(404, 'NOT_FOUND', '项目或记录不存在')
    if project.status != 'active':
        fail(409, 'PROJECT_INACTIVE', '项目当前未启用')
    try:
        settings = project.project_settings
        if settings is not None and not isinstance(settings, dict):
            raise ValueError()
        value = (settings or {}).get('geo_business_scope')
        if value is not None and not isinstance(value, dict):
            raise ValueError()
        revision = (value or {}).get('revision', 0)
        if type(revision) is not int or not 0 <= revision <= 2**53 - 1:
            raise ValueError()
        bound = binding(project)
    except (HTTPException, ValueError, TypeError, AttributeError):
        fail(409, 'BINDING_INVALID', '项目业务归属无效，请由顾问处理')
    records = ProjectRecords(project=project, revision=revision)
    rows = await bounded(session, Business, [Business.tenant_id == tid, Business.id.in_(bound['business_ids'])], ['id', 'name'])
    records.businesses = {b.id: b for b in rows}
    if set(records.businesses) != set(bound['business_ids']):
        fail(409, 'BINDING_INVALID', '项目业务已不存在或归属改变')
    if getattr(ctx, 'advisor_scope', None) is not None:
        if not set(records.businesses).issubset(businesses):
            fail(404, 'NOT_FOUND', '项目或记录不存在')
        if request is not None:
            request.scope['geo_advisor_read_projects'] = (frozenset({pid}), frozenset(records.businesses))
    units = await bounded(session, Unit, [Unit.tenant_id == tid, Unit.business_id.in_(records.businesses)], ['id', 'business_id', 'name'])
    records.units = {u.id: u for u in units}
    prompts = await bounded(session, Prompt, [Prompt.tenant_id == tid, Prompt.unit_id.in_(records.units)],
                            ['id', 'unit_id', 'question', 'status', 'is_brand_probe'])
    records.prompts = {p.id: p for p in prompts}
    return records


async def load_answers(session, records, params, *, answer_id=None):
    tid = params['tenant_id']
    end = params['week_end']
    start = shanghai_day_bounds_utc_naive(end - timedelta(days=21))[0]
    stop = shanghai_day_bounds_utc_naive(end)[0]
    window = and_(Answer.captured_at >= start, Answer.captured_at < stop)
    conditions = [Answer.tenant_id == tid, Answer.prompt_id.in_(records.prompts),
                  or_(window, Answer.captured_at.is_(None), Answer.id == answer_id if answer_id else False)]
    records.answers = await bounded(session, Answer, conditions,
        ['id', 'tenant_id', 'prompt_id', 'engine', 'captured_at', 'sample_mode', 'simulated', 'note',
         'citation_accuracy', 'raw_text', 'mentions_brand', 'cited_urls', 'competitors', 'patrol_run_id'])
    # A mixed-project run is never serialized. Only the bound snapshot's matching
    # cell is inspected by the pure evidence checks; no tenant-wide run summaries.
    runs = await bounded(session, Run, [Run.tenant_id == tid, Run.id.in_({r.patrol_run_id for r in records.answers if r.patrol_run_id})],
                         ['id', 'tenant_id', 'status', 'started_at', 'finished_at', 'items'])
    records.runs = {r.id: r for r in runs}
    channels = await bounded(session, Channel, [Channel.tenant_id == tid, Channel.enabled.is_(True),
                             Channel.channel_type.in_(['website', 'docs'])], ['id', 'base_url'])
    from app.geo.integration_metrics import domain
    canonical = public_host(records.project.canonical_domain)
    records.own_domains = sorted({host for c in channels if canonical and (host := public_host(domain(c.base_url)))
                                  and (host == canonical or host.endswith('.' + canonical))})


async def load_content(session, records, params):
    tid = params['tenant_id']
    # Both task.prompt and task.business must agree with the *current* chain.
    chain = select(Prompt.id, Unit.business_id).join(Unit, Unit.id == Prompt.unit_id).where(
        Prompt.tenant_id == tid, Unit.tenant_id == tid, Unit.business_id.in_(records.businesses)).subquery()
    tasks = await bounded(session, Task, [Task.tenant_id == tid, Task.prompt_id.in_(records.prompts),
        or_(Task.business_id.is_(None), Task.business_id == select(chain.c.business_id).where(chain.c.id == Task.prompt_id).scalar_subquery())],
        ['id', 'prompt_id', 'business_id', 'title', 'status', 'pipeline_step', 'review_status', 'reviewed_at', 'created_at', 'updated_at'])
    records.tasks = {t.id: t for t in tasks}
    articles = await bounded(session, Article, [Article.task_id.in_(records.tasks), Article.kind == 'master'],
        ['id', 'task_id', 'version_no', 'kind', 'title', 'body_markdown', 'created_at'])
    records.articles = {a.id: a for a in articles}
    variants = await bounded(session, Variant, [Variant.task_id.in_(records.tasks), Variant.article_version_id.in_(records.articles)],
        ['id', 'task_id', 'article_version_id', 'channel', 'title', 'status', 'body_markdown', 'adapt_meta', 'created_at', 'updated_at'])
    records.variants = {v.id: v for v in variants if records.articles[v.article_version_id].task_id == v.task_id}
    records.publications = await bounded(session, Publication, [Publication.variant_id.in_(records.variants)],
        ['id', 'variant_id', 'channel', 'publish_mode', 'published_url', 'published_at', 'updated_at', 'status'])


def require_object(rows, ident):
    row = rows.get(ident)
    if row is None:
        fail(404, 'NOT_FOUND', '项目或记录不存在')
    return row
