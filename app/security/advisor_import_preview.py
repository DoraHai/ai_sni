"""Exact read-only article-preview authorization, without CSV/JSON ID scanning."""
from sqlalchemy import select
from starlette.datastructures import UploadFile

from app.security.advisor_scope import deny


FILE_PREVIEW = '/api/v1/geo/content-imports/preview-file'
PREVIEW_ROUTES = frozenset({('POST', FILE_PREVIEW)})
EDIT_KEYS = ('geo.assets', 'geo.content')


async def guard_import_preview(session, ctx, request, claims):
    from app.config import get_settings
    from app.models import GeoProject
    from app.module_scope import ensure_module_access
    from app.security.geo_advisor import positive_id

    template = getattr(request.scope.get('route'), 'path', None)
    if (request.method, template) not in PREVIEW_ROUTES:
        deny(403, 'ADVISOR_ROUTE_UNAVAILABLE', '此预览入口尚未开放')
    if not get_settings().advisor_scoped_content_writes_enabled:
        deny(403, 'ADVISOR_HIGH_RISK_WRITES_DISABLED', '顾问导入暂未开放')
    if ctx.advisor_scope is None or claims.get('scope_kind') != 'advisor_tenant':
        deny(403, 'ADVISOR_TENANT_REQUIRED', '请先选择已授权客户')
    ctx.ensure_tenant(ctx.tenant_id)
    if not request.query_params.getlist('tenant_id'):
        deny(403, 'ADVISOR_TENANT_REQUIRED', '请求必须指定当前客户')
    for key, value in request.query_params.multi_items():
        if key != 'tenant_id':
            deny(403, 'ADVISOR_WRITE_FIELD_FORBIDDEN', '此查询字段未向顾问开放')
        ctx.ensure_tenant(positive_id(value))
    if not all(ctx.can_edit(key) for key in EDIT_KEYS):
        deny(403, 'ADVISOR_ROUTE_UNAVAILABLE', '当前角色无编辑权限')
    await ensure_module_access(session, ctx, ctx.tenant_id, 'geo')
    projects = await session.scalars(select(GeoProject).where(
        GeoProject.tenant_id == ctx.tenant_id, GeoProject.status == 'active'
    ).execution_options(populate_existing=True))
    assigned = False
    for project in projects:
        settings = project.project_settings
        plan = settings.get('geo_service_plan') if isinstance(settings, dict) else None
        if (isinstance(plan, dict) and type(plan.get('advisor_user_id')) is int
                and plan['advisor_user_id'] == ctx.user_id):
            assigned = True
            break
    if not assigned:
        deny(403, 'ADVISOR_ASSIGNMENT_REQUIRED', '需要当前客户下的有效项目分配')
    if request.headers.get('content-type', '').split(';', 1)[0].lower() != 'multipart/form-data':
        deny(403, 'ADVISOR_WRITE_FIELD_FORBIDDEN', '文件预览仅支持单个上传文件')
    form = await request.form()
    items = list(form.multi_items())
    if len(items) != 1 or items[0][0] != 'file' or not isinstance(items[0][1], UploadFile):
        deny(403, 'ADVISOR_WRITE_FIELD_FORBIDDEN', '文件预览仅支持单个上传文件')
    # No commit hook: extraction is read-only. Delivery still rechecks live
    # account/grant/module/menu authority using the existing middleware.
    request.scope['geo_advisor_delivery'] = (ctx.user_id, dict(claims), ctx.tenant_id, frozenset(EDIT_KEYS))
