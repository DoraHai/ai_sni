"""Single-owner, ephemeral remote account-window broker. No publish authority."""
import asyncio
import hashlib
import os
import secrets
import struct
import zlib
from uuid import uuid4

import asyncpg
from fastapi import HTTPException
from app import distribution_control as core
from app.distribution_remote_contract import SessionView

TTL_MS=600000
FRAME_FRESH_MS=5000
MAX_PNG=2097152
MAX_SESSIONS=8
MAX_READ_FRAMES=16
ACTIVE={'requested','active'}


def error(code,status=409):
    return HTTPException(status,{'code':code},headers={'Cache-Control':'no-store'})


def png_dimensions(raw):
    """Bounded non-interlaced Chromium RGB/RGBA PNG, including bounded inflate."""
    if not 57<=len(raw)<=MAX_PNG or raw[:8]!=b'\x89PNG\r\n\x1a\n':raise error('REMOTE_INVALID_PNG',422)
    at=8;idat=[];width=height=channels=None;ended=False
    while at<len(raw):
        if at+12>len(raw):raise error('REMOTE_INVALID_PNG',422)
        size=struct.unpack('>I',raw[at:at+4])[0];kind=raw[at+4:at+8]
        if size>MAX_PNG or at+12+size>len(raw):raise error('REMOTE_INVALID_PNG',422)
        data=raw[at+8:at+8+size]
        if zlib.crc32(kind+data)&0xffffffff!=struct.unpack('>I',raw[at+8+size:at+12+size])[0]:raise error('REMOTE_INVALID_PNG',422)
        if at==8 and kind!=b'IHDR':raise error('REMOTE_INVALID_PNG',422)
        if kind==b'IHDR':
            if width is not None or size!=13:raise error('REMOTE_INVALID_PNG',422)
            width,height,depth,color,compression,filters,interlace=struct.unpack('>IIBBBBB',data)
            if not 1<=width<=1920 or not 1<=height<=1080 or (depth,color,compression,filters,interlace) not in [(8,2,0,0,0),(8,6,0,0,0)]:
                raise error('REMOTE_INVALID_PNG',422)
            channels=3 if color==2 else 4
        elif kind==b'IDAT':idat.append(data)
        elif kind==b'IEND':
            if size or at+12!=len(raw):raise error('REMOTE_INVALID_PNG',422)
            ended=True
        elif kind in (b'acTL',b'fcTL',b'fdAT') or not kind[0]&32:raise error('REMOTE_INVALID_PNG',422)
        at+=12+size
    if not ended or width is None or not idat:raise error('REMOTE_INVALID_PNG',422)
    expected=height*(1+width*channels)
    try:
        decoder=zlib.decompressobj();pixels=decoder.decompress(b''.join(idat),expected+1)
        if len(pixels)!=expected or not decoder.eof or decoder.unused_data or decoder.unconsumed_tail:
            raise ValueError()
        if any(pixels[row*(1+width*channels)]>4 for row in range(height)):raise ValueError()
    except (zlib.error,ValueError):raise error('REMOTE_INVALID_PNG',422) from None
    return width,height


class Broker:
    def __init__(self):
        self.epoch=str(uuid4());self.owner=None;self.nonces={};self.frames={};self.payloads={};self.owner_guard=asyncio.Lock()
        self.sweeper=None;self.payload_expiry={};self.frame_expiry={};self.owner_key=None;self.creation_guard=asyncio.Lock()
        self.read_frames={}

    async def start(self,engine):
        if os.environ.get('DISTRIBUTION_REMOTE_CONTROL_ENABLED')!='true':return
        if self.owner is not None:raise RuntimeError('Remote broker lifecycle already started')
        async with engine.connect() as db:
            schema=await db.scalar(core.text('SELECT current_schema()'))
        if not schema or not schema.replace('_','').isalnum():raise RuntimeError('Remote schema unavailable')
        # Dedicated connection: ownership does not consume a normal API pool slot.
        conn=await asyncpg.connect(engine.url.set(drivername='postgresql').render_as_string(hide_password=False),
            server_settings={'search_path':schema,'timezone':'UTC','statement_timeout':'5000'},timeout=5)
        try:
            owner_key=await conn.fetchval("SELECT hashtext('distribution-remote-v1:'||current_schema())::bigint")
            acquired=await conn.fetchval('SELECT pg_try_advisory_lock($1::bigint)',owner_key)
            if not acquired:raise RuntimeError('Remote broker already owned; single-worker required')
            self.epoch=str(uuid4())
            async with conn.transaction():
                await conn.execute("UPDATE distribution_remote_commands SET state=CASE WHEN state='delivered' THEN 'unknown' ELSE 'canceled' END,code='BROKER_RESTARTED' WHERE state IN ('queued','delivered')")
                await conn.execute("UPDATE distribution_remote_sessions SET state='closed',code='BROKER_RESTARTED',closed_at=$1,last_command_state=(SELECT state FROM distribution_remote_commands WHERE id=last_command_id) WHERE state IN ('requested','active')",core.now_ms())
            self.owner=conn;self.owner_key=owner_key
            self.sweeper=asyncio.create_task(self.sweep())
        except BaseException:
            await conn.close();raise

    async def stop(self):
        if self.sweeper:
            self.sweeper.cancel()
            try:await self.sweeper
            except asyncio.CancelledError:pass
            self.sweeper=None
        self.nonces.clear();self.frames.clear();self.payloads.clear()
        self.read_frames.clear()
        self.payload_expiry.clear();self.frame_expiry.clear()
        owner,self.owner=self.owner,None
        if owner is not None:await owner.close(timeout=2)

    async def sweep(self):
        while True:
            await asyncio.sleep(1);now=core.now_ms()
            for ident,(_,expires) in list(self.nonces.items()):
                if expires<=now:self.forget(ident)
            for ident,expires in list(self.payload_expiry.items()):
                if expires<=now:self.payloads.pop(ident,None);self.payload_expiry.pop(ident,None)
            for ident,expires in list(self.frame_expiry.items()):
                if expires<=now:self.frames.pop(ident,None);self.frame_expiry.pop(ident,None)
            for ident in list(self.read_frames):self.prune_reads(ident,now)

    async def ready(self):
        if os.environ.get('DISTRIBUTION_REMOTE_CONTROL_ENABLED')!='true':raise error('REMOTE_DISABLED',503)
        if self.owner is None or self.owner.is_closed():
            self.nonces.clear();self.frames.clear();self.payloads.clear()
            self.read_frames.clear()
            raise error('REMOTE_BROKER_UNAVAILABLE',503)
        try:
            async with self.owner_guard:
                owned=await asyncio.wait_for(self.owner.fetchval("SELECT EXISTS(SELECT 1 FROM pg_locks WHERE locktype='advisory' AND pid=pg_backend_pid() AND mode='ExclusiveLock' AND granted AND classid=(($1::bigint>>32)&4294967295)::oid AND objid=($1::bigint&4294967295)::oid AND objsubid=1)",self.owner_key),2)
                if not owned:
                    self.nonces.clear();self.frames.clear();self.payloads.clear()
                    self.read_frames.clear()
                    raise error('REMOTE_BROKER_UNAVAILABLE',503)
        except (asyncpg.PostgresError,asyncpg.InterfaceError,OSError,asyncio.TimeoutError):
            self.nonces.clear();self.frames.clear();self.payloads.clear()
            self.read_frames.clear()
            raise error('REMOTE_BROKER_UNAVAILABLE',503) from None

    def forget(self,session_id):
        ident=str(session_id);self.nonces.pop(ident,None);self.frames.pop(ident,None);self.frame_expiry.pop(ident,None)
        self.read_frames.pop(ident,None)
        for key,value in list(self.payloads.items()):
            if value['session_id']==ident:self.payloads.pop(key,None);self.payload_expiry.pop(key,None)

    def prune_reads(self,ident,now):
        history=self.read_frames.get(ident)
        if history is None:return
        for seq,(_,captured) in list(history.items()):
            if now-captured>FRAME_FRESH_MS:history.pop(seq,None)
        if not history:self.read_frames.pop(ident,None)

    def note_read(self,row):
        """Record only metadata for a frame returned to its authenticated controller."""
        ident=str(row['id']);now=core.now_ms()
        if (row['state'] not in ACTIVE or ident not in self.nonces
                or self.nonces[ident][1]<=now or now-row['captured_at']>FRAME_FRESH_MS):return
        self.prune_reads(ident,now)
        history=self.read_frames.setdefault(ident,{})
        history[row['last_frame_seq']]=(row['control_revision'],row['captured_at'])
        while len(history)>MAX_READ_FRAMES:history.pop(next(iter(history)))

    def authorized_frame(self,row,seq,revision):
        ident=str(row['id']);self.prune_reads(ident,core.now_ms())
        meta=self.read_frames.get(ident,{}).get(seq)
        return meta if meta and revision==row['control_revision'] and meta[0]==revision else None

    async def close_row(self,db,row,code,state='closed'):
        self.forget(row['id'])
        await db.execute(core.text("UPDATE distribution_remote_commands SET state=CASE WHEN state='delivered' THEN 'unknown' ELSE 'canceled' END,code=:code WHERE session_id=:id AND state IN ('queued','delivered')"),{'id':row['id'],'code':code})
        await db.execute(core.text('UPDATE distribution_remote_sessions SET state=:state,code=:code,closed_at=:at,last_command_state=(SELECT state FROM distribution_remote_commands WHERE id=last_command_id) WHERE id=:id'),{'id':row['id'],'state':state,'code':code,'at':core.now_ms()})
        if row.get('last_command_state') in ('queued','delivered'):
            row['last_command_state']='canceled' if row['last_command_state']=='queued' else 'unknown'
        row.update(state=state,code=code,closed_at=core.now_ms())
        await core.audit(db,row['controller_user_id'],'remote_closed',{'module':row['module'],'tenant_id':row['tenant_id'],
            'scope_id':row['scope_id'],'binding_id':str(row['binding_id']),'session_id':str(row['id'])},code)

    async def binding(self,db,binding_id,scope):
        peek=await core.one(db,'SELECT device_id FROM distribution_bindings WHERE id=:id',id=binding_id)
        if not peek:raise error('REMOTE_SCOPE_FORBIDDEN',403)
        await core.lock(db,'device:'+peek['device_id'])
        await core.lock(db,'scope:'+core.canonical(scope))
        b=await core.one(db,'SELECT b.*,d.active AS device_active FROM distribution_bindings b JOIN distribution_devices d ON d.id=b.device_id WHERE b.id=:id',id=binding_id)
        if not b or not b['active'] or not b['device_active'] or any(b[k]!=scope[k] for k in scope) or b['platform']!='wechat-article':
            raise error('REMOTE_SCOPE_FORBIDDEN',403)
        return b

    async def authority(self,db,actor,scope):
        try:await core.authorize_scope(db,actor,scope)
        except HTTPException as exc:
            if exc.status_code>=500:raise error('REMOTE_UNAVAILABLE',503) from None
            raise error('REMOTE_SCOPE_FORBIDDEN',403) from None

    async def task_current(self,db,row):
        if row['purpose']!='task-intervention':return
        bound=row['task'];scope={k:row[k] for k in ('module','tenant_id','scope_id')}
        t=await core.one(db,'SELECT * FROM distribution_tasks WHERE id=:id FOR UPDATE',id=bound['task_id'])
        control=await core.one(db,'SELECT * FROM distribution_controls WHERE module=:module AND tenant_id=:tenant_id AND scope_id=:scope_id',**scope)
        now=core.now_ms()
        if (not t or any(str(t[k])!=str(bound[k]) for k in ('grant_id','lease_id','source_revision','content_digest'))
                or any(t[k]!=row[k] for k in ('module','tenant_id','scope_id','binding_id','device_id','account_id','platform'))
                or t['revoked'] or t['action'] not in ('preflight','handoff') or t['publication_grant_id'] is not None
                or t['advisor_user_id']!=row['controller_user_id'] or not control or control['state']!='running'
                or control['owner_user_id']!=row['controller_user_id'] or control['revision']!=row['project_revision']
                or t['status'] not in ('leased','running','awaiting-human')
                or t['grant_expires_at']<=now or not t['lease_expires_at'] or t['lease_expires_at']<=now):
            raise error('REMOTE_TASK_UNAVAILABLE')
        try:
            source,digest=await core.source(db,row['controller_user_id'],scope,t['variant_id'],t['platform'])
        except HTTPException as exc:
            if exc.status_code>=500:raise error('REMOTE_UNAVAILABLE',503) from None
            raise error('REMOTE_SOURCE_CHANGED') from None
        if source['source_revision']!=bound['source_revision'] or digest!=bound['content_digest']:
            raise error('REMOTE_SOURCE_CHANGED')

    async def checked(self,db,session_id,actor=None,device=None,*,allow_closed=False):
        await self.ready()
        peek=await core.one(db,'SELECT * FROM distribution_remote_sessions WHERE id=:id',id=session_id)
        if not peek or actor is not None and peek['controller_user_id']!=actor or device is not None and peek['device_id']!=device:
            raise error('REMOTE_SCOPE_FORBIDDEN',403)
        scope={k:peek[k] for k in ('module','tenant_id','scope_id')}
        try:
            b=await self.binding(db,peek['binding_id'],scope)
            await self.authority(db,peek['controller_user_id'],scope)
        except HTTPException as exc:
            if exc.status_code>=500:raise
            if peek['state'] in ACTIVE:
                await self.close_row(db,peek,'AUTHORIZATION_REVOKED');await db.commit()
            raise
        row=await core.one(db,'SELECT * FROM distribution_remote_sessions WHERE id=:id FOR UPDATE',id=session_id)
        current_account_key=hashlib.sha256((b['platform']+':'+b['external_account_id']).encode()).hexdigest()
        if row['account_id']!=b['account_id'] or row['device_id']!=b['device_id'] or row['account_key']!=current_account_key:
            await self.close_row(db,row,'AUTHORIZATION_REVOKED');await db.commit();raise error('REMOTE_SCOPE_FORBIDDEN',403)
        if row['state'] not in ACTIVE:
            if allow_closed:return row
            raise error('REMOTE_SESSION_CLOSED',410)
        if str(row['broker_epoch'])!=self.epoch or str(row['id']) not in self.nonces:
            await self.close_row(db,row,'BROKER_RESTARTED');await db.commit();raise error('REMOTE_SESSION_CLOSED',410)
        if row['expires_at']<=core.now_ms():
            await self.close_row(db,row,'SESSION_EXPIRED','expired');await db.commit()
            if allow_closed:return row
            raise error('REMOTE_SESSION_EXPIRED',410)
        try:await self.task_current(db,row)
        except HTTPException:
            await self.close_row(db,row,'TASK_AUTHORIZATION_CHANGED');await db.commit();raise
        return row

    def view(self,row):
        frame=None
        if row['state'] in ACTIVE and row['last_frame_seq']:
            frame={k:row[k] for k in ('control_revision','viewport_width','viewport_height','captured_at','uploaded_at')}
            frame['frame_seq']=row['last_frame_seq']
        fields={k:row[k] for k in ('id','module','tenant_id','scope_id','binding_id','device_id','account_id','platform','purpose','task',
            'controller_user_id','broker_epoch','state','code','expires_at','control_revision','last_command_id','last_command_state')}
        return SessionView.model_validate({**fields,'frame':frame}).model_dump(mode='json')

    async def create(self,db,actor,req):
        await self.ready();scope=req.model_dump(include={'module','tenant_id','scope_id'})
        b=await self.binding(db,req.binding_id,scope);await self.authority(db,actor,scope)
        await core.lock(db,'remote-account:'+b['platform']+':'+b['external_account_id'])
        old=await core.one(db,'SELECT * FROM distribution_remote_sessions WHERE controller_user_id=:actor AND create_request_id=:request',actor=actor,request=req.request_id)
        fingerprint=hashlib.sha256(core.canonical(req.model_dump(mode='json')).encode()).hexdigest()
        if old:
            if old['create_fingerprint']!=fingerprint:raise error('REMOTE_IDEMPOTENCY_CONFLICT')
            old=await self.checked(db,old['id'],actor)
            return {'schema':1,'session':self.view(old),'control_nonce':self.nonces[str(old['id'])][0]}
        account_key=hashlib.sha256((b['platform']+':'+b['external_account_id']).encode()).hexdigest()
        occupied=await core.rows(db,"SELECT * FROM distribution_remote_sessions WHERE (device_id=:device OR account_key=:account) AND state IN ('requested','active') FOR UPDATE",device=b['device_id'],account=account_key)
        for row in occupied:
            if row['expires_at']<=core.now_ms():await self.close_row(db,dict(row),'SESSION_EXPIRED','expired')
            else:raise error('REMOTE_SESSION_BUSY')
        now=core.now_ms()
        for sid,(_,expiry) in list(self.nonces.items()):
            if expiry<=now:self.forget(sid)
        if len(self.nonces)>=MAX_SESSIONS:raise error('REMOTE_CAPACITY',503)
        ident=uuid4();nonce=secrets.token_urlsafe(32)
        row={'id':ident,'broker_epoch':self.epoch,'controller_user_id':actor,'create_request_id':req.request_id,
            'create_fingerprint':fingerprint,**scope,'binding_id':req.binding_id,'device_id':b['device_id'],'account_id':b['account_id'],
            'platform':b['platform'],'account_key':account_key,'purpose':req.purpose,'task':None,'project_revision':None,
            'nonce_hash':hashlib.sha256(nonce.encode()).hexdigest(),'state':'requested','code':'SESSION_REQUESTED','created_at':now,'expires_at':now+TTL_MS}
        if req.task:
            current=await core.one(db,'SELECT * FROM distribution_tasks WHERE id=:id FOR UPDATE',id=req.task.task_id)
            if (not current or any(current[k]!=row[k] for k in ('module','tenant_id','scope_id','binding_id','device_id','account_id','platform'))
                    or current['source_revision']!=req.task.expected_source_revision or current['content_digest']!=req.task.expected_content_digest):
                raise error('REMOTE_TASK_UNAVAILABLE')
            row['task']={'task_id':str(current['id']),**{k:str(current[k]) for k in ('grant_id','lease_id','source_revision','content_digest')}}
            control=await core.one(db,'SELECT * FROM distribution_controls WHERE module=:module AND tenant_id=:tenant_id AND scope_id=:scope_id',**scope)
            if not control:raise error('REMOTE_TASK_UNAVAILABLE')
            row['project_revision']=control['revision']
        await self.task_current(db,row)
        self.nonces[str(ident)]=(nonce,row['expires_at'])
        try:
            await db.execute(core.text('INSERT INTO distribution_remote_sessions(id,broker_epoch,controller_user_id,create_request_id,create_fingerprint,module,tenant_id,scope_id,binding_id,device_id,account_id,platform,account_key,purpose,task,project_revision,nonce_hash,state,code,created_at,expires_at) VALUES(:id,:broker_epoch,:controller_user_id,:create_request_id,:create_fingerprint,:module,:tenant_id,:scope_id,:binding_id,:device_id,:account_id,:platform,:account_key,:purpose,CAST(:task AS jsonb),:project_revision,:nonce_hash,:state,:code,:created_at,:expires_at)'),{**row,'task':core.canonical(row['task']) if row['task'] else None})
            row=await core.one(db,'SELECT * FROM distribution_remote_sessions WHERE id=:id',id=ident)
            await core.audit(db,actor,'remote_created',{**scope,'binding_id':str(req.binding_id),'session_id':str(ident),'purpose':req.purpose},'SESSION_REQUESTED')
            return {'schema':1,'session':self.view(row),'control_nonce':nonce}
        except BaseException:self.forget(ident);raise

    def nonce(self,row,nonce):
        if not secrets.compare_digest(row['nonce_hash'],hashlib.sha256(nonce.encode()).hexdigest()):raise error('REMOTE_CONTROL_FORBIDDEN',403)

    async def input(self,db,actor,ident,req):
        row=await self.checked(db,ident,actor);self.nonce(row,req.control_nonce)
        if row['last_command_state']=='unknown':raise error('REMOTE_COMMAND_UNKNOWN')
        basis=self.authorized_frame(row,req.frame_seq,req.control_revision)
        if row['state']!='active' or basis is None:raise error('REMOTE_FRAME_STALE')
        if req.input.kind=='mouse' and (req.input.x>=row['viewport_width'] or req.input.y>=row['viewport_height']):raise error('REMOTE_INPUT_OUTSIDE_VIEWPORT',422)
        if await core.one(db,'SELECT id FROM distribution_remote_commands WHERE id=:id',id=req.command_id):raise error('REMOTE_COMMAND_DUPLICATE')
        waiting=await core.one(db,"SELECT * FROM distribution_remote_commands WHERE session_id=:id AND state IN ('queued','delivered')",id=ident)
        if waiting:raise error('REMOTE_COMMAND_PENDING')
        if row['last_command_id']:
            last=await core.one(db,'SELECT frame_seq FROM distribution_remote_commands WHERE id=:id',id=row['last_command_id'])
            if last and req.frame_seq<=last['frame_seq']:raise error('REMOTE_FRAME_STALE')
        seq=row['command_seq']+1
        await db.execute(core.text("INSERT INTO distribution_remote_commands(id,session_id,command_seq,control_revision,frame_seq,kind,state,code,queued_at) VALUES(:id,:sid,:seq,:revision,:frame,:kind,'queued','INPUT_QUEUED',:at)"),{'id':req.command_id,'sid':ident,'seq':seq,'revision':req.control_revision,'frame':req.frame_seq,'kind':req.input.kind,'at':core.now_ms()})
        await db.execute(core.text("UPDATE distribution_remote_sessions SET command_seq=:seq,last_command_id=:cmd,last_command_state='queued' WHERE id=:id"),{'id':ident,'cmd':req.command_id,'seq':seq})
        self.payloads[str(req.command_id)]={'session_id':str(ident),'command_id':str(req.command_id),'command_seq':seq,
            'control_revision':req.control_revision,'frame_seq':req.frame_seq,'input':req.input.model_dump(mode='json'),
            '_captured_at':basis[1]}
        self.payload_expiry[str(req.command_id)]=basis[1]+FRAME_FRESH_MS
        await core.audit(db,actor,'remote_input_queued',{**{k:row[k] for k in ('module','tenant_id','scope_id')},
            'session_id':str(ident),'binding_id':str(row['binding_id']),'kind':req.input.kind},'INPUT_QUEUED')
        return {'schema':1,'command_id':str(req.command_id),'command_seq':seq,'state':'queued'}

    async def close(self,db,actor,ident,req):
        row=await self.checked(db,ident,actor,allow_closed=True);self.nonce(row,req.control_nonce)
        if row['state'] in ACTIVE:await self.close_row(db,row,'CONTROLLER_CLOSED')
        return {'schema':1,'session':self.view(row)}

    async def poll(self,db,device):
        await self.ready();items=await core.rows(db,"SELECT id FROM distribution_remote_sessions WHERE device_id=:device AND state IN ('requested','active') ORDER BY created_at LIMIT 10",device=device)
        sessions=[];commands=[]
        for item in items:
            try:row=await self.checked(db,item['id'],device=device)
            except HTTPException as exc:
                if exc.status_code>=500:raise
                continue
            self.prune_reads(str(row['id']),core.now_ms())
            sessions.append(self.view(row))
            queued=await core.one(db,"SELECT * FROM distribution_remote_commands WHERE session_id=:id AND state='queued' ORDER BY command_seq LIMIT 1",id=row['id'])
            if queued:
                payload=self.payloads.pop(str(queued['id']),None)
                self.payload_expiry.pop(str(queued['id']),None)
                usable=payload and queued['control_revision']==row['control_revision'] and core.now_ms()-payload['_captured_at']<=FRAME_FRESH_MS
                state='delivered' if usable else 'unknown';code='INPUT_DELIVERED' if usable else 'INPUT_NOT_DELIVERED'
                await db.execute(core.text('UPDATE distribution_remote_commands SET state=:state,code=:code,delivered_at=:at WHERE id=:id'),{'id':queued['id'],'state':state,'code':code,'at':core.now_ms()})
                await db.execute(core.text('UPDATE distribution_remote_sessions SET last_command_state=:state WHERE id=:id'),{'id':row['id'],'state':state})
                if usable:
                    payload.pop('_captured_at');commands.append(payload)
        return {'schema':1,'broker_epoch':self.epoch,'as_of':core.now_ms(),'sessions':sessions,'commands':commands}

    async def frame(self,db,device,req,raw):
        row=await self.checked(db,req.session_id,device=device)
        if req.control_revision!=row['control_revision'] or req.frame_seq<=row['last_frame_seq']:raise error('REMOTE_FRAME_STALE')
        if not core.now_ms()-10000<=req.captured_at<=core.now_ms()+1000:raise error('REMOTE_FRAME_STALE')
        dims=png_dimensions(raw)
        if dims!=(req.viewport_width,req.viewport_height):raise error('REMOTE_VIEWPORT_MISMATCH',422)
        changed=row['last_frame_seq'] and dims!=(row['viewport_width'],row['viewport_height'])
        revision=row['control_revision']+int(bool(changed))
        if changed:
            self.read_frames.pop(str(row['id']),None)
            queued=await core.rows(db,"SELECT id FROM distribution_remote_commands WHERE session_id=:id AND state IN ('queued','delivered')",id=row['id'])
            for item in queued:self.payloads.pop(str(item['id']),None);self.payload_expiry.pop(str(item['id']),None)
            await db.execute(core.text("UPDATE distribution_remote_commands SET state=CASE WHEN state='delivered' THEN 'unknown' ELSE 'canceled' END,code='VIEWPORT_CHANGED' WHERE session_id=:id AND state IN ('queued','delivered')"),{'id':row['id']})
            await db.execute(core.text('UPDATE distribution_remote_sessions SET last_command_state=(SELECT state FROM distribution_remote_commands WHERE id=last_command_id) WHERE id=:id'),{'id':row['id']})
        at=core.now_ms()
        await db.execute(core.text("UPDATE distribution_remote_sessions SET state='active',code='FRAME_READY',control_revision=:revision,last_frame_seq=:seq,viewport_width=:width,viewport_height=:height,captured_at=:captured,uploaded_at=:at WHERE id=:id"),{'id':row['id'],'revision':revision,'seq':req.frame_seq,'width':dims[0],'height':dims[1],'captured':req.captured_at,'at':at})
        self.frames[str(row['id'])]=(req.frame_seq,revision,raw)
        self.frame_expiry[str(row['id'])]=req.captured_at+FRAME_FRESH_MS
        return {'schema':1,'frame_seq':req.frame_seq,'control_revision':revision}

    async def frame_read(self,db,actor,ident):
        row=await self.checked(db,ident,actor);value=self.frames.get(str(ident))
        if not value or value[:2]!=(row['last_frame_seq'],row['control_revision']) or core.now_ms()-row['captured_at']>FRAME_FRESH_MS:raise error('REMOTE_FRAME_STALE')
        return row,value[2]

    async def ack(self,db,device,req):
        row=await self.checked(db,req.session_id,device=device)
        cmd=await core.one(db,'SELECT * FROM distribution_remote_commands WHERE id=:id AND session_id=:sid FOR UPDATE',id=req.command_id,sid=req.session_id)
        if not cmd or cmd['command_seq']!=req.command_seq or cmd['control_revision']!=req.control_revision or req.control_revision!=row['control_revision']:raise error('REMOTE_ACK_MISMATCH')
        if cmd['state'] in ('applied','rejected','unknown'):
            if cmd['state']!=req.state or cmd['code']!=req.code:raise error('REMOTE_ACK_MISMATCH')
        elif cmd['state']=='delivered':
            await db.execute(core.text('UPDATE distribution_remote_commands SET state=:state,code=:code,acked_at=:at WHERE id=:id'),{'id':req.command_id,'state':req.state,'code':req.code,'at':core.now_ms()})
            await db.execute(core.text('UPDATE distribution_remote_sessions SET last_command_state=:state WHERE id=:id'),{'id':row['id'],'state':req.state})
            await core.audit(db,'device:'+device,'remote_input_ack',{**{k:row[k] for k in ('module','tenant_id','scope_id')},
                'session_id':str(row['id']),'command_id':str(req.command_id)},req.code)
        else:raise error('REMOTE_ACK_MISMATCH')
        return {'schema':1,'command_id':str(req.command_id),'state':req.state,'code':req.code}


broker=Broker()
