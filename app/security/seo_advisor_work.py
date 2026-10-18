"""Exact SEO daily-work admission; authorization settings are never included."""
from datetime import date

from fastapi import HTTPException
from sqlalchemy import select


# Each entry is reviewed as a method, mounted route template and body fields.
# Separate batches append entries here; no URL-prefix admission is permitted.
DAILY = (
    ('PATCH', '/rank-serp/brand-profile', 'tenant_id site_id brand_name website', 'seo.keywords'),
    ('POST', '/qa/research/file-preview', '', 'seo.content'),
    ('POST', '/backlinks/import', '', 'seo.links'),
    ('POST', '/site/page-captures/upload', 'tenant_id site_id relation_type relation_id', 'seo.site'),
    ('POST', '/tasks', 'tenant_id site_id module action_type title params created_by assignee_role', 'seo.content'),
    ('PATCH', '/tasks/{task_id}', 'tenant_id site_id title status note', 'seo.content'),
    ('POST', '/workbench/notifications/read', 'tenant_id site_id task_id event_id', 'seo.content seo.site'),
    ('POST', '/overview/metric-snapshots', 'tenant_id site_id metric_type dimension numeric_value text_value unit source data_quality status error_message observed_at', 'seo.dashboard'),
    ('POST', '/keywords', 'tenant_id site_id keyword cluster intent monthly_volume difficulty priority landing_page status notes', 'seo.keywords'),
    ('POST', '/keywords/import', 'tenant_id site_id items', 'seo.keywords'),
    ('PATCH', '/keywords/{keyword_id}', 'site_id cluster intent monthly_volume difficulty priority landing_page status notes', 'seo.keywords'),
    ('POST', '/rank-snapshots', 'engine tenant_id site_id keyword_id device region domain subject_type rank result_url checked_at source', 'seo.keywords'),
    ('POST', '/rank-snapshots/batch', 'tenant_id items', 'seo.keywords'),
    ('POST', '/rank-serp/collect', 'engine tenant_id site_id keyword_ids devices max_keywords use_ai', 'seo.keywords'),
    ('PATCH', '/rank-serp/results/{result_id}', 'tenant_id site_id ownership_type create_asset', 'seo.keywords'),
    ('POST', '/site/crawl-runs', 'tenant_id site_id max_urls max_depth seed_urls include_known_pages', 'seo.site'),
    ('POST', '/site-pages/suggestions/generate', 'tenant_id site_id page_ids overwrite', 'seo.site'),
    ('POST', '/site-pages', 'tenant_id site_id url page_type target_keyword_id title_suggestion description_suggestion', 'seo.site'),
    ('POST', '/site-pages/import', 'tenant_id site_id urls', 'seo.site'),
    ('POST', '/site-pages/audit-pending', '', 'seo.site'),
    ('PATCH', '/site-pages/{page_id}', 'page_type target_keyword_id title_suggestion description_suggestion status', 'seo.site'),
    ('POST', '/site-pages/{page_id}/audit', '', 'seo.site'),
    ('POST', '/content-distribution/variants', 'tenant_id site_id content_id connection_id source_version title content status ai_generated instruction feedback', 'seo.content'),
    ('POST', '/backlinks', 'tenant_id site_id source_url target_url anchor_text authority_score toxic_score status first_seen_at last_seen_at', 'seo.links'),
    ('POST', '/backlinks/opportunities/query', 'tenant_id site_id competitors', 'seo.links'),
    ('POST', '/backlinks/query-index', 'tenant_id site_id', 'seo.links'),
    ('POST', '/backlinks/discover', 'tenant_id site_id source_url publication_id', 'seo.links'),
    ('POST', '/backlinks/{backlink_id}/verify', 'tenant_id site_id', 'seo.links'),
    ('PATCH', '/backlinks/{backlink_id}/monitoring', 'tenant_id site_id enabled', 'seo.links'),
    ('POST', '/backlinks/referrals', 'tenant_id site_id source_url visits conversions date_from date_to source', 'seo.links'),
    ('POST', '/internal-links/crawl', '', 'seo.links'),
    ('POST', '/competitors', 'tenant_id site_id name domain notes', 'seo.competitors'),
    ('POST', '/competitors/{competitor_id}/collect', 'tenant_id site_id max_pages', 'seo.competitors'),
    ('POST', '/competitors/events', 'tenant_id site_id competitor_id event_type title url source_url summary event_at', 'seo.competitors'),
    ('POST', '/workbench/onsite-tasks', 'tenant_id site_id request_id work_type month keyword_ids page_ids owner_name', 'seo.content seo.site'),
    ('POST', '/workbench/onsite-tasks/{task_id}/actions', 'action expected_revision items note owner_name tenant_id site_id', 'seo.content seo.site'),
    ('POST', '/qa/questions/import/preview', 'tenant_id site_id items csv preview_token', 'seo.content'),
    ('POST', '/qa/questions/import', 'tenant_id site_id items csv preview_token', 'seo.content'),
    ('POST', '/qa/questions/discover', 'tenant_id site_id', 'seo.content'),
    ('PATCH', '/qa/questions/{question_id}', 'tenant_id site_id version topic intent relevance status owner', 'seo.content'),
    ('POST', '/qa/questions/batch', 'tenant_id site_id items changes', 'seo.content'),
    ('POST', '/qa/answers', 'tenant_id site_id question_id format body fact_ids content_version expected_question_version expected_facts', 'seo.content'),
    ('PATCH', '/qa/answers/{answer_id}', 'tenant_id site_id question_id format body fact_ids content_version expected_question_version expected_facts', 'seo.content'),
    ('POST', '/qa/placements', 'tenant_id site_id answer_id platform question_url scheduled_at', 'seo.content'),
    ('POST', '/qa/placements/{placement_id}/verify', 'tenant_id site_id', 'seo.content'),
    ('POST', '/qa/placements/{placement_id}/metrics', 'tenant_id site_id version views likes comments source_url as_of', 'seo.content'),
    ('POST', '/qa/research/{operation_id}/accept', 'tenant_id site_id indices', 'seo.content'),
    ('POST', '/site/page-captures', 'tenant_id site_id url relation_type relation_id', 'seo.site'),
    ('PUT', '/site/reports/monthly-template', 'tenant_id site_id sections', 'seo.site'),
    ('PUT', '/site/publications/export-template', 'tenant_id site_id columns', 'seo.site'),
    ('PUT', '/site/tdk-review/template', 'tenant_id site_id sections columns', 'seo.site'),
    ('POST', '/site/tdk-review/export', 'tenant_id site_id page_ids format trigger_capture', 'seo.site'),
    ('PUT', '/site-pages/image-remediation', 'tenant_id site_id page_id expected_snapshot_id expected_review_id expected_review_version position decision alt_suggestion note review_status', 'seo.site'),
    ('POST', '/site-pages/image-remediation/copy', 'tenant_id site_id page_id expected_snapshot_id source_snapshot_id expected_source_version', 'seo.site'),
    ('POST', '/site-pages/image-remediation/reuse', 'tenant_id site_id page_id expected_snapshot_id expected_reuse_version', 'seo.site'),
    ('POST', '/site-pages/index-reviews', 'tenant_id site_id page_id expected_review_id intent reason', 'seo.site'),
    ('POST', '/image-verifications/{verification_id}/retry', '', 'seo.content seo.site'),
    ('POST', '/traffic/gsc/test', 'tenant_id site_id days', 'seo.site'),
    ('POST', '/traffic/gsc/collect', 'tenant_id site_id days', 'seo.site'),
    ('POST', '/overview/collect-metrics', 'tenant_id site_id', 'seo.dashboard'),
    ('POST', '/site/analytics-sources/{source}/test', 'tenant_id site_id', 'seo.site'),
    ('POST', '/site/analytics/pull', 'tenant_id site_id month source', 'seo.site'),
)


AI = (
    ('POST', '/qa/batches', 'tenant_id site_id request_id items', 'seo.content'),
    ('POST', '/qa/batches/{batch_id}/control', 'tenant_id site_id action question_id', 'seo.content'),
    ("POST", '/qa/planning/semantic', 'tenant_id site_id items request_id', 'seo.content'),
    ("POST", '/qa/research/draft', 'tenant_id site_id request_id question facts format', 'seo.content'),
    ("POST", '/qa/research/extract', 'tenant_id site_id request_id text source_name source_url', 'seo.content'),
    ("POST", '/qa/research/quality', 'tenant_id site_id request_id answer_id content_version', 'seo.content'),
    ("POST", '/site/pages/ai-tdk/generate', 'tenant_id site_id page_ids force', 'seo.site seo.content'),
    ("POST", '/content-ai/assist', 'request_id tenant_id site_id source_page_id action mode keyword_id keyword_ids title outline draft source_text instruction template engine qa_question_id qa_fact_ids qa_format', 'seo.content'),
    ("POST", '/content-distribution/adapt', 'request_id tenant_id site_id content_id connection_id use_ai instruction', 'seo.content'),
    ("POST", '/content-distribution/variants/generate', 'tenant_id site_id pairs use_ai instruction submit_for_review', 'seo.content'),
)
AI += (
    ("POST", '/site-pages/image-remediation/ai-drafts', 'tenant_id site_id items', 'seo.site seo.content'),
    ("POST", '/site-pages/ai-remediation', 'tenant_id site_id page_id', 'seo.site seo.content'),
    ("POST", '/workbench/assistant/chat', 'tenant_id site_id request_id message history content_id', 'seo.site seo.content'),
    ("POST", '/workbench/onsite-tasks/{task_id}/ai-proposal', 'tenant_id site_id expected_revision request_id mode', 'seo.site seo.content'),
)

def workflow_rules(rule_type):
    return [rule_type(method, "/api/v1/seo" + path, frozenset(fields.split()),
                      frozenset(), tuple(permissions.split()), "site", True)
            for method, path, fields, permissions in DAILY + AI]


def deny(code="ADVISOR_OBJECT_UNAVAILABLE", status=403):
    raise HTTPException(status, {"code": code})


_CONTROL = frozenset({
    "owner_user_id", "advisor_user_id", "project_id", "role_id", "permissions",
    "grants", "credentials", "secrets", "clear_secrets", "model", "provider",
    "content_ai_model", "content_ai_provider", "interval_days", "frequency",
    "verified_by", "verified_at", "public_use_allowed",
})


def check_workflow_fields(rule, body):
    if not isinstance(body, dict) or set(body) - rule.fields:
        deny("ADVISOR_WRITE_FIELD_FORBIDDEN")

    def walk(value, depth=0):
        if depth > 32:
            deny("ADVISOR_WRITE_FIELD_FORBIDDEN")
        if isinstance(value, dict):
            if set(value) & _CONTROL:
                deny("ADVISOR_WRITE_FIELD_FORBIDDEN")
            for item in value.values():
                walk(item, depth + 1)
        elif isinstance(value, list):
            for item in value:
                walk(item, depth + 1)
    walk(body)
    if rule.template in {"/api/v1/seo/content-assets", "/api/v1/seo/content-assets/{content_id}"}:
        if body.get("status", "drafting") not in {"planned", "drafting", "archived"}:
            deny("ADVISOR_WRITE_STATE_FORBIDDEN")
    if rule.method in {"PATCH", "PUT"}:
        version = "version_count" if "/content-assets/" in rule.template else "version" if "/qa/facts/" in rule.template else None
        if version and (type(body.get(version)) is not int or body[version] < 1):
            deny("ADVISOR_WRITE_VERSION_REQUIRED", 422)
    if body.get("actor_mode") not in {None, "advisor_proxy"}:
        deny("ADVISOR_WRITE_FIELD_FORBIDDEN")
    if rule.template == '/api/v1/seo/tasks' and body.get('assignee_role', 'advisor') != 'advisor':
        deny('ADVISOR_WRITE_FIELD_FORBIDDEN')


TABLES = {
    "tenant_id": "tenants", "site_id": "seo_sites",
    "keyword_id": "seo_keyword_assets", "target_keyword_id": "seo_keyword_assets",
    "content_id": "seo_content_assets", "content_asset_id": "seo_content_assets",
    "page_id": "seo_site_pages", "source_page_id": "seo_site_pages",
    "fact_id": "seo_qa_facts", "qa_fact_id": "seo_qa_facts",
    "question_id": "seo_questions", "qa_question_id": "seo_questions",
    "answer_id": "seo_qa_answers", "placement_id": "seo_qa_placements",
    "asset_id": "seo_brand_assets", "task_id": "seo_tasks",
    "batch_id": "seo_qa_batches", "operation_id": "seo_ai_operations",
    "run_id": "seo_automation_runs", "publication_id": "seo_content_publications",
    "variant_id": "seo_distribution_variants", "connection_id": "seo_distribution_connections",
    "backlink_id": "seo_backlinks", "competitor_id": "seo_competitors",
    "capture_id": "seo_page_captures", "snapshot_id": "seo_page_snapshots",
    "expected_snapshot_id": "seo_page_snapshots", "source_snapshot_id": "seo_page_snapshots",
    "review_id": "seo_image_alt_reviews", "expected_review_id": "seo_image_alt_reviews",
    "index_review_id": "seo_page_index_reviews",
    "suggestion_id": "seo_page_ai_tdk_suggestions", "result_id": "seo_serp_results",
    "verification_id": "seo_image_verifications", "retry_page_id": "seo_site_pages",
    "article_id": "seo_content_assets", "before_snapshot_id": "seo_page_snapshots",
    'conversation_id': 'seo_content_conversations', 'last_read_message_id': 'seo_content_messages',
}
# Stored ownership links are followed even when omitted from a partial update.
LINKS = {
    'seo_content_messages': ('conversation_id',),
    'seo_content_conversations': ('content_asset_id',),
    "seo_content_assets": ("keyword_id", "keyword_ids", "source_page_id"),
    "seo_site_pages": ("target_keyword_id",),
    "seo_qa_answers": ("question_id", "content_id"),
    "seo_qa_placements": ("answer_id",),
    "seo_distribution_variants": ("content_asset_id", "connection_id"),
    "seo_content_publications": ("content_asset_id", "connection_id"),
    "seo_image_verifications": ("page_id", "review_id"),
}


def references(value, template, parent="", refs=None, depth=0):
    refs = [] if refs is None else refs
    if depth > 32 or len(refs) > 10000:
        deny()
    if isinstance(value, dict):
        for key, item in value.items():
            if item is None:
                continue
            kind = key[:-1] if key.endswith("_ids") else key
            if key == "expected_review_id" and template == "/api/v1/seo/site-pages/index-reviews":
                kind = "index_review_id"
            if key == "request_id" or (key == 'event_id' and template == '/api/v1/seo/workbench/notifications/read') or key == 'opportunity_request_id':
                continue  # An idempotency key, never a business object.
            if key == 'item_id' and template == '/api/v1/seo/content-distribution/video/publications/{publication_id}/recover':
                continue  # Provider's work identifier, validated by the existing recovery handler.
            if key == "relation_id":
                kind = {"site_page": "page_id", "publication": "publication_id"}.get(value.get("relation_type"))
                if kind is None:
                    deny()
            if key == "id":
                if parent in {"facts", "expected_facts"}:
                    kind = "fact_id"
                elif parent == 'question' or template in {"/api/v1/seo/qa/questions/batch", "/api/v1/seo/qa/planning/semantic", "/api/v1/seo/qa/batches"}:
                    kind = "question_id"
                elif template == "/api/v1/seo/workbench/onsite-tasks/{task_id}/actions":
                    continue  # Workflow item labels such as title-15, not row IDs.
                else:
                    deny()
            if key == "id" or key.endswith(("_id", "_ids")):
                if kind not in TABLES:
                    deny()
                entries = item if key.endswith("_ids") else [item]
                if not isinstance(entries, list):
                    deny("ADVISOR_INVALID_OBJECT_ID", 422)
                refs.extend((kind, entry) for entry in entries)
            else:
                references(item, template, key, refs, depth + 1)
    elif isinstance(value, list):
        for item in value:
            references(item, template, parent, refs, depth + 1)
    return refs


async def workflow_scope(session, ctx, request, body, rule, *, lock=False):
    from app.database import Base
    from app.security.advisor_write_objects import _positive_id
    ctx.ensure_tenant(ctx.tenant_id)
    refs = references(dict(request.path_params), rule.template)
    for key, value in request.query_params.multi_items():
        references({key: value}, rule.template, refs=refs)
    references(body, rule.template, refs=refs)
    seen, sites = set(), set()
    index = 0
    while index < len(refs):
        kind, value = refs[index]
        index += 1
        table_name = TABLES[kind]
        table = Base.metadata.tables.get(table_name)
        if table is None:
            deny()
        object_id = str(value) if table.c.id.type.python_type is str else _positive_id(value)
        if (table_name, object_id) in seen:
            continue
        seen.add((table_name, object_id))
        query = select(table).where(table.c.id == object_id)
        if table_name == 'seo_content_messages':
            conversations = Base.metadata.tables['seo_content_conversations']
            query = select(table, conversations.c.tenant_id, conversations.c.site_id).join(
                conversations, conversations.c.id == table.c.conversation_id).where(table.c.id == object_id)
        if lock:
            query = query.with_for_update(read=True)
        row = (await session.execute(query)).mappings().first()
        if row is None:
            deny("ADVISOR_OBJECT_NOT_FOUND", 404)
        ctx.ensure_tenant(row["id"] if kind == "tenant_id" else row["tenant_id"])
        if kind == "site_id":
            sites.add(row["id"])
        elif "site_id" in row:
            if row["site_id"] is None:
                deny()
            sites.add(row["site_id"])
        for key in LINKS.get(table_name, ()):
            if row[key] is not None:
                references({key: row[key]}, rule.template, refs=refs)
        if len(refs) > 10000:
            deny()
    if len(sites) != 1:
        deny("ADVISOR_ASSIGNMENT_REQUIRED")
    request.state.seo_advisor_evidence = {
        **getattr(request.state, "seo_advisor_evidence", {}),
        "objects": sorted([list(item) for item in seen], key=str),
    }
    site_id = sites.pop()
    request.state.seo_advisor_site_id = site_id
    return site_id


async def lock_workflow_scope(session, ctx, request, body, rule):
    from app.models.module_workspace import SeoSite, TenantModule
    from app.models.seo import SeoSiteAdvisorAssignment
    site_id = await workflow_scope(session, ctx, request, body, rule)
    assignment = await session.scalar(select(SeoSiteAdvisorAssignment.id).where(
        SeoSiteAdvisorAssignment.tenant_id == ctx.tenant_id,
        SeoSiteAdvisorAssignment.site_id == site_id,
        SeoSiteAdvisorAssignment.advisor_user_id == ctx.user_id,
        SeoSiteAdvisorAssignment.active.is_(True),
    ).with_for_update(read=True))
    if assignment is None:
        deny("ADVISOR_ASSIGNMENT_REQUIRED")
    site = (await session.execute(select(SeoSite.__table__).where(
        SeoSite.id == site_id, SeoSite.tenant_id == ctx.tenant_id,
    ).with_for_update())).mappings().first()
    module = (await session.execute(select(TenantModule.__table__).where(
        TenantModule.id == site["tenant_module_id"], TenantModule.tenant_id == ctx.tenant_id,
        TenantModule.module_code == "seo",
    ).with_for_update())).mappings().first() if site else None
    if (site is None or site["status"] != "active" or module is None
            or module["status"] not in {"active", "trial"}
            or (module["expires_at"] is not None and module["expires_at"] < date.today())):
        deny("ADVISOR_OBJECT_UNAVAILABLE")
    await workflow_scope(session, ctx, request, body, rule, lock=True)
