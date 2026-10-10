"""Fixed platform connection catalogue and isolated runtime settings.

Only public provider parameters enter metadata/audit. Secrets are an encrypted
bundle, never returned. Database, JWT, crypto and money-write switches are not
editable here. Existing tenant credentials and authorization rules still apply.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from contextvars import ContextVar
from functools import wraps
import hashlib
import json
import os
import re
from urllib.parse import urlsplit

current_settings = ContextVar('managed_api_settings', default=None)


def entry(module, code, label, base_attr, hosts, *, key_attr=None, model_attr=None,
          timeout_attr=None, enabled_attr=None, secrets=None, parameters=None):
    fields = {'enabled': {'type': 'boolean', 'label': '平台默认配置启用', 'attr': enabled_attr}}
    if base_attr:
        fields['base_url'] = {'type': 'url', 'label': '接口地址', 'attr': base_attr, 'hosts': hosts}
    if model_attr:
        fields['model'] = {'type': 'model', 'label': '默认模型', 'attr': model_attr}
    if timeout_attr:
        fields['timeout_seconds'] = {'type': 'timeout', 'label': '超时（秒）', 'attr': timeout_attr}
    fields.update(parameters or {})
    return dict(id=module+'.'+code, module=module, label=label, fields=fields,
                secrets=secrets or ({'api_key': {'label': 'API Key', 'attr': key_attr}} if key_attr else {}))


CATALOG = {}
for module in ('sem', 'seo', 'geo'):
    for prefix, label, host in (('dashscope','阿里云百炼','dashscope.aliyuncs.com'),('deepseek','DeepSeek 官方','api.deepseek.com')):
        spec=entry(module,prefix,label,prefix+'_base_url',(host,),key_attr=prefix+'_api_key',model_attr=prefix+'_model')
        CATALOG[spec['id']]=spec
for module in ('seo','geo'):
    names=(('api_key','通用 Key'),('baidu_index_api_key','百度收录'),('baidu_pc_keywords_api_key','百度 PC 网站关键词'),
           ('baidu_mobile_keywords_api_key','百度移动网站关键词'),('baidu_pc_top50_api_key','百度 PC Top50 / 排名'),
           ('baidu_mobile_top50_api_key','百度移动 Top50 / 排名'),('weight_all_api_key','综合权重'),('whois_api_key','Whois'))
    spec=entry(module,'chinaz','站长之家','chinaz_api_base_url',('openapi.chinaz.net',),
               timeout_attr='chinaz_api_timeout_seconds',enabled_attr='chinaz_api_enabled',
               secrets={k:{'label':label,'attr':'chinaz_'+k} for k,label in names})
    CATALOG[spec['id']]=spec
    spec=entry(module,'pagespeed','Google PageSpeed','pagespeed_api_base_url',('pagespeedonline.googleapis.com',),
               key_attr='pagespeed_api_key',timeout_attr='pagespeed_api_timeout_seconds',enabled_attr='pagespeed_api_enabled')
    CATALOG[spec['id']]=spec
spec=entry('sem','baidu','百度推广开发者配置','baidu_api_base_url',('api.baidu.com',),
           secrets={'secret_key':{'label':'开发者 Secret Key','attr':'baidu_secret_key'}},
           parameters={'app_id':{'type':'model','label':'开发者 App ID','attr':'baidu_app_id'},
                       'oauth_base_url':{'type':'url','label':'百度授权接口地址','attr':'baidu_oauth_base_url','hosts':('u.baidu.com',)}})
CATALOG[spec['id']]=spec
spec=entry('seo','dataforseo','DataForSEO','seo_dataforseo_base_url',('api.dataforseo.com',),
           enabled_attr='seo_dataforseo_enabled',
           secrets={'login':{'label':'API 登录账号','attr':'seo_dataforseo_login','min_length':1},
                    'password':{'label':'API 密码','attr':'seo_dataforseo_password'}})
CATALOG[spec['id']]=spec
for code,label,host in (('openai','OpenAI','api.openai.com'),('deepseek','DeepSeek 采样','api.deepseek.com'),
                       ('qwen','通义千问','dashscope.aliyuncs.com'),('doubao','豆包','ark.cn-beijing.volces.com'),
                       ('hunyuan','腾讯混元','api.hunyuan.cloud.tencent.com'),('qianfan','百度千帆','qianfan.bj.baidubce.com'),
                       ('kimi','Kimi','api.moonshot.cn'),('perplexity','Perplexity','api.perplexity.ai')):
    prefix='geo_'+code
    spec=entry('geo',prefix,label+' · 平台采样',prefix+'_base_url',(host,),key_attr=prefix+'_api_key',model_attr=prefix+'_model')
    CATALOG[spec['id']]=spec
spec=entry('geo','tencent_wsa','腾讯 WSA 搜索','geo_tencent_wsa_base_url',('api.wsa.cloud.tencent.com',),key_attr='geo_tencent_wsa_api_key')
CATALOG[spec['id']]=spec

RUNTIME_FIELDS = {
    'sem': (('百度资金写回演练模式','baidu_write_dry_run'),),
    'seo': (('排名自动采集','seo_rank_scheduler_enabled'),('排名采集引擎','seo_rank_scheduler_engines'),
            ('各引擎采集间隔（天）','seo_rank_scheduler_engine_interval_days')),
    'geo': (('内容调度','geo_scheduler_enabled'),('后续任务调度','geo_followup_scheduler_enabled'),
            ('异步执行器','geo_async_worker_enabled'),('巡检执行','geo_patrol_execution_enabled'),
            ('模型执行','geo_model_execution_enabled'),('内容生成','geo_content_generation_enabled'),
            ('渠道发布','geo_publishing_enabled'),('渠道授权','geo_oauth_enabled'),
            ('异常任务恢复','geo_stale_reconciliation_enabled'),('启动恢复','geo_startup_recovery_enabled'),
            ('单次巡检格数上限','geo_patrol_max_cells_per_run'),('巡检默认词数','geo_patrol_default_prompt_limit')),
}


def public_runtime(module, settings):
    return [{'label':label,'value':getattr(settings,attr)} for label,attr in RUNTIME_FIELDS.get(module,()) if hasattr(settings,attr)]


def credential_id(config_id):
    return hashlib.sha256(('platform-connection\0'+config_id).encode()).hexdigest()


def spec_for(key):
    code=key.removeprefix('connection:') if isinstance(key,str) else ''
    if code not in CATALOG or key!='connection:'+code:
        raise ValueError('接口配置范围无效')
    return CATALOG[code]


def validate_connection(key, value):
    spec=spec_for(key)
    if not isinstance(value,dict) or set(value)!={'parameters','secrets','restore'} or type(value['restore']) is not bool:
        raise ValueError('接口配置格式无效')
    params,secrets=value['parameters'],value['secrets']
    if not isinstance(params,dict) or not isinstance(secrets,dict) or set(params)-set(spec['fields']) or set(secrets)-set(spec['secrets']):
        raise ValueError('接口配置包含不支持的字段')
    if value['restore'] and (params or secrets):
        raise ValueError('恢复服务器配置时不能同时提交参数或密钥')
    clean={}
    for name,item in params.items():
        kind=spec['fields'][name]['type']
        if kind=='boolean':
            if type(item) is not bool: raise ValueError('启用状态无效')
        elif kind=='timeout':
            if type(item) not in (int,float) or not 1<=item<=120: raise ValueError('超时应为 1 至 120 秒')
        elif kind=='model':
            if not isinstance(item,str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:/-]{0,119}',item): raise ValueError('模型或 App ID 格式无效')
        elif kind=='url':
            if not isinstance(item,str) or len(item)>500 or any(ord(c)<33 for c in item): raise ValueError('接口地址无效')
            url=urlsplit(item)
            if url.scheme!='https' or url.hostname not in spec['fields'][name]['hosts'] or url.port not in (None,443) or url.username or url.password or url.query or url.fragment or '%' in url.path or '..' in url.path:
                raise ValueError('接口地址必须使用该服务商的官方 HTTPS 域名，不含认证或查询参数')
            item=item.rstrip('/')
        clean[name]=item
    secret_clean={}
    for name,item in secrets.items():
        minimum=spec['secrets'][name].get('min_length',8)
        if item is not None and (not isinstance(item,str) or not minimum<=len(item)<=4096 or any(ord(c)<32 for c in item)):
            raise ValueError('密钥格式无效，请重新输入')
        secret_clean[name]=item
    return clean,secret_clean,value['restore']


def public_defaults(spec, settings):
    parameters={}
    for name,field in spec['fields'].items():
        attr=field['attr']
        if name=='enabled': parameters[name]=bool(getattr(settings,attr,True)) if attr else True
        elif attr and hasattr(settings,attr):
            value=getattr(settings,attr)
            # Server URLs may contain legacy authentication. Never publish them.
            if field['type']=='url':
                try:
                    value=validate_connection('connection:'+spec['id'],
                        {'parameters':{name:value},'secrets':{},'restore':False})[0][name]
                except (ValueError,TypeError): value=''
            parameters[name]=value
    secrets={name:bool(getattr(settings,field['attr'],'') or '') for name,field in spec['secrets'].items()}
    supported=all(hasattr(settings,f['attr']) for f in spec['secrets'].values())
    return {'parameters':parameters,'secrets':secrets,'supported':supported}


def public_connections(bindings,settings):
    registered={(r['module'],r['label']):r for r in bindings}
    policies={r['key']:r for r in settings if r['kind']=='connection'}
    result=[]
    for spec in CATALOG.values():
        row=registered.get((spec['module'],'connection:'+spec['id']))
        defaults=(row or {}).get('metadata') or {}
        policy=policies.get('connection:'+spec['id']) or {}
        value=policy.get('value') or {}
        parameters={**defaults.get('parameters',{}),**value.get('parameters',{})}
        secrets={**defaults.get('secrets',{}),**value.get('secrets',{})}
        result.append({'id':spec['id'],'module':spec['module'],'label':spec['label'],
          'registered':row is not None,'supported':bool(defaults.get('supported')),
          'parameters':parameters,'secret_status':secrets,'revision':policy.get('revision',0),
          'source':'managed' if value.get('parameters') or value.get('secrets') else 'server',
          'fields':[{k:v for k,v in f.items() if k!='attr'}|{'name':name} for name,f in spec['fields'].items()],
          'secret_fields':[{'name':name,'label':f['label']} for name,f in spec['secrets'].items()],
          'note':'当前默认检测使用本地 Lighthouse；本项管理远程 PageSpeed 凭据，不切换检测模式。' if spec['id'].endswith('.pagespeed') else '',
          'seen_at':(row or {}).get('seen_at')})
    return result


async def register_connections(session,module,settings):
    from sqlalchemy import text
    for spec in CATALOG.values():
        if spec['module']!=module: continue
        metadata=public_defaults(spec,settings)
        if spec['id']==module+'.dashscope': metadata['runtime']=public_runtime(module,settings)
        url=metadata['parameters'].get('base_url') or ''
        await session.execute(text('''INSERT INTO api_control_bindings(id,module,label,host,model,configured,can_rotate,metadata)
          VALUES(:id,:module,:label,:host,:model,:configured,false,CAST(:metadata AS jsonb))
          ON CONFLICT(module,label) DO UPDATE SET host=excluded.host,model=excluded.model,
          configured=excluded.configured,metadata=excluded.metadata,seen_at=CURRENT_TIMESTAMP'''),
          {'id':credential_id(spec['id']),'module':module,'label':'connection:'+spec['id'],
           'host':urlsplit(url).hostname or '', 'model':metadata['parameters'].get('model'),
           'configured':any(metadata['secrets'].values()),'metadata':json.dumps(metadata)})


async def load_settings(module):
    from sqlalchemy import text
    from app.api_controls import async_session_factory, ControlDenied
    from app.config import get_server_settings
    from app.security.crypto import decrypt
    base=get_server_settings()
    updates={}
    try:
        async with asyncio.timeout(6),async_session_factory() as session:
            await session.execute(text('SET TRANSACTION READ ONLY'))
            await session.execute(text("SET LOCAL statement_timeout='3000ms'"))
            rows=(await session.execute(text('''SELECT key,value FROM api_control_settings
              WHERE kind='connection' AND key LIKE :prefix'''),{'prefix':'connection:'+module+'.%'})).mappings().all()
            ids=[credential_id(spec_for(row['key'])['id']) for row in rows]
            bundles=dict((await session.execute(text('''SELECT id,ciphertext FROM api_control_credentials
              WHERE id=ANY(CAST(:ids AS varchar[]))'''),{'ids':ids})).all()) if ids else {}
            await session.rollback()
    except Exception:
        raise ControlDenied('平台接口配置暂时无法读取，请联系超级管理员') from None
    for row in rows:
        spec=spec_for(row['key'])
        value=row['value']
        for name,item in value.get('parameters',{}).items():
            attr=spec['fields'][name]['attr']
            if attr and hasattr(base,attr): updates[attr]=item
        ciphertext=bundles.get(credential_id(spec['id']))
        if ciphertext:
            try: bundle=json.loads(decrypt(ciphertext))
            except Exception: raise ControlDenied('平台密钥无法解密，请联系超级管理员') from None
            for name,item in bundle.items():
                attr=spec['secrets'][name]['attr']
                if hasattr(base,attr): updates[attr]=item or ''
        if value.get('parameters',{}).get('enabled') is False:
            for secret in spec['secrets'].values():
                if hasattr(base,secret['attr']): updates[secret['attr']]=''
    return base.model_copy(update=updates)


@asynccontextmanager
async def runtime_scope(module):
    if os.environ.get('API_CONTROLS_ENABLED','').lower()!='true' or current_settings.get() is not None:
        yield
        return
    token=current_settings.set(await load_settings(module))
    try: yield
    finally: current_settings.reset(token)


def managed_runtime(module=None):
    def decorate(func):
        @wraps(func)
        async def run(*args,**kwargs):
            from app.api_metering import scope
            from app.api_controls import SERVICE_MODULE
            selected=module or scope.get().module or SERVICE_MODULE
            if selected=='unknown': selected=SERVICE_MODULE
            async with runtime_scope(selected):
                return await func(*args,**kwargs)
        return run
    return decorate
