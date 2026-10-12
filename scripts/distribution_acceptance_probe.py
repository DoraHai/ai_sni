"""Owned actual native API flow and read-only checkpoints; never consumes leases."""
import argparse
import asyncio
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from distribution_acceptance_environment import PORTS, NATIVE_HEADS, PYTHON, owned, read, write, command
from distribution_acceptance_configure import Client

RECIPE_SHA='25027554989014f0373e9284323c601a432f702cb8b1b068d8630d818819d77d'
BODY_SHA='65de75d0991fc67e81dc812b9c210cf28705fd49a271f941b07af49f12b3664c'


def checked_root(value):
    root=owned(value); config=read(root/'environment.json')
    if config['ports']!=PORTS or config['native_heads']!=NATIVE_HEADS or config['production'] is not False:
        raise RuntimeError('Exact new acceptance runtime required')
    if Path(config['central_root']).resolve()!=Path(__file__).resolve().parents[1]:
        raise RuntimeError('Acceptance central root mismatch')
    return root


def geo_flow(root):
    scope=read(root/'geo-pairing.json')['scope'];tenant=scope['tenant_id']
    advisor=Client(root,'geo','acceptance-advisor');customer=Client(root,'geo','acceptance-customer-1')
    try:
        private=Path(os.environ['TEMP'])
        recipe_path=private/'geo-manual-api-evidence-recipe-20261012.json'
        body_path=private/'geo-manual-revision-final-20261012.md'
        if hashlib.sha256(recipe_path.read_bytes()).hexdigest()!=RECIPE_SHA or hashlib.sha256(body_path.read_bytes()).hexdigest()!=BODY_SHA:
            raise RuntimeError('Frozen private manual revision evidence required')
        recipe=read(recipe_path);body=body_path.read_text(encoding='utf-8')
        base='/api/v1/geo/content-tasks/12';final=base+'/variants/wechat/manual-finalization'
        original=advisor.call('GET','/acceptance/original')
        task=advisor.call('GET',base,params={'tenant_id':tenant})
        raw=advisor.call('GET',final,params={'tenant_id':tenant,'scope_id':scope['scope_id']})
        assert raw['article_id']==17 and raw['variant_id']==2 and not raw['quality_passed']
        confirmations={key:True for key in ('confirm_title_body','confirm_layout','confirm_facts','confirm_brand_author','confirm_platform')}
        request=lambda value:{'scope_id':scope['scope_id'],'expected_variant_id':value['variant_id'],
            'expected_article_id':value['article_id'],'expected_revision':value['revision'],'request_id':str(uuid4()),**confirmations}
        advisor.call('POST',final,expected=409,params={'tenant_id':tenant},json=request(raw))
        advisor.call('GET','/api/distribution/v1/source',expected=409,params={**scope,'variant_id':2,'platform':'wechat-article'})
        for verification in recipe['fact_verification']:
            path=verification['path'].split('?',1)[0]
            assert path in {'/api/v1/geo/facts/4/verify','/api/v1/geo/facts/6/verify'}
            advisor.call('POST',path,params={'tenant_id':tenant},json=verification['request'])
        current=advisor.call('GET',base,params={'tenant_id':tenant})
        saved=advisor.call('PUT',base+'/article',params={'tenant_id':tenant},json={
            'expected_article_id':current['article']['id'],'title':original['title'],'body_markdown':body,'outline':{}})
        assert saved['article']['id']!=17
        advisor.call('PATCH',base+'/variants/wechat',params={'tenant_id':tenant},json={'title':original['title'],'body_markdown':body})
        context=advisor.call('GET',final,params={'tenant_id':tenant,'scope_id':scope['scope_id']})
        assert context['quality_passed'] and context['requires_master_rebase']
        pending=advisor.call('POST',final,params={'tenant_id':tenant},json=request(context))
        variant_id=pending['manual_finalize_result']['variant_id']
        assert pending['review_status']=='pending' and pending['manual_finalize_result']['publishing_authorized'] is False
        review={'decision':'approved','expected_article_id':pending['article']['id'],
            'expected_updated_at':pending['updated_at'],'note':'Local isolated synthetic customer review, not production or real client approval'}
        advisor.call('POST',base+'/review',expected=403,params={'tenant_id':tenant},json=review)
        customer.call('POST',base+'/review',params={'tenant_id':tenant},json=review)
        retained=advisor.call('GET','/acceptance/original')
        assert retained['articleId']==17 and retained['body']==original['body']
        result=source_ready(root,'geo',advisor,variant_id)
        result.update(original_article_id=17,original_variant_id=2,original_body_preserved=True,
            revised_article_id=pending['article']['id'],manual_source='manual',five_confirmations=True,
            approval_actor='native local test customer; not real client approval',
            actual_API=True,actual_GEO_Vue_DOM=False,formal_publish=False,
            http_checks=advisor.journal+customer.journal)
        write(root/'geo-native-flow-evidence.json',result)
        return result
    finally: advisor.close();customer.close()


def geo_timezone_recovery(root):
    """Preserve the failed local-time attempt; create a real edited UTC version."""
    scope=read(root/'geo-pairing.json')['scope'];tenant=scope['tenant_id']
    advisor=Client(root,'geo','acceptance-advisor');customer=Client(root,'geo','acceptance-customer-1')
    try:
        base='/api/v1/geo/content-tasks/12';final=base+'/variants/wechat/manual-finalization'
        current=advisor.call('GET',base,params={'tenant_id':tenant})
        assert current['article']['id']==18 and current['review_status']=='approved'
        bad=next(v for v in current['variants'] if v['channel']=='wechat')
        assert bad['id']==5 and bad['adapt_meta']['manual_finalization']['state']=='approved'
        advisor.call('GET','/api/distribution/v1/source',expected=409,params={**scope,'variant_id':5,'platform':'wechat-article'})
        body=current['article']['body_markdown']+'\n\n请保留确认记录。'
        private_body=root/'geo-local-timezone-recovery.md';private_body.write_text(body,encoding='utf-8')
        advisor.call('PUT',base+'/article',params={'tenant_id':tenant},json={
            'expected_article_id':current['article']['id'],'title':current['article']['title'],'body_markdown':body,'outline':{}})
        advisor.call('PATCH',base+'/variants/wechat',params={'tenant_id':tenant},json={'title':current['article']['title'],'body_markdown':body})
        context=advisor.call('GET',final,params={'tenant_id':tenant,'scope_id':scope['scope_id']})
        assert context['quality_passed'] and context['requires_master_rebase']
        request={'scope_id':scope['scope_id'],'expected_variant_id':context['variant_id'],
            'expected_article_id':context['article_id'],'expected_revision':context['revision'],'request_id':str(uuid4()),
            **{key:True for key in ('confirm_title_body','confirm_layout','confirm_facts','confirm_brand_author','confirm_platform')}}
        pending=advisor.call('POST',final,params={'tenant_id':tenant},json=request)
        review={'decision':'approved','expected_article_id':pending['article']['id'],
            'expected_updated_at':pending['updated_at'],'note':'Local synthetic customer re-review of UTC edited version; not production approval'}
        advisor.call('POST',base+'/review',expected=403,params={'tenant_id':tenant},json=review)
        customer.call('POST',base+'/review',params={'tenant_id':tenant},json=review)
        result=source_ready(root,'geo',advisor,pending['manual_finalize_result']['variant_id'])
        assert result['body_sha256']==hashlib.sha256(body.encode()).hexdigest()
        original=advisor.call('GET','/acceptance/original')
        snapshot=read(root/'customer-snapshot.json')['collections']
        original17=next(r for r in snapshot['geo_article_versions'] if r['id']==17)
        assert original['articleId']==17 and original['body']==original17['body_markdown']
        result.update(original_article_id=17,original_variant_id=2,original_body_preserved=True,
            failed_timezone_article_id=18,failed_timezone_variant_id=5,failed_attempt_preserved=True,
            revised_article_id=pending['article']['id'],manual_source='manual',five_confirmations=True,
            approval_actor='native local test customer; not real client approval',actual_API=True,
            actual_GEO_Vue_DOM=False,formal_publish=False,private_revised_body=str(private_body),
            http_checks=advisor.journal+customer.journal)
        write(root/'geo-native-flow-evidence.json',result)
        return result
    finally:advisor.close();customer.close()


def source_ready(root,module,client=None,variant_id=None):
    own=client is None;client=client or Client(root,module,'acceptance-advisor')
    try:
        scope=read(root/(module+'-pairing.json'))['scope']
        candidates=client.call('GET','/api/distribution/v1/sources',params={**scope,'platform':'wechat-article'})['items']
        if variant_id is None:
            assert len(candidates)==1
            variant_id=candidates[0]['variant_id']
        listed=next(row for row in candidates if row['variant_id']==variant_id)
        source=client.call('GET','/api/distribution/v1/source',params={**scope,'variant_id':variant_id,'platform':'wechat-article'})
        assert source['source_revision']==listed['source_revision']
        result={'scope':scope,'variant_id':variant_id,'source_revision':source['source_revision'],
            'content_digest':source['content_digest'],'body_sha256':hashlib.sha256(source['content']['body'].encode()).hexdigest(),
            'publicationVerified':False,'source_current_native_gate':True}
        write(root/(module+'-source-ready.json'),result)
        return result
    finally:
        if own:client.close()


def geo_fresh_copy(root, *, resume=False, visible_date=False):
    """Actual native task copy; no temporal history mutation or self approval."""
    scope=read(root/'geo-pairing.json')['scope'];tenant=scope['tenant_id']
    advisor=Client(root,'geo','acceptance-advisor');customer=Client(root,'geo','acceptance-customer-1')
    try:
        source=read(root/'customer-snapshot.json')['collections']
        original=next(row for row in source['geo_content_tasks'] if row['id']==12)
        article=next(row for row in source['geo_article_versions'] if row['id']==17)
        private=Path(os.environ['TEMP'])/'geo-manual-revision-final-20261012.md'
        assert hashlib.sha256(private.read_bytes()).hexdigest()==BODY_SHA
        body=private.read_text(encoding='utf-8')
        saved_at=datetime.now(timezone.utc)
        if visible_date:
            # Native editorial-date format explicitly distinguishes document
            # creation from the date of any cited source or production edit.
            body+='\n\n*草稿生成日期：'+saved_at.date().isoformat()+'（非来源更新日期）*'
            (root/'geo-fresh-visible-date-revision.md').write_text(body,encoding='utf-8')
        if resume:
            pointer=read(root/'geo-derived-task.json')
            assert pointer['scope']==scope and pointer['source_task_id']==12 and pointer['local_manual_revision'] is True
            copied=advisor.call('GET',f'/api/v1/geo/content-tasks/{pointer["task_id"]}',params={'tenant_id':tenant})
            assert copied['tenant_id']==tenant and copied['prompt_id']==original['prompt_id']
            assert visible_date or copied['review_status']!='approved'
        else:
            copied=advisor.call('POST','/api/v1/geo/content-tasks',json={'tenant_id':tenant,'prompt_id':original['prompt_id'],
                'title':article['title']+' · 本地UTC验收副本','target_channels':['wechat'],'fact_ids':[4,5,6],
                'brief':{**(original.get('brief') or {}),'notes':'LOCAL copy of existing customer topic and manually revised text; no production edit'}})
        task_id=copied['id'];base=f'/api/v1/geo/content-tasks/{task_id}'
        write(root/'geo-derived-task.json',{'scope':scope,'task_id':task_id,'source_task_id':12,'source_article_id':17,
            'local_manual_revision':True,'failed_temporal_history_preserved':True})
        # This is current editorial metadata, never a historic timestamp rewrite.
        saved=advisor.call('PUT',base+'/article',params={'tenant_id':tenant},json={'title':copied['title'],'body_markdown':body,
            'outline':{'updated_at':saved_at.isoformat()}})
        # Native synchronous non-AI path creates a real preview version first.
        if not resume:
            advisor.call('POST',base+'/variants',params={'tenant_id':tenant,'run_async':False},json={'channels':['wechat'],'use_llm':False})
        advisor.call('PATCH',base+'/variants/wechat',params={'tenant_id':tenant},json={'title':copied['title'],'body_markdown':body})
        final=base+'/variants/wechat/manual-finalization'
        context=advisor.call('GET',final,params={'tenant_id':tenant,'scope_id':scope['scope_id']})
        assert context['quality_passed']
        pending=advisor.call('POST',final,params={'tenant_id':tenant},json={'scope_id':scope['scope_id'],
            'expected_variant_id':context['variant_id'],'expected_article_id':context['article_id'],
            'expected_revision':context['revision'],'request_id':str(uuid4()),
            **{key:True for key in ('confirm_title_body','confirm_layout','confirm_facts','confirm_brand_author','confirm_platform')}})
        review={'decision':'approved','expected_article_id':pending['article']['id'],'expected_updated_at':pending['updated_at'],
            'note':'LOCAL synthetic customer confirms fresh UTC task version; not real customer or production approval'}
        advisor.call('POST',base+'/review',expected=403,params={'tenant_id':tenant},json=review)
        customer.call('POST',base+'/review',params={'tenant_id':tenant},json=review)
        result=source_ready(root,'geo',advisor,pending['manual_finalize_result']['variant_id'])
        retained=advisor.call('GET','/acceptance/original')
        assert retained['articleId']==17 and retained['body']==article['body_markdown']
        result.update(task_id=task_id,article_id=pending['article']['id'],source_task_id=12,source_article_id=17,
            failed_task_12_history_preserved=True,original_body_preserved=True,manual_source='manual',
            approval_actor='actual native LOCAL test customer JWT, not real client approval',
            actual_API=True,actual_GEO_Vue_DOM=False,formal_publish=False,
            http_checks=advisor.journal+customer.journal)
        write(root/'geo-native-flow-evidence.json',result)
        return result
    finally:
        write(root/'geo-fresh-copy-api-journal.json',{'checks':advisor.journal+customer.journal,'body_or_credentials_included':False})
        advisor.close();customer.close()


async def native_intake(root,module):
    from distribution_acceptance_native import prepare
    _,config,engine,sessions,manifest=prepare(root/'environment.json',module)
    scope=read(root/(module+'-pairing.json'))['scope'];expected=read(root/(module+'-source-ready.json'))
    try:
        if module=='geo':from app.geo.distribution_sources import load_intake_candidate
        else:from app.seo_distribution_sources import load_intake_candidate
        async with sessions() as db:
            value=await load_intake_candidate(db,100007,scope['tenant_id'],scope['scope_id'],expected['variant_id'],'wechat-article')
            assert value['readiness']=='ready' and value['source_revision']==expected['source_revision']
            await db.rollback()
        write(root/(module+'-native-intake-evidence.json'),{'metadata':value,'scope':scope,
            'actual_native_adapter':True,'normal_read_committed_no_mutation':True,'native_head':manifest['native_head']})
        return value
    finally:await engine.dispose()


async def observe(root,module):
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine
    public=read(root/(module+'-pairing.json'));scope=public['scope']
    engine=create_async_engine(f'postgresql+asyncpg://distribution_acceptance@127.0.0.1:{PORTS["pg"]}/distribution_acceptance_{module}',
        hide_parameters=True,connect_args={'server_settings':{'search_path':'acceptance_'+module}})
    report={'module':module,'scope':scope,'publicationVerified':False,'read_only':True}
    try:
        async with engine.connect() as db:
            await db.execute(text('SET TRANSACTION READ ONLY'))
            rows=(await db.execute(text('SELECT id,grant_id,lease_id,source_revision,content_digest,account_id,platform,action,status,publication_grant_id,revoked,receipt FROM distribution_tasks WHERE module=:module AND tenant_id=:tenant_id AND scope_id=:scope_id AND device_id=:device ORDER BY created_at DESC LIMIT 20'),{**scope,'device':public['deviceId']})).mappings().all()
            tuples=[{'taskId':str(row['id']),'grantId':str(row['grant_id']),'leaseId':str(row['lease_id']),
                'deviceId':public['deviceId'],'customerId':public['customerId'],'projectId':public['projectId'],
                'accountId':row['account_id'],'platform':row['platform'],'contentVersion':row['source_revision'],
                'contentDigest':row['content_digest'],'action':row['action'],'status':row['status'],
                'revoked':row['revoked'],'publicationGrantId':str(row['publication_grant_id']) if row['publication_grant_id'] else None,
                'receiptCode':(row['receipt'] or {}).get('code'),'publicationVerified':False} for row in rows]
            report['task_tuples']=tuples
            queries={
                'queue':'SELECT variant_id,state,reason,draft_version,source_revision,content_digest FROM distribution_queue WHERE module=:module AND tenant_id=:tenant_id AND scope_id=:scope_id ORDER BY checked_at DESC LIMIT 20',
                'plans':'SELECT state,reason,basis,planned_at FROM distribution_plans WHERE module=:module AND tenant_id=:tenant_id AND scope_id=:scope_id ORDER BY created_at DESC LIMIT 20',
                'planning_requests':'SELECT state,reason,attempts FROM distribution_plan_requests WHERE module=:module AND tenant_id=:tenant_id AND scope_id=:scope_id ORDER BY updated_at DESC LIMIT 20'}
            for key,sql in queries.items():report[key]=[dict(row) for row in (await db.execute(text(sql),scope)).mappings()]
            report['simulation_metering']=[dict(row) for row in (await db.execute(text("SELECT module,operation,user_id,tenant_id,state,model,provider_request_id,prompt_tokens,completion_tokens FROM api_usage_events ORDER BY started_at DESC LIMIT 20"))).mappings()]
            native='seo_content_publications' if module=='seo' else 'geo_publications'
            report['native_publications']=await db.scalar(text('SELECT count(*) FROM '+native))
            report['central_publication_reservations']=await db.scalar(text('SELECT count(*) FROM distribution_publish_reservations'))
            report['handoff_ledger']=[dict(row) for row in (await db.execute(text('SELECT task_id::text,sequence,status,code FROM acceptance_handoff_events WHERE module=:module ORDER BY at,sequence'),{'module':module})).mappings()]
            report['scoped_audit']=[dict(row) for row in (await db.execute(text(
                "SELECT at,actor,action,task_id::text,result FROM distribution_events WHERE target->>'module'=:module "
                "AND target->>'tenant_id'=:tenant AND target->>'scope_id'=:project ORDER BY at DESC LIMIT 80"),
                {'module':module,'tenant':str(scope['tenant_id']),'project':str(scope['scope_id'])})).mappings()]
            await db.rollback()
        write(root/(module+'-runtime-checkpoint.json'),report)
        write(root/(module+'-main-task-tuple.json'),{'scope':scope,'items':tuples,'no_exchange_called':True,'publicationVerified':False})
        return report
    finally:await engine.dispose()


def close_binding(root,module):
    """Only after GUI handoff completion and advisor DOM pause; never takes leases."""
    public=read(root/(module+'-pairing.json'));scope=public['scope']
    advisor=Client(root,module,'acceptance-advisor');admin=Client(root,module,'acceptance-admin')
    customer=Client(root,module,'acceptance-customer-'+str(scope['tenant_id']))
    foreign=Client(root,module,'acceptance-foreign-customer')
    try:
        control=advisor.call('GET','/api/distribution/v1/scope',params=scope)['project']
        assert control['state']=='paused'
        before=advisor.call('GET','/acceptance/handoff-results',params={'tenant_id':scope['tenant_id'],'scope_id':scope['scope_id']})
        assert any(row['code']=='HUMAN_HANDOFF_ACCEPTED' and row['status']=='succeeded' for row in before['items'])
        customer.call('POST','/api/distribution/v1/control',expected=403,json={**scope,'action':'resume',
            'expected_revision':control['revision'],'request_id':str(uuid4())})
        advisor.call('POST','/api/distribution/v1/control',expected=409,json={**scope,'action':'resume',
            'expected_revision':control['revision']-1,'request_id':str(uuid4())})
        foreign.call('GET','/acceptance/handoff-results',expected=403,params={'tenant_id':scope['tenant_id'],'scope_id':scope['scope_id']})
        advisor.call('POST','/api/distribution/v1/tasks',expected=403,json={'action':'publish'})
        binding=next(row for row in admin.call('GET','/api/distribution/v1/bindings')['items'] if row['id']==public['bindingIds'][0])
        if binding['active']:
            admin.call('POST','/api/distribution/v1/bindings/'+binding['id']+'/revoke')
        revoked=next(row for row in admin.call('GET','/api/distribution/v1/bindings')['items'] if row['id']==binding['id'])
        assert revoked['active'] is False
        retained=customer.call('GET','/acceptance/handoff-results',params={'tenant_id':scope['tenant_id'],'scope_id':scope['scope_id']})
        assert retained['items']==before['items']
        assert advisor.call('GET','/api/distribution/v1/scope',params=scope)['project']==control
        result={'module':module,'scope':scope,'binding_id':binding['id'],'active':False,'project':control,
            'handoff_metadata_preserved':True,'http_checks':advisor.journal+admin.journal+customer.journal+foreign.journal,
            'publicationVerified':False,'lease_exchange_called':False,'production_mutations':False}
        write(root/(module+'-closure-evidence.json'),result)
        return result
    finally:
        for client in (advisor,admin,customer,foreign):client.close()


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--module',choices=('seo','geo'),required=True)
    parser.add_argument('action',choices=('geo-native','geo-timezone-recovery','geo-fresh-copy','geo-fresh-resume','geo-date-revision','source','intake','native-intake','observe','close-binding'))
    args=parser.parse_args();root=checked_root(args.root)
    if args.action=='geo-native':
        if args.module!='geo':raise RuntimeError('GEO only')
        result=geo_flow(root)
    elif args.action=='geo-timezone-recovery':
        if args.module!='geo':raise RuntimeError('GEO only')
        result=geo_timezone_recovery(root)
    elif args.action in ('geo-fresh-copy','geo-fresh-resume','geo-date-revision'):
        if args.module!='geo':raise RuntimeError('GEO only')
        result=geo_fresh_copy(root,resume=args.action!='geo-fresh-copy',visible_date=args.action=='geo-date-revision')
    elif args.action=='source':result=source_ready(root,args.module)
    elif args.action=='close-binding':result=close_binding(root,args.module)
    elif args.action=='native-intake':result=asyncio.run(native_intake(root,args.module))
    elif args.action=='intake':
        command(root,[PYTHON,Path(__file__),'--root',root,'--module',args.module,'native-intake'],args.module)
        result=read(root/(args.module+'-native-intake-evidence.json'))
    else:result=asyncio.run(observe(root,args.module))
    print(json.dumps({'module':args.module,'action':args.action,'source_ready':bool(result.get('source_current_native_gate')),
        'task_count':len(result.get('task_tuples',[])),'publicationVerified':False}))


if __name__=='__main__':main()
