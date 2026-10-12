"""SEO request/result boundary, reused by existing collectors and v2 workers."""
from contextlib import contextmanager,asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass,field
import inspect
from functools import wraps

from app import automation_projects as core, automation_project_v2 as v2
from app.database import async_session_factory
from app.api_metering import background_scope
from app.security.auth import AuthContext

current = ContextVar('seo_automation_boundary', default=None)


@dataclass
class Boundary:
    key: dict
    operation: str
    token: dict | None = None
    sessions: object = None
    legacy_keys: list | None = None
    http_sequence: int = 0
    deferred_receipts: list = field(default_factory=list)

    async def check(self, db):
        if self.token:
            from app.api.seo_automation_projects import scoped
            from app import seo_automation_sources as sources
            from app.api.seo_onsite_ai import execution_enabled
            await core.check_step(db,self.token)
            site,fresh=await scoped(db,AuthContext(self.token['owner_user_id'],'','',None,{}),
                self.key['tenant_id'],self.key['scope_id'],lock=True)
            if self.operation=='ranking_collect' and not fresh.can_edit('seo.keywords'):
                raise core.problem('automation_forbidden','排名采集需要关键词编辑权限',403)
            if self.operation=='content_draft':
                from app.seo_content_workflow import plan_for
                if plan_for(site).get('content_ai_authorized_by')!=fresh.user_id:
                    raise core.problem('automation_owner_mismatch','内容起草授权人与当前负责人不一致')
            execution_enabled(site)
            await sources.validate_token(db,self.token,site)
        else:
            for key in self.legacy_keys or [self.key]:
                await v2.check_legacy(db,key,self.operation)
                if self.operation=='site_diagnosis':
                    await v2.check_legacy(db,key,'incremental_diagnosis')

    async def checkpoint(self):
        async with (self.sessions or async_session_factory)() as db:
            await self.check(db)
            await db.commit()


@contextmanager
def use(boundary):
    mark=current.set(boundary)
    try: yield boundary
    finally: current.reset(mark)


async def provider_call(send,*args,**kwargs):
    boundary=current.get()
    if boundary is None: return await send(*args,**kwargs)
    if boundary.token is None:
        await boundary.checkpoint()
        return await send(*args,**kwargs)
    # Payload identity excludes credentials. A retry of the same provider request
    # has the same key and cannot obtain a second paid admission.
    public_params={k:v for k,v in (kwargs.get('params') or {}).items() if k.lower() not in {'apikey','key','token'}}
    call_key='request:'+v2.fingerprint({'method':args[1],'endpoint':args[2],
        'params':public_params,'json':kwargs.get('json')})[:32]
    sessions=boundary.sessions or async_session_factory
    async with sessions() as db:
        await boundary.check(db)
        if not await v2.begin_call(db,boundary.token,call_key):
            raise core.problem('automation_call_already_admitted','原请求已有调用记录，不自动付费重试')
        await db.commit()
    state='unknown'
    try:
        with background_scope(tenant_id=boundary.key['tenant_id'],module='seo',
                user_id=boundary.token['owner_user_id'],operation=boundary.operation,
                job_ref='automation:'+boundary.token['request_id']+':'+call_key):
            result=await send(*args,**kwargs)
        state='succeeded' if result.is_success else 'failed'
        return result
    finally:
        if boundary.operation=='indexation_collection':
            # Here the gate sits inside the already-metered client's get(). The
            # outer ledger commits after get returns; settle immediately after it.
            boundary.deferred_receipts.append((call_key,state))
        else:
            async with sessions() as db:
                fee,refs=await fee_receipt(db,boundary.token,call_key)
                await v2.finish_call(db,boundary.token,call_key,state=state,fee_state=fee,evidence_refs=refs)
                await db.commit()


def legacy_collector(operation):
    """Decorate site-specific collectors; a managed executor supplies its token."""
    def decorate(function):
        signature=inspect.signature(function)
        @wraps(function)
        async def wrapped(*args,**kwargs):
            if current.get() is not None:
                if current.get().operation != operation:
                    raise core.problem('automation_operation_mismatch','调用操作与接管范围不一致')
                return await function(*args,**kwargs)
            arguments=signature.bind(*args,**kwargs).arguments
            site_id=arguments.get('site_id')
            if site_id is None:
                # Split a legacy tenant batch by actual keyword ownership. One
                # adopted website must not stop unrelated unowned websites.
                from sqlalchemy import select
                from app.models.seo import SeoKeywordAsset
                db=arguments['session']
                query=select(SeoKeywordAsset).where(SeoKeywordAsset.tenant_id==arguments['tenant_id'],SeoKeywordAsset.status=='active')
                if arguments.get('keyword_ids'): query=query.where(SeoKeywordAsset.id.in_(arguments['keyword_ids']))
                query=query.order_by(SeoKeywordAsset.priority,SeoKeywordAsset.id.desc())
                if arguments.get('max_keywords') is not None: query=query.limit(arguments['max_keywords'])
                rows=list(await db.scalars(query))
                groups={}
                errors=[]
                for row in rows:
                    if row.site_id is None:
                        errors.append({'keyword_id':row.id,'code':'automation_site_required'})
                    else: groups.setdefault(row.site_id,[]).append(row.id)
                results=[]
                budget=arguments.get('provider_request_budget')
                for ident,ids in sorted(groups.items()):
                    key=core.scope('seo',arguments['tenant_id'],ident)
                    if await v2.ownership(db,key,operation):
                        errors.extend({'keyword_id':i,'code':'automation_legacy_owned'} for i in ids)
                        continue
                    if budget is not None and budget<=0: break
                    params={**arguments,'site_id':ident,'keyword_ids':ids,'max_keywords':len(ids),'provider_request_budget':budget}
                    with use(Boundary(key,operation)):
                        result=await function(**params)
                    results.append(result)
                    if budget is not None: budget-=result['provider_requests']
                numeric=('keywords','requests','provider_requests','serp_results','confirmed_brand_results','ai_suspected_results','snapshots')
                return {**{k:sum(r[k] for r in results) for k in numeric},
                    'engine':arguments.get('engine','baidu'),'devices':arguments.get('devices') or ['desktop'],
                    'source':results[0]['source'] if results else None,
                    'errors':errors+[e for r in results for e in r['errors']],
                    'optimization':{'created':sum(r['optimization']['created'] for r in results),
                        'task_ids':[i for r in results for i in r['optimization']['task_ids']],
                        'skipped_existing':sum(r['optimization']['skipped_existing'] for r in results)},
                    **{name:any(r.get(name,False) for r in results) for name in ('ai_enabled','ai_available','ai_requested','ai_attempted')}}
            boundary=Boundary(core.scope('seo',arguments['tenant_id'],site_id),operation)
            with use(boundary):
                return await function(*args,**kwargs)
        return wrapped
    return decorate


async def before_save(db):
    if current.get(): await current.get().check(db)


async def fee_receipt(db,token,call_key):
    from sqlalchemy import text
    from app.api_usage_review_basis import accounted_amount
    columns=set((await db.execute(text("SELECT column_name FROM information_schema.columns WHERE table_schema=current_schema() AND table_name='api_usage_events'"))).scalars())
    if not {'id','tenant_id','module','job_ref','state','estimated_amount'}<=columns: return 'unknown_charge',[]
    try: amount=await accounted_amount(db)
    except RuntimeError: return 'unknown_charge',[]
    job='automation:'+token['request_id']+':'+('indexation' if token['operation']=='indexation_collection' else call_key)
    rows=list((await db.execute(text('SELECT id,state,'+amount+" AS amount FROM api_usage_events WHERE tenant_id=:tenant AND module='seo' AND job_ref=:job ORDER BY id LIMIT 21"),
        {'tenant':token['tenant_id'],'job':job})).mappings())
    known=bool(rows) and len(rows)<=20 and all(r['state'] in {'succeeded','error'} and r['amount'] is not None for r in rows)
    return ('recorded' if known else 'unknown_charge'),['api_event:'+str(r['id']) for r in rows[:20]]


async def finish_deferred(db,gate):
    for call_key,state in gate.deferred_receipts:
        fee,refs=await fee_receipt(db,gate.token,call_key)
        await v2.finish_call(db,gate.token,call_key,state=state,fee_state=fee,evidence_refs=refs)


def legacy_task(operation):
    def decorate(function):
        @wraps(function)
        async def wrapped(task_id,*args,**kwargs):
            if current.get() is not None: return await function(task_id,*args,**kwargs)
            from app.models.seo_cockpit import SeoTask
            # Use the original worker factory, including isolated-test injection.
            sessions=kwargs.get('sessions') or function.__globals__['async_session_factory']
            async with sessions() as db:
                row=await db.get(SeoTask,task_id)
                if row is None: return
                gate=Boundary(core.scope('seo',row.tenant_id,row.site_id),operation,sessions=sessions)
                await gate.check(db)
                await db.commit()
            with use(gate): return await function(task_id,*args,**kwargs)
        return wrapped
    return decorate


async def ai_call(send,system,user,**kwargs):
    """One chat_json invocation is one real request; no fallback or paid repair."""
    gate=current.get()
    if gate is None: return await send(system,user,**kwargs)
    if gate.token is None:
        await gate.checkpoint()
        return await send(system,user,**kwargs)
    sessions=gate.sessions or async_session_factory
    async with sessions() as db:
        await gate.check(db)
        if not await v2.begin_call(db,gate.token,'content_draft'):
            raise core.problem('automation_call_already_admitted','原请求已有调用记录，不自动付费重试')
        await db.commit()
    state='unknown'
    try:
        with background_scope(tenant_id=gate.key['tenant_id'],module='seo',user_id=gate.token['owner_user_id'],
                operation=gate.operation,job_ref='automation:'+gate.token['request_id']+':content_draft'):
            value=await send(system,user,**kwargs)
        state='succeeded'
        return value
    finally:
        async with sessions() as db:
            fee,refs=await fee_receipt(db,gate.token,'content_draft')
            await v2.finish_call(db,gate.token,'content_draft',state=state,fee_state=fee,evidence_refs=refs)
            await db.commit()


@asynccontextmanager
async def http_attempt():
    gate=current.get()
    if gate is None:
        yield
        return
    if gate.token is None:
        await gate.checkpoint()
        yield
        return
    gate.http_sequence+=1
    call_key='http:'+str(gate.http_sequence)
    sessions=gate.sessions or async_session_factory
    async with sessions() as db:
        await gate.check(db)
        if not await v2.begin_call(db,gate.token,call_key,kind='http'):
            raise core.problem('automation_call_already_admitted','原抓取已有准入，不自动重试')
        await db.commit()
    state='unknown'
    try:
        yield
        state='succeeded'
    finally:
        async with sessions() as db:
            await v2.finish_call(db,gate.token,call_key,state=state,fee_state='not_called')
            await db.commit()
