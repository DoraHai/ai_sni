"""Named-user preparation for the single Nord site; no publication or DDL."""
from typing import Literal
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from app.database import get_session
from app.security.auth import require_auth
from app.api.distribution import PrivateRoute, named
from app.api.seo import (AdvisorAssignmentRequest, DistributionConnectionCreate,
                        upsert_advisor_assignment, create_distribution_connection)
from app.models.seo import SeoSiteAdvisorAssignment, SeoDistributionConnection
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
    site = await core.one(db, 'SELECT id,status FROM seo_sites WHERE id=1 AND tenant_id=1')
    conflict = await core.one(db, 'SELECT id FROM distribution_bindings WHERE platform=:p '
                              'AND external_account_id=:a AND tenant_id<>1 LIMIT 1', p='wechat-article', a=account)
    if conflict:
        raise HTTPException(409, '这个公众号已绑定其他客户')
    if not device or not site or site['status'] != 'active':
        raise HTTPException(409, '诺德网站或已配对执行电脑不可用')
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
    # Native operations commit separately. A response loss requires GET reconciliation.
    if not current['advisor_assigned']:
        await upsert_advisor_assignment(AdvisorAssignmentRequest(
            tenant_id=1, site_id=1, advisor_user_id=fresh.user_id, active=True), session=db, ctx=fresh)
    if current['connection_id'] is None:
        await create_distribution_connection(DistributionConnectionCreate(
            tenant_id=1, platform_code='wechat_browser', name='诺德公众号 · ' + req.external_account_id,
            enabled=True), session=db, ctx=fresh)
    await core.audit(db, fresh.user_id, 'nord_setup_prepared',
                     {'module': 'seo', 'tenant_id': 1, 'scope_id': 1,
                      'device_id': str(req.device_id), 'platform': 'wechat-article'}, 'PREPARED')
    await db.commit()
    return await state(db, fresh, req.external_account_id)
