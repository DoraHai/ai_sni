"""Reviewed operational contracts. No URL prefix or schema-derived grants."""
import json
from types import SimpleNamespace

from app.security.advisor_scope import deny

# method, resolved route, JSON fields, optional query fields
CONTRACTS = [
    ('POST', '/facts/import', '', 'business_id'),
    ('POST', '/prompts/import-csv', '', 'unit_id'),
    ('POST', '/prompts/import', 'tenant_id items unit_id', ''),
    ('POST', '/prompts/expand-candidates', 'tenant_id market roots competitors products seed_from_tenant max_terms persist', 'project_id'),
    ('POST', '/prompts/promote-candidates', 'tenant_id items', ''),
    ('POST', '/gap-workbench/create-tasks', 'tenant_id prompt_ids', ''),
    ('POST', '/content-tasks/from-source-opportunity', 'tenant_id prompt_id snapshot_ids evidence_version', ''),
    ('POST', '/content-tasks/from-diagnosis', 'tenant_id audit_id advice_code', 'project_id'),
    ('POST', '/content-tasks/{task_id}/seed-diagnosis-facts', '', ''),
    ('POST', '/content-tasks/{task_id}/retrieve-facts', 'limit verified_only auto_bind', ''),
    ('POST', '/content-tasks/{task_id}/apply-patch', 'code author_name', ''),
    ('POST', '/content-tasks/{task_id}/import-receipts', '', 'project_id dry_run'),
    ('POST', '/content-tasks/{task_id}/deliveries/{variant_id}/{delivery_id}/resolve', 'tenant_id action note published_url confirmed_not_published', ''),
    ('POST', '/content-tasks/{task_id}/publication-monitor/{publication_id}/check', '', ''),
    ('POST', '/async-jobs/{job_id}/cancel', '', ''),
    ('POST', '/reports/publication-links/preview', '', 'business_id project_id'),
    ('POST', '/reports/publication-links/confirm', 'tenant_id business_id project_id rows', ''),
    ('PUT', '/reports/template', 'tenant_id project_id sections', ''),
    ('POST', '/optimization-periods', 'tenant_id name starts_at ends_at business_id goal_note capture_baseline', ''),
    ('POST', '/optimization-periods/{period_id}/close', '', ''),
    ('POST', '/answer-snapshots', 'tenant_id prompt_id engine raw_text captured_at mentions_brand cited_urls competitors brand_position sentiment citation_format citation_accuracy note sample_mode', ''),
    ('PATCH', '/answer-snapshots/{snapshot_id}', 'engine raw_text captured_at mentions_brand cited_urls competitors brand_position sentiment citation_format citation_accuracy note', ''),
    ('POST', '/answer-snapshots/probe', 'tenant_id prompt_id engine', ''),
    ('POST', '/answer-snapshots/probe-batch', 'tenant_id prompt_id engines', ''),
    ('POST', '/answer-snapshots/extract-urls', 'tenant_id raw_text', 'project_id'),
    ('POST', '/answer-snapshots/suggest-fields', 'tenant_id raw_text prompt_id use_llm', 'project_id'),
    ('POST', '/answer-snapshots/check-citations', 'tenant_id cited_urls snapshot_id apply', 'project_id'),
    ('DELETE', '/visibility-patrol/runs/{run_id}', '', 'force'),
    ('POST', '/visibility-patrol/runs/cleanup', '', 'keep_latest only_terminal project_id'),
    ('POST', '/competitor-insights/web-search', '', 'name project_id'),
    ('POST', '/competitor-insights/report', 'tenant_id competitor source_urls platform_keys confirmed_external_urls note insight action', 'project_id'),
    ('POST', '/competitor-insights/create-tasks', 'tenant_id competitor items', ''),
    ('POST', '/competitor-reports', 'tenant_id competitor title business_id period_id insight action note markdown source_urls platform_keys evidence status', ''),
    ('PATCH', '/competitor-reports/{report_id}', 'title business_id period_id insight action note markdown source_urls platform_keys evidence status', ''),
    ('POST', '/competitor-reports/{report_id}/confirm', '', ''),
    ('POST', '/competitor-reports/{report_id}/archive', '', ''),
    ('POST', '/competitor-reports/{report_id}/restore', '', 'version_no'),
    ('POST', '/competitor-reports/{report_id}/create-task', '', ''),
    ('PUT', '/competitor-aliases', 'aliases alias_map', 'project_id'),
    ('POST', '/media-placements', 'tenant_id name channel_type channel_key target_url authority_note status published_url priority priority_band fits_groups citation_national related_prompt_id', ''),
    ('PATCH', '/media-placements/{placement_id}', 'name channel_type channel_key target_url authority_note status published_url priority priority_band fits_groups citation_national related_prompt_id', ''),
    ('DELETE', '/media-placements/{placement_id}', '', ''),
    ('POST', '/publishing-channels', 'tenant_id name channel_type publish_mode base_url content_rules enabled sort_order', 'project_id'),
    ('PATCH', '/publishing-channels/{channel_id}', 'name channel_type publish_mode base_url content_rules enabled sort_order', 'project_id'),
    ('DELETE', '/publishing-channels/{channel_id}', '', 'hard project_id'),
    ('POST', '/channel-accounts', 'tenant_id channel_id display_name auth_type', 'project_id'),
    ('PATCH', '/channel-accounts/{account_id}', 'display_name status', 'project_id'),
    ('DELETE', '/channel-accounts/{account_id}', '', 'hard project_id'),
    ('PUT', '/channel-polish-prompts', 'tenant_id system_prompt reset_system channels add_channel_key remove_channel_key', 'project_id'),
    ('POST', '/audits', 'tenant_id url', 'project_id'),
    ('POST', '/audits/{audit_id}/advice', '', ''),
    ('POST', '/audits/{audit_id}/assets', '', ''),
    ('POST', '/audits/{audit_id}/tickets', '', 'replace_open'),
    ('POST', '/audits/{audit_id}/verify', '', 'recrawl'),
    ('POST', '/structure-scan', '', 'website_url project_id'),
    ('POST', '/action-tickets', 'title priority action advice_code acceptance_type acceptance_check acceptance_desc media_placement_id audit_id owner_name due_date', 'project_id'),
    ('PATCH', '/action-tickets/{ticket_id}', 'status priority action acceptance_type acceptance_check acceptance_desc manual_pass owner_name due_date', 'project_id'),
    ('POST', '/action-tickets/{ticket_id}/verify', '', 'recrawl project_id'),
    ('POST', '/action-tickets/{ticket_id}/prepare-content', 'prompt_id', 'project_id'),
    ('POST', '/action-tickets/{ticket_id}/execution', 'content_task_id expected_article_id before_snapshot_ids after_snapshot_ids change_note', 'project_id'),
    ('POST', '/workbench/onsite-tasks', 'tenant_id project_id request_id work_type month owner_name', ''),
    ('POST', '/workbench/onsite-tasks/{task_id}/ai-proposal', 'tenant_id project_id expected_revision request_id mode', ''),
    ('POST', '/workbench/onsite-tasks/{task_id}/actions', 'tenant_id project_id expected_revision action items note owner_name', ''),
    ('POST', '/onboarding/preview', 'tenant_id website_url expand max_prompt_candidates', 'project_id'),
    ('POST', '/onboarding/apply', 'tenant_id website_url brand_terms businesses prompts facts create_website_channel dry_run', 'project_id'),
    ('POST', '/onboarding/sitemap-audit', '', 'website_url project_id'),
    ('POST', '/onboarding/sitemap-audit/create-tasks', 'items', 'project_id'),
    ('POST', '/daily-metrics/rebuild', '', 'metric_date date_from date_to include_empty_slices project_id'),
    ('POST', '/attribution/backfill', '', 'limit only_empty cursor_id project_id'),
    ('POST', '/deliverables/archives', 'pack title markdown', 'project_id'),
    ('POST', '/integration/tasks', 'module action_type title params status created_by assignee_role', 'project_id'),
    ('PATCH', '/integration/tasks/{task_id}', 'status', ''),
    ('POST', '/integration/tasks/{task_id}/baseline', '', ''),
    ('POST', '/integration/tasks/{task_id}/retest', '', ''),
    ('POST', '/integration/tasks/{task_id}/publication-check', 'publication_id', ''),
    ('PUT', '/projects/{project_id}/search-visibility/config', 'domains zh_url brand_terms core_terms extra_article_urls customer_visible', ''),
    ('POST', '/projects/{project_id}/search-visibility/run', '', ''),
    ('POST', '/content-imports/preview-url', 'tenant_id url', 'project_id'),
]
PREFIX = '/api/v1/geo'
LOOKUP = {(method, PREFIX + path): (frozenset(fields.split()), frozenset(query.split()))
          for method, path, fields, query in CONTRACTS}
FORM_ROUTES = {PREFIX + path for path in ('/facts/import', '/prompts/import-csv',
    '/reports/publication-links/preview', '/content-tasks/{task_id}/import-receipts')}
SUGGESTIONS = {PREFIX + p for p in ('/prompts/expand-candidates', '/audits/{audit_id}/advice',
    '/audits/{audit_id}/assets', '/answer-snapshots/suggest-fields', '/competitor-insights/report',
    '/workbench/onsite-tasks/{task_id}/ai-proposal', '/onboarding/preview', '/onboarding/sitemap-audit')}
MANUAL_CHECKS = {PREFIX + p for p in ('/answer-snapshots/probe', '/answer-snapshots/probe-batch',
    '/integration/tasks/{task_id}/retest', '/projects/{project_id}/search-visibility/run')}


def rules():
    from app.security.advisor_write_routes import WriteRule
    return {key: WriteRule(*key, fields, frozenset(), ('geo.assets', 'geo.content'), 'operations')
            for key, (fields, _query) in LOOKUP.items()}


async def read_contract(request, rule):
    fields, query = LOOKUP[(rule.method, rule.template)]
    seen = set()
    for key, value in request.query_params.multi_items():
        if key in seen or key not in query | {'tenant_id'}:
            deny(403, 'ADVISOR_WRITE_FIELD_FORBIDDEN', '请只提交这个操作支持的参数')
        seen.add(key)
        if key in {'hard', 'force', 'dry_run', 'only_terminal', 'replace_open', 'recrawl', 'only_empty',
                   'include_empty_slices'} and value not in {'true', 'false'}:
            deny(422, 'ADVISOR_WRITE_FIELD_FORBIDDEN', '开关只能填写 true 或 false')
    if rule.template in FORM_ROUTES:
        form = await request.form()
        if set(form) - {'file', 'pasted'} or len(list(form.multi_items())) != len(set(form)):
            deny(403, 'ADVISOR_WRITE_FIELD_FORBIDDEN', '上传参数含未开放字段')
        for upload in form.values():
            if hasattr(upload, 'file'):
                position = upload.file.tell()
                raw = await upload.read(2 * 1024 * 1024 + 1)
                await upload.seek(position)
                if len(raw) > 2 * 1024 * 1024:
                    deny(413, 'ADVISOR_UPLOAD_TOO_LARGE', '上传文件不能超过2MB')
        return {}
    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                deny(422, 'ADVISOR_WRITE_FIELD_FORBIDDEN', '参数不能重复')
            value[key] = item
        return value
    raw = await request.body()
    try:
        body = json.loads(raw, object_pairs_hook=unique) if raw.strip() else {}
    except (ValueError, UnicodeError):
        deny(422, 'ADVISOR_WRITE_FIELD_FORBIDDEN', '请提交有效JSON对象')
    check_fields(rule, body)
    # Validate required values before reserving a paid attempt. Keep the raw
    # object for the recursive reference guard; schema coercion must not hide IDs.
    from pydantic import BaseModel, ValidationError
    route = request.scope.get('route')
    schema = getattr(getattr(route, 'body_field', None), 'type_', None)
    if isinstance(schema, type) and issubclass(schema, BaseModel):
        try:
            schema.model_validate(body)
        except ValidationError:
            deny(422, 'ADVISOR_INVALID_OPERATION', '操作参数不完整或格式不正确，请核对后重试')
    return body


def check_fields(rule, body):
    if not isinstance(body, dict) or set(body) - rule.fields:
        deny(403, 'ADVISOR_WRITE_FIELD_FORBIDDEN', '此字段未向顾问开放')
    if rule.template in {PREFIX + '/publishing-channels', PREFIX + '/publishing-channels/{channel_id}'}:
        if body.get('publish_mode', 'manual_only') != 'manual_only':
            deny(403, 'ADVISOR_WRITE_FIELD_FORBIDDEN', '自动发布模式只能由平台管理员配置')
    if rule.template == PREFIX + '/channel-polish-prompts' and (
            body.get('add_channel_key') or body.get('remove_channel_key')):
        deny(403, 'ADVISOR_WRITE_FIELD_FORBIDDEN', '共享渠道的启停只能由平台管理员配置')
    forbidden = {'api_key', 'clear_api_key', 'credentials', 'credentials_encrypted', 'password',
                 'advisor_user_id', 'permissions', 'role_id', 'interval_days', 'interval_hours',
                 'model', 'api_base_url', 'engine_keys', 'auth_type'}
    if rule.method == 'POST' and rule.template == PREFIX + '/channel-accounts':
        if body.get('auth_type', 'manual') != 'manual':
            deny(403, 'ADVISOR_WRITE_FIELD_FORBIDDEN', '账号凭证和鉴权方式只能由管理员配置')
        forbidden -= {'auth_type'}
    def walk(value):
        if isinstance(value, dict):
            if set(value) & forbidden:
                deny(403, 'ADVISOR_WRITE_FIELD_FORBIDDEN', '系统配置只能由管理员修改')
            for item in value.values():
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)
    walk(body)


async def guard_shared_destinations(session, ctx, request, body, rule, projects):
    """A tenant-wide edit may not change another advisor's project.

    Shared customer data has no project foreign key. Metadata/manual-account
    operations remain available only when every affected project is assigned
    and active. Credential-bearing identities remain administrator managed.
    This guard runs again under the normal commit-time authority locks.
    """
    shared = {PREFIX + path for path in (
        '/publishing-channels', '/publishing-channels/{channel_id}',
        '/channel-accounts', '/channel-accounts/{account_id}', '/channel-polish-prompts',
        '/competitor-aliases')}
    if rule.template not in shared and not (
            rule.template == PREFIX + '/onboarding/apply' and (
                body.get('create_website_channel') or body.get('brand_terms'))):
        return
    from sqlalchemy import select
    from app.models import GeoProject, GeoChannelAccount, GeoPublishingChannel
    affected = set(await session.scalars(select(GeoProject.id).where(
        GeoProject.tenant_id == ctx.tenant_id).execution_options(advisor_scope_control=True)))
    if not affected or not affected.issubset(projects):
        deny(403, 'ADVISOR_ASSIGNMENT_REQUIRED', '此操作会修改客户共享设置，需要你负责该客户的全部有效项目。请让超管在「GEO → 项目管理」核对全部项目状态和「计划与待办 → 项目顾问」，或由超管处理。')
    account_id = request.path_params.get('account_id')
    if account_id:
        account = await session.scalar(select(GeoChannelAccount).where(
            GeoChannelAccount.id == int(account_id), GeoChannelAccount.tenant_id == ctx.tenant_id)
            .execution_options(advisor_scope_control=True))
        if account is None or account.auth_type != 'manual' or account.credentials_encrypted:
            deny(403, 'ADVISOR_WRITE_FIELD_FORBIDDEN', '带凭证的发布账号只能由平台管理员维护')
    channel_id = request.path_params.get('channel_id')
    if channel_id:
        channel = await session.scalar(select(GeoPublishingChannel).where(
            GeoPublishingChannel.id == int(channel_id), GeoPublishingChannel.tenant_id == ctx.tenant_id)
            .execution_options(advisor_scope_control=True))
        if channel is None or channel.publish_mode != 'manual_only':
            deny(403, 'ADVISOR_WRITE_FIELD_FORBIDDEN', '自动发布渠道只能由平台管理员维护')
        accounts = list(await session.scalars(select(GeoChannelAccount).where(
            GeoChannelAccount.channel_id == int(channel_id), GeoChannelAccount.tenant_id == ctx.tenant_id)
            .order_by(GeoChannelAccount.id).with_for_update()
            .execution_options(advisor_scope_control=True)))
        if any(a.auth_type != 'manual' or a.credentials_encrypted for a in accounts):
            deny(403, 'ADVISOR_WRITE_FIELD_FORBIDDEN', '带凭证账号的共享渠道只能由平台管理员维护')


async def guard_scope(session, ctx, request, body, rule):
    from app.security.advisor_write_objects import _resolve, _assignment_required
    from app.security.advisor_write_reads import assigned_scope
    from app.security.geo_advisor import check_manual_execution_scope
    await check_manual_execution_scope(session, ctx, rule)
    if session.info.pop('advisor_pending_business_binding', False):
        # The flush callback binds newly-created businesses to their project.
        # Persist it before populate_existing reloads the project authority.
        await session.flush()
    if session.info.get('advisor_scoped_write'):
        from app.models import GeoProject
        from sqlalchemy import select
        await session.scalars(select(GeoProject).where(GeoProject.tenant_id == ctx.tenant_id)
            .order_by(GeoProject.id).with_for_update().execution_options(
                populate_existing=True, advisor_scope_control=True))
    objects = await _resolve(session, ctx, request, body, rule)
    projects, businesses = await assigned_scope(session, ctx)
    await guard_shared_destinations(session, ctx, request, body, rule, projects)
    if not objects.projects and not objects.businesses and len(projects) == 1:
        objects.projects.update(projects)
    if objects.unscoped or not objects.projects.issubset(projects) or not objects.businesses.issubset(businesses):
        _assignment_required()
    if not objects.projects and not objects.businesses:
        deny(409, 'ADVISOR_PROJECT_SELECTION_REQUIRED', '请先选择一个已分配项目')
    from app.models import GeoProject
    from app.geo.project_scope import binding
    from sqlalchemy import select
    owners = set(objects.projects)
    for row in await session.scalars(select(GeoProject).where(GeoProject.id.in_(projects))
                                     .execution_options(advisor_scope_control=True)):
        if objects.businesses & set(binding(row)['business_ids']):
            owners.add(row.id)
    request.state.advisor_operation_projects = owners
    request.state.advisor_operation_businesses = frozenset(objects.businesses)
    if rule.template in MANUAL_CHECKS:
        from app.models import GeoTrackingEngine
        enabled = set(await session.scalars(select(GeoTrackingEngine.engine_key).where(
            GeoTrackingEngine.tenant_id == ctx.tenant_id, GeoTrackingEngine.enabled.is_(True))))
        requested = body.get('engines') or ([body['engine']] if body.get('engine') else [])
        if requested and not set(requested).issubset(enabled):
            deny(403, 'ADVISOR_WRITE_FIELD_FORBIDDEN', '只能使用管理员已启用的检测引擎')


async def reserve_quota(session, ctx, rule):
    from app.models import GeoAsyncJob
    from app.security.advisor_write_ai import reserve_suggestion
    # All suggestion entry points consume the same existing durable counter.
    if rule.template in SUGGESTIONS:
        await reserve_suggestion(session, ctx, SimpleNamespace(id=0))
    if rule.template in MANUAL_CHECKS:
        from app.geo.content.autopatrol import check_manual_quota
        from app.geo.content.patrol import count_patrol_runs_today
        from app.models import GeoVisibilityPatrolRun
        if rule.template == PREFIX + '/integration/tasks/{task_id}/retest':
            await check_manual_quota(session, ctx.tenant_id)
        elif await count_patrol_runs_today(session, ctx.tenant_id, created_by=ctx.user_id, exclude_auto=True) >= 10:
            deny(429, 'ADVISOR_VISIBILITY_DAILY_LIMIT', '今日其他 AI 检测操作额度已满')
        # A terminal reservation is not an executable patrol or a new table.
        if rule.template == PREFIX + '/integration/tasks/{task_id}/retest':
            return  # Its durable patrol row is itself the reservation.
        from app.security.advisor_quota import KEY, STATE
        reservation = GeoVisibilityPatrolRun(tenant_id=ctx.tenant_id, created_by=ctx.user_id,
            status='completed', trigger='manual', auto_persist=False, prefer_real=True,
            prompt_limit=1, summary={'reservation_only': True, STATE: 'reserved'})
        session.add(reservation)
        await session.commit()
        session.info[KEY] = (reservation.id, ctx.tenant_id, ctx.user_id)


async def bind_pending_scope(session, ctx, request, body):
    """Put newly imported rows into their actual project before the first flush."""
    from sqlalchemy import event, select
    from app import models as m
    from app.security.advisor_write_objects import _assignment_required
    projects = request.state.advisor_operation_projects
    project_id = next(iter(projects)) if len(projects) == 1 else None
    business_id = body.get('business_id') or request.query_params.get('business_id')
    unit_id = body.get('unit_id') or request.query_params.get('unit_id')
    scope = session.info['advisor_read_scope']
    referenced = request.state.advisor_operation_businesses
    if business_id is None and len(referenced) == 1:
        business_id = next(iter(referenced))
    if business_id is None and len(scope[2]) == 1:
        business_id = next(iter(scope[2]))
    if business_id is None:
        business_id = await session.scalar(select(m.GeoOptimizationBusiness.id).where(
            m.GeoOptimizationBusiness.id.in_(scope[2]), m.GeoOptimizationBusiness.status == 'active')
            .order_by(m.GeoOptimizationBusiness.id).limit(1))
    units = list(await session.scalars(select(m.GeoOptimizationUnit.id).where(
        m.GeoOptimizationUnit.business_id == int(business_id), m.GeoOptimizationUnit.status == 'active')
        .order_by(m.GeoOptimizationUnit.id))) if business_id else []
    if unit_id is None and units:
        unit_id = units[0]
    parent = await session.get(m.GeoProject, project_id) if project_id else None

    def before_flush(sync_session, _context, _instances):
        touched = session.info.setdefault('advisor_operation_touched', set())
        touched.update(sync_session.new)
        touched.update(sync_session.dirty)
        touched.update(sync_session.deleted)
        for row in list(sync_session.new):
            if isinstance(row, m.GeoFact) and row.business_id is None:
                if business_id is None:
                    _assignment_required()
                row.business_id = int(business_id)
            if isinstance(row, m.GeoPrompt) and row.unit_id is None:
                if unit_id is None:
                    _assignment_required()
                row.unit_id = int(unit_id)
            if isinstance(row, m.GeoCompetitorReport) and row.business_id is None:
                if business_id is None:
                    _assignment_required()
                row.business_id = int(business_id)
            if isinstance(row, m.GeoActionTicket) and project_id:
                progress = dict(row.progress or {})
                if 'onsite' not in progress:
                    progress['project_workflow'] = {**progress.get('project_workflow', {}), 'project_id': project_id}
                row.progress = progress
            if isinstance(row, m.GeoExpandRun):
                if project_id is None:
                    _assignment_required()
                row.roots = [{**root, 'advisor_project_id': project_id} for root in row.roots or [{}]]
            if isinstance(row, m.GeoVisibilityPatrolRun) and not (row.summary or {}).get('reservation_only'):
                summary = dict(row.summary or {})
                cells = (summary.get('contract_plan') or {}).get('cells') or []
                prompts = sorted({cell.get('prompt_id') for cell in cells})
                if not prompts or not set(prompts).issubset(session.info['advisor_read_prompt_ids']):
                    _assignment_required()
                summary['advisor_visibility_prompt_ids'] = prompts
                summary['advisor_visibility_auth'] = dict(user_id=ctx.user_id, tenant_id=ctx.tenant_id,
                    grant_id=ctx.advisor_scope.grant_id, auth_exp=session.info['advisor_scoped_write'][4])
                row.summary = summary
            if isinstance(row, m.GeoDeliverableArchive):
                if project_id is None:
                    _assignment_required()
                row.pack_json = {**row.pack_json, 'data_scope': {
                    **row.pack_json.get('data_scope', {}), 'project_id': project_id}}
            if isinstance(row, (m.GeoTrackingEngine, m.GeoAiSetting, m.GeoVisibilityPatrolSettings)):
                deny(403, 'ADVISOR_WRITE_FIELD_FORBIDDEN', '系统配置只能由管理员建立或修改')
        # Newly created business IDs are assigned by the database in this flush.
        session.info['advisor_new_businesses'] = [r for r in sync_session.new if isinstance(r, m.GeoOptimizationBusiness)]
        session.info['advisor_new_patrols'] = [r for r in sync_session.new if isinstance(r, m.GeoVisibilityPatrolRun)
            and not (r.summary or {}).get('reservation_only')]

    def after_flush(sync_session, _context):
        session.info['advisor_read_patrol_ids'].update(r.id for r in session.info.pop('advisor_new_patrols', []))
        new = session.info.pop('advisor_new_businesses', [])
        if new:
            if parent is None:
                _assignment_required()
            from app.geo.project_scope import binding
            settings = dict(parent.project_settings or {})
            current = binding(parent)
            settings['geo_business_scope'] = {**current, 'business_ids': sorted(
                set(current['business_ids']) | {r.id for r in new}), 'revision': current.get('revision', 0) + 1}
            parent.project_settings = settings
            session.info['advisor_pending_business_binding'] = True
            # Later queries in this same import must see the new business/unit,
            # rather than accidentally attach its questions to the old default.
            from app.security.advisor_read_scope import predicates
            _, project_ids, business_ids, _ = session.info['advisor_read_scope']
            business_ids = business_ids | frozenset(r.id for r in new)
            criteria = predicates(ctx, project_ids, business_ids, session.info['advisor_read_domains'],
                session.info['advisor_read_prompt_ids'], session.info['advisor_read_patrol_ids'])
            session.info['advisor_read_scope'] = (ctx, project_ids, business_ids, criteria)
            request.scope['geo_advisor_read_projects'] = (project_ids, business_ids)

    event.listen(session.sync_session, 'before_flush', before_flush)
    event.listen(session.sync_session, 'after_flush_postexec', after_flush)


async def verify_pending_scope(session, ctx):
    """Check handler-produced rows too; request IDs alone are not sufficient."""
    if not session.info.get('advisor_operation_touched'):
        return
    from sqlalchemy import and_, inspect, select
    from app.models import GeoAsyncJob, GeoVisibilityPatrolRun, GeoOptimizationBusiness, GeoProject
    from app.security.advisor_read_scope import predicates
    from app.security.advisor_write_reads import assigned_scope
    projects, businesses = await assigned_scope(session, ctx)
    projects &= set(session.info.get('advisor_operation_project_limit', projects))
    from app.geo.project_scope import binding
    rows = list(await session.scalars(select(GeoProject).where(GeoProject.id.in_(projects))
        .execution_options(advisor_scope_control=True)))
    businesses &= {bid for p in rows for bid in binding(p)['business_ids']}
    criteria = predicates(ctx, projects, businesses, session.info.get('advisor_read_domains', ()),
        session.info.get('advisor_read_prompt_ids', ()), session.info.get('advisor_read_patrol_ids', ()))
    session.info['advisor_read_scope'] = (ctx, frozenset(projects), frozenset(businesses), criteria)
    for row in session.info.get('advisor_operation_touched', set()):
        state = inspect(row)
        if state.deleted or not state.identity:
            continue
        # Counters have no content and are intentionally absent from read lists.
        if isinstance(row, GeoAsyncJob) and row.kind == 'advisor_suggest_brief' and (row.request_meta or {}).get('reservation_only'):
            continue
        if isinstance(row, GeoVisibilityPatrolRun) and (row.summary or {}).get('reservation_only'):
            continue
        condition = criteria.get(type(row))
        if condition is None:
            if hasattr(type(row), 'tenant_id') and row.tenant_id != ctx.tenant_id:
                deny(403, 'ADVISOR_ASSIGNMENT_REQUIRED', '写入对象不属于当前客户')
            continue
        table = state.mapper.local_table
        identity = [column == value for column, value in zip(state.mapper.primary_key, state.identity)]
        allowed = await session.scalar(select(table.c[next(iter(table.primary_key)).name]).where(
            and_(*identity), condition).execution_options(advisor_scope_control=True))
        if allowed is None:
            deny(403, 'ADVISOR_ASSIGNMENT_REQUIRED', '写入对象不属于分配给你的有效项目')


async def recheck_search_job(session, job):
    from starlette.requests import Request
    from app.security.advisor_scope import AdvisorScope
    from app.security.auth import AuthContext
    from app.security.advisor_write_commit import recheck_advisor_before_commit
    authority = (job.request_meta or {}).get('advisor_authority')
    if authority is None:
        return
    operation = PREFIX + '/projects/{project_id}/search-visibility/run'
    if (not isinstance(authority, dict) or authority.get('operation') != operation
            or authority.get('tenant_id') != job.tenant_id or authority.get('user_id') != job.created_by
            or type(authority.get('grant_id')) is not int or type(authority.get('expires_at')) not in {int, float}):
        deny(403, 'ADVISOR_GRANT_REVOKED', '顾问搜索检测的授权记录无效')
    ctx = AuthContext(job.created_by, '', '顾问', job.tenant_id, {'geo.assets': 'edit', 'geo.content': 'edit'},
        advisor_scope=AdvisorScope(frozenset({job.tenant_id}), job.tenant_id, authority['grant_id']))
    request = Request({'type': 'http', 'method': 'POST',
        'path': operation.replace('{project_id}', str(job.ref_id)), 'headers': [],
        'query_string': f'tenant_id={job.tenant_id}'.encode(), 'path_params': {'project_id': job.ref_id},
        'route': SimpleNamespace(path=operation)})
    request.scope['geo_advisor_actor'] = (ctx.user_id, ctx.tenant_id)
    session.info['advisor_scoped_write'] = (ctx, request, {}, rules()[('POST', operation)], authority['expires_at'])
    await recheck_advisor_before_commit(session, ctx)
