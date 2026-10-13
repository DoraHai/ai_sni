"""Named-user preparation for the single Nord site; no publication or DDL."""
from typing import Literal
from uuid import UUID
from datetime import date
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from app.database import get_session
from app.security.auth import require_auth
from app.api.distribution import PrivateRoute, named
from app.models.seo import SeoSiteAdvisorAssignment, SeoDistributionConnection
from app.seo_distribution import platform_definition
from app import distribution_control as core

router = APIRouter(prefix='/api/distribution/nord/v1', route_class=PrivateRoute)

class Prepare(BaseModel):
    model_config = ConfigDict(extra='forbid')
    device_id: UUID
    external_account_id: str = Field(pattern=r'^gh_[a-f0-9]{12}$')
    confirm_account_ownership: Literal[True]
    confirm_current_advisor: Literal[True]

async def context(db, ctx, device_id, account):
    fresh = await named(db, ctx, admin=True)
    if not all(fresh.can_edit(k) for k in ('seo.content', 'seo.site')):
        raise HTTPException(403, '需要当前实名管理员具有 SEO 内容和网站编辑权限')
    device = await core.one(db, 'SELECT id FROM distribution_devices WHERE id=:id AND active', id=str(device_id))
    site = await core.one(db, 'SELECT s.id,s.status,s.site_settings,m.module_code,m.tenant_id AS module_tenant,'
                             'm.status AS module_status,m.expires_at FROM seo_sites s '
                             'JOIN tenant_modules m ON m.id=s.tenant_module_id WHERE s.id=1 AND s.tenant_id=1')
    conflict = await core.one(db, 'SELECT id FROM distribution_bindings WHERE platform=:p '
                              'AND external_account_id=:a AND tenant_id<>1 LIMIT 1', p='wechat-article', a=account)
    if conflict:
        raise HTTPException(409, '这个公众号已绑定其他客户')
    if not device or not site or site['status'] != 'active':
        raise HTTPException(409, '诺德网站或已配对执行电脑不可用')
    plan = (site['site_settings'] or {}).get('seo_service_plan') if isinstance(site['site_settings'], dict) else None
    if (site['module_code'] != 'seo' or site['module_tenant'] != 1 or
            site['module_status'] not in ('active', 'trial') or
            site['expires_at'] and site['expires_at'] < date.today() or
            isinstance(plan, dict) and plan.get('status') == 'paused'):
        raise HTTPException(409, '诺德 SEO 模块或服务计划当前不可运营')
    return fresh

async def state(db, fresh, account):
    assignment = await db.scalar(select(SeoSiteAdvisorAssignment).where(
        SeoSiteAdvisorAssignment.tenant_id == 1, SeoSiteAdvisorAssignment.site_id == 1,
        SeoSiteAdvisorAssignment.advisor_user_id == fresh.user_id,
        SeoSiteAdvisorAssignment.active.is_(True)))
    connection = await db.scalar(select(SeoDistributionConnection).where(
        SeoDistributionConnection.tenant_id == 1,
        SeoDistributionConnection.name == '诺德公众号 · ' + account))
    if connection and (connection.platform_code != 'wechat_browser' or
                       connection.mode != 'assisted' or not connection.enabled or connection.status != 'ready'):
        raise HTTPException(409, '既有账号连接状态不匹配，请核对；不会覆盖旧连接')
    return {'schema': 1, 'module': 'seo', 'tenant_id': 1, 'scope_id': 1,
            'external_account_id': account, 'advisor_user_id': fresh.user_id,
            'advisor_assigned': assignment is not None,
            'connection_id': connection.id if connection else None,
            'automatic_publish': False, 'publication_verified': False}

@router.get('/preparation')
async def preparation(device_id: UUID, external_account_id: str = Query(pattern=r'^gh_[a-f0-9]{12}$'),
                      db=Depends(get_session), ctx=Depends(require_auth)):
    fresh = await context(db, ctx, device_id, external_account_id)
    return await state(db, fresh, external_account_id)

@router.post('/preparation')
async def prepare(req: Prepare, db=Depends(get_session), ctx=Depends(require_auth)):
    fresh = await context(db, ctx, req.device_id, req.external_account_id)
    await core.lock(db, 'nord-setup:' + req.external_account_id)
    current = await state(db, fresh, req.external_account_id)
    # Native metadata models, one transaction; approvals and publication remain untouched.
    if not current['advisor_assigned']:
        assignment = await db.scalar(select(SeoSiteAdvisorAssignment).where(
            SeoSiteAdvisorAssignment.tenant_id == 1, SeoSiteAdvisorAssignment.site_id == 1,
            SeoSiteAdvisorAssignment.advisor_user_id == fresh.user_id).with_for_update())
        if assignment is None:
            assignment = SeoSiteAdvisorAssignment(tenant_id=1, site_id=1,
                advisor_user_id=fresh.user_id, active=True, assigned_by=fresh.user_id)
            db.add(assignment)
        else:
            assignment.active = True
            assignment.assigned_by = fresh.user_id
        await db.flush()
    await core.authorize_scope(db, fresh.user_id, {'module': 'seo', 'tenant_id': 1, 'scope_id': 1})
    if current['connection_id'] is None:
        definition = platform_definition('wechat_browser')
        if not definition.get('available') or definition['mode'] != 'assisted':
            raise HTTPException(409, '公众号浏览器连接能力不可用')
        db.add(SeoDistributionConnection(tenant_id=1, platform_code='wechat_browser',
            name='诺德公众号 · ' + req.external_account_id, mode='assisted',
            capabilities=definition['capabilities'], has_credentials=False,
            enabled=True, status='ready', created_by=fresh.user_id))
    await core.audit(db, fresh.user_id, 'nord_setup_prepared',
                     {'module': 'seo', 'tenant_id': 1, 'scope_id': 1,
                      'device_id': str(req.device_id), 'platform': 'wechat-article'}, 'PREPARED')
    await db.commit()
    return await state(db, fresh, req.external_account_id)
