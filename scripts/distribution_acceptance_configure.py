"""Actual native HTTPS configuration; credentials and article bodies stay private."""
import argparse
import hashlib
import json
from pathlib import Path
import ssl
from uuid import uuid4
import httpx
from distribution_acceptance_environment import PORTS, owned, read, write


class Client:
    def __init__(self, root, module, username):
        self.root, self.module = root, module
        context = ssl.create_default_context(cafile=str(root/'loopback.pem'))
        self.http = httpx.Client(base_url=f'https://127.0.0.1:{PORTS[module]}', verify=context,
                                 timeout=20, follow_redirects=False, trust_env=False)
        login = self.http.post('/api/v1/auth/login', json={
            'username':username,'password':read(root/'secrets.json')['password']})
        if login.status_code != 200: raise RuntimeError('Named acceptance login failed')
        token = login.json()['token']
        self.http.headers['Authorization'] = 'Bearer '+token
        self.journal = []

    def call(self, method, path, expected=200, **kwargs):
        result = self.http.request(method, path, **kwargs)
        code = None
        try:
            detail = result.json().get('detail')
            code = detail.get('code') if isinstance(detail,dict) else None
        except (ValueError,AttributeError): pass
        self.journal.append({'method':method,'path':path,'status':result.status_code,'code':code})
        accepted = expected if isinstance(expected,tuple) else (expected,)
        if result.status_code not in accepted:
            write(self.root/(self.module+'-last-http-failure.json'), {'path':path,'status':result.status_code,'code':code})
            raise RuntimeError('Acceptance HTTP step failed; see private status-only report')
        return result.json()

    def close(self): self.http.close()


def inventory(root):
    snapshot = read(root/'customer-snapshot.json')
    result = {'snapshot_sha256':hashlib.sha256((root/'customer-snapshot.json').read_bytes()).hexdigest(),
              'source_parent_sha256':snapshot.get('sourceSnapshotSha256'), 'modules':{}}
    for module in ('seo','geo'):
        client = Client(root,module,'acceptance-advisor')
        try:
            if module=='seo':
                initial = client.call('GET','/api/distribution/v1/source',expected=(403,404,409),
                    params={'module':'seo','tenant_id':15,'scope_id':6,'variant_id':1,'platform':'wechat-article'})
                result['modules'][module]={'initial_source_blocked':True,'detail':initial.get('detail'),
                    'original_variant_id':1,'original_platform':'baijiahao','local_adaptation_required':True}
            else:
                projects = client.call('GET','/api/v1/geo/projects',params={'tenant_id':1})
                task = client.call('GET','/api/v1/geo/content-tasks/12',params={'tenant_id':1})
                variants=[{'id':row['id'],'channel':row['channel'],'status':row['status'],
                    'publishable':row.get('publishable',row.get('adapt_meta',{}).get('publishable')),
                    'quality':row.get('adapt_meta',{}).get('quality')}
                    for row in task['variants']]
                if task['review_status']!='pending' or len(variants)!=3 or any(row['publishable'] is not False for row in variants):
                    raise RuntimeError('Original GEO runtime gate state changed; do not label it initial')
                result['modules'][module]={'project_count':len(projects['projects']),
                    'task_id':12,'task_payload_keys':sorted(task),'runtime_review_status':task['review_status'],
                    'runtime_variant_gates':variants,'runtime_readback_asserted':True}
            result['modules'][module]['http_checks'] = client.journal
        finally: client.close()
    target=root/('initial-gates.json' if not (root/'initial-gates.json').exists() else 'native-gate-readback.json')
    write(target,result)
    return result


def configure(root, module):
    admin = Client(root,module,'acceptance-admin')
    advisor = Client(root,module,'acceptance-advisor')
    try:
        private_file = root/(module+'-pairing-private.json')
        if private_file.exists() and read(private_file).get('configured'):
            return read(private_file)
        if module=='seo':
            scope = {'module':'seo','tenant_id':15,'scope_id':6}
            admin.call('PUT','/api/v1/seo/workbench/advisor-assignments',json={
                'tenant_id':15,'site_id':6,'advisor_user_id':100007,'active':True})
            # Admin is separately named; only the assigned advisor controls work.
        else:
            projects = admin.call('GET','/api/v1/geo/projects',params={'tenant_id':1})['projects']
            project = next((row for row in projects if row['name']=='诺德 · 独立本地验收'),None)
            if project is None:
                project = admin.call('POST','/api/v1/geo/projects',json={'tenant_id':1,
                    'name':'诺德 · 独立本地验收','brand_name':'诺德','domain':'nord-acceptance.example',
                    'description':'仅本地独立验收；未更新生产项目'})
            scope = {'module':'geo','tenant_id':1,'scope_id':project['id']}
            binding = project['business_scope']
            admin.call('PUT',f'/api/v1/geo/projects/{project["id"]}/business-scope',params={'tenant_id':1},
                json={'business_ids':[13],'expected_revision':binding['revision']})
            snapshot = read(root/'customer-snapshot.json')
            prompts = [row['id'] for row in snapshot['collections']['geo_prompts']]
            advisor.call('PUT',f'/api/v1/geo/projects/{project["id"]}/service-plan',params={'tenant_id':1},
                json={'expected_revision':0,'enabled':False,'status':'active','prompt_ids':prompts,
                    'interval_days':7,'advisor_user_id':100007})
        control=advisor.call('GET','/api/distribution/v1/scope',params=scope)['project']
        if control['revision']==0:
            advisor.call('POST','/api/distribution/v1/control',json={**scope,'action':'start',
                'expected_revision':0,'request_id':str(uuid4())})
            advisor.call('POST','/api/distribution/v1/control',json={**scope,'action':'pause',
                'expected_revision':1,'request_id':str(uuid4())})
        # Clean up only abandoned, never-paired local devices from a failed
        # bootstrap. Their one-time credentials cannot be recovered from DB.
        if not private_file.exists():
            abandoned=admin.call('GET','/api/distribution/v1/bindings')['items']
            for row in abandoned:
                if row['module']==module and row['external_account_id']=='acceptance-local-'+module and row['active']:
                    admin.call('POST','/api/distribution/v1/bindings/'+row['id']+'/revoke')
                    admin.call('POST','/api/distribution/v1/devices/'+row['device_id']+'/revoke')
        if private_file.exists():
            value=read(private_file);device={'id':value['deviceId'],'credential':value['credential']}
        else:
            device = admin.call('POST','/api/distribution/v1/devices',json={'label':module.upper()+' independent acceptance'})['device']
            value={'scope':scope,'deviceId':device['id'],'credential':device['credential'],'bindingIds':[],
                'customerId':str(scope['tenant_id']),'projectId':module+'-'+str(scope['scope_id']),'configured':False}
            write(private_file,value)
        existing=admin.call('GET','/api/distribution/v1/bindings')['items']
        binding=next((row for row in existing if row['device_id']==device['id'] and row['active']),None)
        if binding is None:
            binding = admin.call('POST','/api/distribution/v1/bindings',json={**scope,
                'device_id':device['id'],'account_id':'acceptance-'+module,
                'external_account_id':'acceptance-local-'+module,'platform':'wechat-article',
                'confirm_account_ownership':True})['binding']
        value['bindingIds']=[binding['id']];write(private_file,value)
        policies=admin.call('GET','/api/distribution/v1/account-policies')['items']
        policy=next(row['policy'] for row in policies if row['binding_id']==binding['id'])
        if not policy or not policy['enabled']:
            admin.call('POST','/api/distribution/v1/account-policy',json={'binding_id':binding['id'],
                'enabled':True,'expected_revision':policy['revision'] if policy else 0,'timezone':'Asia/Shanghai','daily_limit':10,
                'min_interval_seconds':0,'windows':[{'start':0,'end':1440}],'request_id':str(uuid4())})
        capability=next(row for row in admin.call('GET','/api/distribution/v1/channel-catalog')['items'] if row['platform']=='wechat-article')
        if not capability['enabled']:
            admin.call('POST','/api/distribution/v1/channel-permission',json={'platform':'wechat-article',
                'content_type':'article','enabled':True,'expected_revision':capability['revision'],'request_id':str(uuid4())})
        advisor.call('POST','/api/distribution/v1/project-channel',json={**scope,'binding_id':binding['id'],
            'content_type':'article','enabled':True,'expected_revision':0,'request_id':str(uuid4())})
        advisor.call('POST','/api/distribution/v1/handoff-permission',json={**scope,'binding_id':binding['id'],
            'stage':'handoff','enabled':True,'confirm_reviewed_handoff':True,'expected_revision':0,'request_id':str(uuid4())})
        # The project remains paused until its advisor explicitly resumes it.
        value = {'scope':scope,'deviceId':device['id'],'credential':device['credential'],
            'bindingIds':[binding['id']],'customerId':str(scope['tenant_id']),
            'projectId':module+'-'+str(scope['scope_id']),'configured':True}
        write(private_file,value)
        public = {key:val for key,val in value.items() if key!='credential'}
        public.update(parentRoot=str(root/'mht-gui-isolated'/module), accountId='acceptance-'+module,
            platform='wechat-article',origin=f'https://127.0.0.1:{PORTS[module]}',
            caFile=str(root/'loopback.pem'))
        write(root/(module+'-pairing.json'),public)
        write(root/(module+'-mht-gui.json'),{key:public[key] for key in ('parentRoot','origin','deviceId','caFile')})
        write(root/(module+'-configuration-journal.json'),{'native_API':admin.journal+advisor.journal,
            'production_mutations':False,'project_state':'paused','account_identity':'isolated test identity; real account unverified'})
        return public
    finally:
        admin.close();advisor.close()


def main():
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True)
    p.add_argument('--module',choices=('seo','geo'));p.add_argument('action',choices=('inventory','configure'))
    args=p.parse_args();root=owned(args.root)
    if args.action=='inventory':
        value=inventory(root);print(json.dumps({'inventory_saved':True,'initial_gates_preserved':True,
            'snapshot_sha256':value['snapshot_sha256']}))
    else:
        if not args.module:p.error('--module required for configure')
        value=configure(root,args.module)
        print(json.dumps({'module':args.module,'scope':value['scope'],'private_pairing_saved':True,
            'project_paused':True,'real_account_unverified':True}))


if __name__=='__main__': main()
