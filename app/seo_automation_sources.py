"""Server-owned v2 bindings. Reads never queue work or expose plan contents."""
from sqlalchemy import select,text

from app import automation_projects as core, automation_project_v2 as v2
from app.automation_project_contract import ConfigurationV2
from app.models.seo_cockpit import SeoTask
from app.models.seo import SeoKeywordAsset,SeoSitePage
from app.seo_content_workflow import plan_for

# Only operations with complete dispatch and legacy gates belong here.
OPERATIONS = ('onsite_ai', 'ranking_collect', 'indexation_collection', 'content_draft', 'site_diagnosis', 'incremental_diagnosis', 'monthly_onsite_plan', 'monthly_report')
RANK_VARIANTS = ('baidu_desktop', 'baidu_mobile', 'qihu360_desktop', 'qihu360_mobile', 'sogou_desktop', 'sogou_mobile')


def plan_version(site):
    plan = plan_for(site)
    revision = plan.get('revision', 0)
    if type(revision) is not int or revision < 0:
        raise core.problem('automation_source_invalid', '服务计划版本无效')
    return {'revision': revision, 'sha256': v2.fingerprint({
        'domain': site.canonical_domain, 'plan': plan})}


async def target_for(db, site, operation, object_id, *, variant=None, lock=False):
    from app.api.seo_onsite import ACTION_TYPE
    from app import seo_onsite_ai as ai
    if operation not in OPERATIONS:
        raise core.problem('automation_operation_unsupported', '该操作尚未完成自动接管', 422)
    if operation=='monthly_report':
        row=await db.get(SeoTask,object_id,populate_existing=True,**({'with_for_update':True} if lock else {}))
        if (not row or (row.tenant_id,row.site_id,row.action_type)!=(site.tenant_id,site.id,'monthly_report')
                or row.status not in {'open','in_progress'} or variant is not None or row.params.get('report')):
            raise core.problem('automation_report_ineligible','需要当前网站尚未冻结的月报任务')
        return {'operation':operation,'object_type':'report_task','object_id':row.id,'source_revision':0,
            'source_hash':v2.fingerprint(await report_source(db,site,row.params['month'],lock=lock)),'variant':None}
    if operation=='site_diagnosis':
        row=await db.get(SeoSitePage,object_id,populate_existing=True,
            **({'with_for_update':True} if lock else {}))
        from app.seo_incremental_crawl import scoped_url,site_hosts
        if not row or (row.tenant_id,row.site_id)!=(site.tenant_id,site.id) or variant is not None:
            raise core.problem('automation_page_not_found','页面不属于当前网站',404)
        if not scoped_url(row.url,site_hosts(site.canonical_domain)):
            raise core.problem('automation_target_invalid','页面地址超出当前网站范围')
        return {'operation':operation,'object_type':'page','object_id':row.id,'source_revision':0,
            'source_hash':v2.fingerprint({'url':row.url,'domain':site.canonical_domain}),'variant':None}
    if operation in {'indexation_collection','content_draft','monthly_onsite_plan','incremental_diagnosis'}:
        if object_id!=site.id or variant is not None:
            raise core.problem('automation_target_invalid','收录量查询只能绑定当前网站',422)
        value={'domain':site.canonical_domain,'url':site.default_url}
        if operation=='incremental_diagnosis' and plan_for(site).get('website_incremental_enabled') is not True:
            raise core.problem('automation_incremental_disabled','增量诊断尚未由顾问启用')
        if operation=='monthly_onsite_plan':
            value.update(await monthly_source(db,site,lock=lock))
        if operation=='content_draft':
            from app.seo_content_drafting import selected_material
            from app.models.seo_qa import SeoQaFact
            plan=plan_for(site)
            if plan.get('content_ai_enabled') is not True:
                raise core.problem('automation_content_not_enabled','内容自动起草尚未由顾问启用')
            if lock:
                for model,ids in ((SeoQaFact,plan.get('content_ai_fact_ids') or []),(SeoKeywordAsset,plan.get('content_ai_keyword_ids') or [])):
                    if ids: await db.scalars(select(model).where(model.tenant_id==site.tenant_id,model.site_id==site.id,
                        model.id.in_(ids)).order_by(model.id).with_for_update(read=True))
            value['material']=await selected_material(db,site,plan)
        return {'operation':operation,'object_type':'site','object_id':site.id,'source_revision':0,
            'source_hash':v2.fingerprint(value),'variant':None}
    if operation == 'ranking_collect':
        row=await db.get(SeoKeywordAsset,object_id,populate_existing=True,
            **({'with_for_update':True} if lock else {}))
        if not row or (row.tenant_id,row.site_id,row.status)!=(site.tenant_id,site.id,'active'):
            raise core.problem('automation_keyword_not_found','关键词不存在或不属于当前网站',404)
        if variant not in RANK_VARIANTS:
            raise core.problem('automation_variant_invalid','排名引擎与设备组合无效',422)
        return {'operation':operation,'object_type':'keyword','object_id':row.id,'source_revision':0,
            'source_hash':v2.fingerprint({k:getattr(row,k) for k in
                ('keyword','status','landing_page','priority','intent','cluster')}),'variant':variant}
    row = await db.get(SeoTask, object_id, populate_existing=True,
        **({'with_for_update': True} if lock else {}))
    if not row or (row.tenant_id, row.site_id, row.module, row.action_type) != (
            site.tenant_id, site.id, 'seo', ACTION_TYPE):
        raise core.problem('automation_task_not_found', '所选任务不属于当前网站', 404)
    workflow = (row.params or {}).get('onsite') or {}
    if workflow.get('schema') != 1 or workflow.get('phase') != 'draft' or row.status in {'done', 'cancelled'}:
        raise core.problem('automation_task_ineligible', '任务已处理，不能自动重发')
    facts = await ai.evidence(db, row, site, lock=lock)
    return {'operation': operation, 'object_type': 'onsite_task', 'object_id': row.id,
        'source_revision': workflow['revision'], 'source_hash': v2.fingerprint(facts), 'variant': None}


async def validate(db, site, config, *, target=None, targets=None, lock=False, configuring=False):
    config = ConfigurationV2.model_validate(config) if isinstance(config, dict) else config
    if set(config.operations) - set(OPERATIONS) or config.source_bindings:
        raise core.problem('automation_operation_unsupported', '操作或资料绑定尚未支持', 422)
    if config.service_plan.model_dump() != plan_version(site):
        raise core.problem('automation_source_changed', '服务计划已变化，请重新核对配置')
    for item in (targets if targets is not None else [target] if target else config.targets):
        value = item if isinstance(item, dict) else item.model_dump(mode='json')
        actual = await target_for(db, site, value['operation'], value['object_id'], variant=value.get('variant'),lock=lock)
        if actual != value:
            raise core.problem('automation_source_changed', '目标资料已变化，请重新核对配置')
        if configuring and value['operation']=='onsite_ai':
            from app.api.seo_automation_projects import eligible
            if not eligible(await db.get(SeoTask, value['object_id'])):
                raise core.problem('automation_task_ineligible', '任务已有请求或方案，不能自动重发')


async def validate_token(db, token, site, *, lock=True):
    if not token.get('target'): return
    _, run, _ = await core.check_step(db, token)
    await validate(db, site, run['configuration'], target=token['target'], lock=lock)


async def basis(db, site, operation, before_object_id, limit):
    from app.api.seo_onsite import ACTION_TYPE
    result = {'schema': 1, **core.scope('seo', site.tenant_id, site.id), 'contract_version': 2,
        'state': 'schema_pending', 'service_plan': None, 'source_bindings': [],
        'available_operations': [], 'targets': [], 'next_before_object_id': None}
    if not await v2.schema_ready(db): return result
    if operation not in OPERATIONS:
        raise core.problem('automation_operation_unsupported', '该操作尚未完成自动接管', 422)
    result.update(state='ready', service_plan=plan_version(site), available_operations=list(OPERATIONS))
    if operation=='site_diagnosis':
        query=select(SeoSitePage).where(SeoSitePage.tenant_id==site.tenant_id,SeoSitePage.site_id==site.id)
        if before_object_id is not None: query=query.where(SeoSitePage.id<before_object_id)
        rows=list(await db.scalars(query.order_by(SeoSitePage.id.desc()).limit(limit+1)))
        result['targets']=[{**await target_for(db,site,operation,row.id),'label':(row.title or '已登记页面')[:240]} for row in rows[:limit]]
        result['next_before_object_id']=rows[limit-1].id if len(rows)>limit else None
        return result
    if operation in {'indexation_collection','content_draft','monthly_onsite_plan','incremental_diagnosis'}:
        if before_object_id is None or site.id<before_object_id:
            result['targets']=[{**await target_for(db,site,operation,site.id),'label':site.name[:240]}]
        return result
    if operation=='monthly_report':
        query=select(SeoTask).where(SeoTask.tenant_id==site.tenant_id,SeoTask.site_id==site.id,
            SeoTask.module=='seo',SeoTask.action_type=='monthly_report',SeoTask.status.in_(['open','in_progress']),
            text("COALESCE(seo_tasks.params->'report','null'::jsonb) IN ('null'::jsonb,'{}'::jsonb)"))
        if before_object_id is not None: query=query.where(SeoTask.id<before_object_id)
        rows=list(await db.scalars(query.order_by(SeoTask.id.desc()).limit(limit+1)))
        result['targets']=[{**await target_for(db,site,operation,row.id),'label':row.title[:240]} for row in rows[:limit]]
        result['next_before_object_id']=rows[limit-1].id if len(rows)>limit else None
        return result
    if operation=='ranking_collect':
        query=select(SeoKeywordAsset).where(SeoKeywordAsset.tenant_id==site.tenant_id,
            SeoKeywordAsset.site_id==site.id,SeoKeywordAsset.status=='active')
        if before_object_id is not None: query=query.where(SeoKeywordAsset.id<before_object_id)
        rows=list(await db.scalars(query.order_by(SeoKeywordAsset.id.desc()).limit(limit+1)))
        for row in rows[:limit]:
            for variant in RANK_VARIANTS:
                result['targets'].append({**await target_for(db,site,operation,row.id,variant=variant),'label':row.keyword[:240]})
        result['next_before_object_id']=rows[limit-1].id if len(rows)>limit else None
        return result
    query = select(SeoTask).where(SeoTask.tenant_id == site.tenant_id, SeoTask.site_id == site.id,
        SeoTask.module == 'seo', SeoTask.action_type == ACTION_TYPE,
        SeoTask.status.in_(['open', 'in_progress']), SeoTask.params['onsite']['schema'].astext == '1',
        SeoTask.params['onsite']['phase'].astext == 'draft',
        text("COALESCE(seo_tasks.params->'onsite'->'ai_proposal','null'::jsonb) IN ('null'::jsonb,'{}'::jsonb)"),
        text("""NOT EXISTS (SELECT 1 FROM jsonb_each(COALESCE(NULLIF(seo_tasks.params->'onsite_ai_requests','null'::jsonb),'{}'::jsonb)) r
            WHERE NULLIF(r.value->>'started_at','') IS NOT NULL OR r.value->>'state' IN ('queued','running','ready','unknown'))"""))
    if before_object_id is not None: query = query.where(SeoTask.id < before_object_id)
    # Eligibility is filtered before LIMIT, so the cursor is always a returned object.
    rows = list(await db.scalars(query.order_by(SeoTask.id.desc()).limit(limit + 1)))
    for row in rows[:limit]:
        result['targets'].append({**await target_for(db, site, operation, row.id), 'label': row.title[:240]})
    result['next_before_object_id'] = rows[limit-1].id if len(rows) > limit else None
    return result


async def monthly_source(db,site,*,lock=False):
    from datetime import timedelta,timezone
    query=select(SeoKeywordAsset).where(SeoKeywordAsset.tenant_id==site.tenant_id,
        SeoKeywordAsset.site_id==site.id,SeoKeywordAsset.status=='active',SeoKeywordAsset.priority.in_(['P0','P1'])
        ).order_by(SeoKeywordAsset.priority,SeoKeywordAsset.id).limit(3)
    keywords=list(await db.scalars(query.with_for_update(read=True) if lock else query))
    pages_query=select(SeoSitePage).where(SeoSitePage.tenant_id==site.tenant_id,SeoSitePage.site_id==site.id,
        SeoSitePage.url.in_([k.landing_page for k in keywords if k.landing_page])).order_by(SeoSitePage.id).limit(3)
    pages=list(await db.scalars(pages_query.with_for_update(read=True) if lock else pages_query))
    if not keywords or not pages or any(k.landing_page not in {p.url for p in pages} for k in keywords):
        raise core.problem('automation_monthly_bindings_required','重点词必须绑定本站已登记页面')
    return {'month':core.now().astimezone(timezone(timedelta(hours=8))).strftime('%Y-%m'),
        'keywords':[{k:getattr(row,k) for k in ('id','keyword','landing_page','priority')} for row in keywords],
        'pages':[{k:getattr(row,k) for k in ('id','url','title_suggestion','description_suggestion')} for row in pages]}


async def report_source(db,site,month,*,lock=False):
    from app.models.seo import SeoContentAsset,SeoContentPublication
    from app.models.seo_site_analytics import SeoSiteAnalyticsMonthly,SeoSiteAnalyticsSource
    from app.seo_publication_export import month_bounds
    start,end=month_bounds(month)
    query=select(SeoContentPublication,SeoContentAsset).join(SeoContentAsset,
        SeoContentAsset.id==SeoContentPublication.content_asset_id).where(
            SeoContentPublication.tenant_id==site.tenant_id,SeoContentAsset.tenant_id==site.tenant_id,
            SeoContentAsset.site_id==site.id,SeoContentPublication.status=='published',
            SeoContentPublication.published_at>=start,SeoContentPublication.published_at<end
        ).order_by(SeoContentPublication.id).limit(201)
    pairs=list((await db.execute(query.with_for_update(read=True) if lock else query)).all())
    if len(pairs)>200: raise core.problem('automation_report_limit','本次报告最多汇总 200 条发布记录')
    query=select(SeoSiteAnalyticsMonthly).where(SeoSiteAnalyticsMonthly.tenant_id==site.tenant_id,
        SeoSiteAnalyticsMonthly.site_id==site.id,SeoSiteAnalyticsMonthly.month==month).order_by(SeoSiteAnalyticsMonthly.id)
    monthly=list(await db.scalars(query.with_for_update(read=True) if lock else query))
    names=list(await db.scalars(select(SeoSiteAnalyticsSource.source).where(SeoSiteAnalyticsSource.tenant_id==site.tenant_id,
        SeoSiteAnalyticsSource.site_id==site.id,SeoSiteAnalyticsSource.enabled.is_(True)).order_by(SeoSiteAnalyticsSource.source)))
    return {'month':month,'publications':[(p.id,p.platform_name,p.page_url,str(p.published_at),c.title,c.version_count) for p,c in pairs],
        'analytics':[{k:str(getattr(r,k)) for k in ('id','source','uv','pv','status','fetched_at','raw_meta')} for r in monthly],
        'source_names':names}
