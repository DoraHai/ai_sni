"""Pinned manual-delivery proof and independently authenticated registration."""
import hashlib
import re
import secrets
from uuid import uuid4
from app import distribution_control as core

MHT_SOURCE_COMMIT = 'f271408e12c2569557e734029c720fb7f70a8903'
MHT_MANIFEST_SHA256 = 'd16ca1d08ab0eba00eef569ea014a55aa5c05f77ff443af983077338aea36136'

def frozen_manifest():
    """Pinned descriptive directory only; unavailable adapters grant no stages."""
    import hashlib, json
    from pathlib import Path
    raw = (Path(__file__).resolve().parents[1] / 'docs/fixtures/mht-distribution-capabilities-v1.json').read_bytes()
    if hashlib.sha256(raw).hexdigest() != MHT_MANIFEST_SHA256:
        raise ValueError('Frozen MHT manifest digest mismatch')
    return json.loads(raw)

def validate_manifest(value):
    """Reject changed or promoted capabilities until a new protocol is frozen."""
    if core.canonical(value) != core.canonical(frozen_manifest()):
        raise ValueError('Unsupported MHT manifest')
    return {'source_commit': MHT_SOURCE_COMMIT, 'manifest_digest': MHT_MANIFEST_SHA256,
            'stages': {}, 'automatic_publish': False}

def delivery_stages(value):
    validate_manifest(value)
    # This grants package preparation, never the unavailable channel publisher.
    return {c['v1Platform']: ['preflight', 'handoff'] for c in value['channels']
            if c['v1Platform'] and c['deliveryAvailable']}

async def authenticate(db, credential, device_id):
    await core.lock(db, 'device:' + device_id)
    device = await core.one(db, 'SELECT * FROM distribution_devices WHERE id=:id AND active', id=device_id)
    if not device or not secrets.compare_digest(device['credential_hash'], hashlib.sha256(credential.encode()).hexdigest()):
        raise core.problem('device_unauthorized', 401)
    return device

def registration_view(row):
    return {'capabilityVersion': 1, 'deviceId': row['device_id'],
            'registrationId': str(row['registration_id']), 'revision': row['revision'],
            'manifestDigest': row['manifest_digest'], 'attestationDigest': row['digest'],
            'expiresAt': row['expires_at'], 'active': row['active'],
            'allowedBindings': [{'bindingId': b['id'], 'platform': b['platform'],
                                 'stages': ['preflight', 'handoff']} for b in row['bindings']] if row['active'] else [],
            'automaticSubmit': False, 'publicationVerified': False}

async def request_prior(db, req, action):
    value=req.model_dump(mode='json')
    fp=hashlib.sha256(core.canonical({'action':action, 'request':value}).encode()).hexdigest()
    prior=await core.one(db,'SELECT fingerprint,response FROM distribution_capability_requests WHERE device_id=:device AND request_id=:id',device=req.deviceId,id=req.requestId)
    if prior and prior['fingerprint']!=fp:raise core.problem('idempotency_conflict')
    return fp,prior['response'] if prior else None

async def save_response(db,req,fp,response):
    await db.execute(core.text('INSERT INTO distribution_capability_requests VALUES(:device,:id,:fp,CAST(:response AS jsonb))'),
                     {'device':req.deviceId,'id':req.requestId,'fp':fp,'response':core.canonical(response)})

async def register(db, credential, req):
    await authenticate(db,credential,req.deviceId)
    fp,prior=await request_prior(db,req,'register')
    if prior:return prior
    if req.manifestDigest!=MHT_MANIFEST_SHA256:raise core.problem('capability_manifest_mismatch',422)
    try:stages=delivery_stages(req.manifest)
    except ValueError:raise core.problem('capability_manifest_mismatch',422) from None
    if not core.now_ms()<req.expiresAt<=core.now_ms()+86400000:raise core.problem('capability_expiry_invalid',422)
    old=await core.one(db,'SELECT * FROM distribution_device_capability_registrations WHERE device_id=:id',id=req.deviceId)
    if (old['revision'] if old else 0)!=req.expectedRevision:raise core.problem('version_conflict')
    bindings=[]
    for ident in sorted(req.bindingIds,key=str):
        b=await core.one(db,'SELECT * FROM distribution_bindings WHERE id=:id AND device_id=:device AND active',id=ident,device=req.deviceId)
        if not b or b['platform'] not in stages:raise core.problem('capability_binding_forbidden',403)
        bindings.append({k:str(b[k]) if k=='id' else b[k] for k in ('id','platform','account_id','external_account_id','tenant_id','module','scope_id')})
    same=old and old['active'] and old['bindings']==bindings
    registration_id=old['registration_id'] if same else uuid4()
    digest=hashlib.sha256(core.canonical({'device':req.deviceId,'registration':str(registration_id),'manifest':req.manifestDigest,'adapter':req.adapterVersion,'bindings':bindings}).encode()).hexdigest()
    admitted={b['platform']:stages[b['platform']] for b in bindings}
    if same:
        await db.execute(core.text('UPDATE distribution_capability_attestations SET expires_at=:expiry,recorded_at=:at WHERE device_id=:device AND digest=:digest'),{'expiry':req.expiresAt,'at':core.now_ms(),'device':req.deviceId,'digest':digest})
    else:await record_attestation(db,req.deviceId,digest,req.adapterVersion,admitted,req.expiresAt)
    row={'device_id':req.deviceId,'registration_id':registration_id,'revision':req.expectedRevision+1,'digest':digest,'manifest_digest':req.manifestDigest,'bindings':bindings,'active':True,'expires_at':req.expiresAt,'updated_at':core.now_ms()}
    await db.execute(core.text('INSERT INTO distribution_device_capability_registrations VALUES(:device_id,:registration_id,:revision,:digest,:manifest_digest,CAST(:bindings AS jsonb),:active,:expires_at,:updated_at) ON CONFLICT(device_id) DO UPDATE SET registration_id=EXCLUDED.registration_id,revision=EXCLUDED.revision,digest=EXCLUDED.digest,manifest_digest=EXCLUDED.manifest_digest,bindings=EXCLUDED.bindings,active=EXCLUDED.active,expires_at=EXCLUDED.expires_at,updated_at=EXCLUDED.updated_at'),{**row,'bindings':core.canonical(bindings)})
    response=registration_view(row);await save_response(db,req,fp,response)
    await core.audit(db,'device:'+req.deviceId,'manual_delivery_registered',{'device_id':req.deviceId},'PACKAGE_HANDOFF_ONLY')
    return response

async def revoke(db,credential,req):
    await authenticate(db,credential,req.deviceId)
    fp,prior=await request_prior(db,req,'revoke')
    if prior:return prior
    row=await core.one(db,'SELECT * FROM distribution_device_capability_registrations WHERE device_id=:id',id=req.deviceId)
    if not row or row['revision']!=req.expectedRevision:raise core.problem('version_conflict')
    row.update(active=False,revision=row['revision']+1,expires_at=core.now_ms(),updated_at=core.now_ms())
    await db.execute(core.text('UPDATE distribution_device_capability_registrations SET active=false,revision=:revision,expires_at=:at,updated_at=:at WHERE device_id=:device'),{'revision':row['revision'],'at':row['expires_at'],'device':req.deviceId})
    await db.execute(core.text('UPDATE distribution_capability_attestations SET expires_at=:at WHERE device_id=:device'),{'at':row['expires_at'],'device':req.deviceId})
    response=registration_view(row);await save_response(db,req,fp,response)
    await core.audit(db,'device:'+req.deviceId,'manual_delivery_revoked',{'device_id':req.deviceId},'REVOKED')
    return response

def directory():
    grouped = {}
    for channel in frozen_manifest()['channels']:
        key = 'website' if channel['platform'] == 'website-cms' else channel['platform']
        row = grouped.setdefault(key, {'platform_id': key, 'label': channel['name'],
            'content_types': [], 'v1_platform': None, 'native_intake': False,
            'automatic_publish': False, 'real_channel_verified': False,
            'status': 'reserved' if key == 'website' else 'not-integrated',
            'missing': ['独立官网发布接线'] if key == 'website' else ['原生渠道稿来源', '版本化执行协议', '冻结能力适配器']})
        row['content_types'].append(channel['contentType'])
        if channel['v1Platform']:
            row.update(v1_platform=channel['v1Platform'], native_intake=True,
                       status='manual-handoff-candidate', missing=['真实发布适配器尚未验收'])
    from app.distribution_api_orders import directory as api_directory
    return list(grouped.values())+api_directory()

async def record_attestation(db,device_id,digest,adapter_version,stages,expires_at):
    """Internal normalized store; register authenticates and pins the manifest.

    Direct synthetic attestations are test fixtures, not device authorization.
    """
    if not re.fullmatch('[a-f0-9]{64}',digest) or not re.fullmatch('[a-zA-Z0-9_-]{1,100}',adapter_version):raise ValueError('Invalid attestation identity')
    if not isinstance(stages,dict) or set(stages)-{'wechat-article','xiaohongshu-image'} or any(not isinstance(s,list) or not s or len(set(s))!=len(s) or set(s)-{'preflight','handoff'} for s in stages.values()):raise ValueError('Unsupported stage')
    if type(expires_at)is not int or not core.now_ms()<expires_at<=core.now_ms()+86400000:raise ValueError('Invalid attestation expiry')
    await core.lock(db,'device:'+device_id)
    device=await core.one(db,'SELECT id FROM distribution_devices WHERE id=:id AND active',id=device_id)
    if not device:raise core.problem('device_unauthorized',401)
    old=await core.one(db,'SELECT * FROM distribution_capability_attestations WHERE device_id=:device AND digest=:digest',device=device_id,digest=digest)
    if old:
        if old['adapter_version']!=adapter_version or old['stages']!=stages or old['expires_at']!=expires_at:raise core.problem('idempotency_conflict')
        return
    await db.execute(core.text('INSERT INTO distribution_capability_attestations VALUES(:device,:digest,:adapter,CAST(:stages AS jsonb),:expiry,:at)'),{'device':device_id,'digest':digest,'adapter':adapter_version,'stages':core.canonical(stages),'expiry':expires_at,'at':core.now_ms()})
    await core.audit(db,'capability-adapter','capability_verified',{'device_id':device_id},'HANDOFF_ONLY')

async def current(db,device_id,platform,stage,digest=None,binding_id=None):
    installed=(await core.one(db,"SELECT to_regclass(current_schema()||'.distribution_device_capability_registrations') IS NOT NULL AS ready"))['ready']
    if installed:
        registration=await core.one(db,'SELECT * FROM distribution_device_capability_registrations WHERE device_id=:device',device=device_id)
        if registration and (not registration['active'] or registration['expires_at']<=core.now_ms() or digest is not None and digest!=registration['digest'] or binding_id is not None and not any(b['id']==str(binding_id) and b['platform']==platform for b in registration['bindings'])):return None
    row=await core.one(db,'SELECT * FROM distribution_capability_attestations WHERE device_id=:device ORDER BY recorded_at DESC,digest DESC LIMIT 1',device=device_id)
    return row if row and row['expires_at']>core.now_ms() and stage in row['stages'].get(platform,[]) and (digest is None or row['digest']==digest) else None
