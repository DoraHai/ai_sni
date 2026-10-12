"""Real loopback TLS + separate Node executor + PostgreSQL; synthetic source."""
import asyncio
from datetime import datetime, timedelta, timezone
import ipaddress
import json
import os
from pathlib import Path
import shutil
import socket
import tempfile

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
import uvicorn

from test_distribution_control_postgres import fixture, prepare, SCOPE


def test_real_https_node_handoff_and_durable_ack(monkeypatch):
    async def run():
        runner=Path(os.environ.get('DISTRIBUTION_NODE_RUNNER',''))
        if not runner.is_file() or runner.name!='https-runner.mjs':
            raise RuntimeError('Build the independent Multihao HTTPS runner and set DISTRIBUTION_NODE_RUNNER')
        node=shutil.which('node')
        if not node: raise RuntimeError('Node 24+ required')
        async with fixture(monkeypatch) as f:
            device,request=await prepare(f,'handoff')
            assert (await f.call('POST','/tasks',json=request)).status_code==200
            with tempfile.TemporaryDirectory(prefix='snipers-distribution-tls-') as temp:
                root=Path(temp); key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
                name=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'distribution-loopback-test')])
                cert=(x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
                    .serial_number(x509.random_serial_number()).not_valid_before(datetime.now(timezone.utc)-timedelta(minutes=1))
                    .not_valid_after(datetime.now(timezone.utc)+timedelta(days=1))
                    .add_extension(x509.BasicConstraints(ca=True,path_length=None),critical=True)
                    .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address('127.0.0.1'))]),critical=False)
                    .sign(key,hashes.SHA256()))
                cert_path=root/'loopback.pem'; key_path=root/'loopback.key'
                cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
                key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))
                sock=socket.socket(); sock.bind(('127.0.0.1',0)); port=sock.getsockname()[1]
                server=uvicorn.Server(uvicorn.Config(f.app,host='127.0.0.1',port=port,ssl_keyfile=str(key_path),
                    ssl_certfile=str(cert_path),access_log=False,log_level='critical',lifespan='off'))
                running=asyncio.create_task(server.serve(sockets=[sock]))
                process=None
                try:
                    async with asyncio.timeout(10):
                        while not server.started:
                            if running.done(): raise RuntimeError('Synthetic TLS server failed to start')
                            await asyncio.sleep(.02)
                    env={**os.environ,'NODE_EXTRA_CA_CERTS':str(cert_path),'MHT_DISTRIBUTION_DEVICE_TOKEN':device['credential']}
                    process=await asyncio.create_subprocess_exec(node,str(runner),stdin=asyncio.subprocess.PIPE,
                        stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE,env=env)
                    payload=json.dumps({'origin':f'https://127.0.0.1:{port}','deviceId':device['id'],'cycles':3}).encode()
                    stdout,_stderr=await asyncio.wait_for(process.communicate(payload),30)
                    # Never include raw subprocess output in assertion failures.
                    assert process.returncode==0,'Independent TLS runner rejected the synthetic exchange'
                    stages=[json.loads(line) for line in stdout.splitlines()]
                    assert stages[-1]['phase']=='verified' and stages[-1]['acknowledgements']>=3
                    assert stages[-1]['stages']['awaiting-human']==1
                    state=(await f.call('GET','/tasks',params=SCOPE)).json()['items'][0]
                    assert state['status']=='awaiting-human' and state['receipt']['code']=='HUMAN_REQUIRED'
                    assert state['receipt']['publicUrl'] is None and state['receipt']['evidence']=='none'
                finally:
                    if process and process.returncode is None:
                        process.kill(); await process.wait()
                    server.should_exit=True
                    await asyncio.wait_for(running,10)
                    sock.close()
    asyncio.run(run())


def test_real_broker_large_image_handoff_decode_chunks_and_pause(monkeypatch):
    """Final standalone CLI talks to this router, not a mocked exchange server."""
    async def run():
        import base64, hashlib
        from io import BytesIO
        from types import MethodType
        from uuid import uuid4
        from copy import deepcopy
        from PIL import Image
        from app.distribution_contract import content_digest
        from test_distribution_control_postgres import core
        runner=Path(os.environ.get('DISTRIBUTION_NODE_RUNNER',''))
        cli=runner.parent/'cli.mjs'; workspace=runner.parents[2]
        if not cli.is_file() or not (workspace/'node_modules/electron/dist/electron.exe').is_file():
            raise RuntimeError('Build standalone Multihao and install its own Electron runtime')
        node=shutil.which('node')
        async with fixture(monkeypatch) as f:
            output=BytesIO(); Image.frombytes('RGB',(512,512),os.urandom(512*512*3)).save(output,format='PNG')
            image=output.getvalue(); assert 600000<len(image)<20000000
            f.sources.content['assets']=[{'id':'actual_large_image','sha256':hashlib.sha256(image).hexdigest(),
                'mediaType':'image/png','bytes':len(image)}]
            async def source(self,db,actor,tenant,scope,variant,platform):
                await self.authorize_scope(db,actor,tenant,scope)
                assert platform=='xiaohongshu-image' and variant==11
                return {**SCOPE,'variant_id':11,'source_revision':self.content['version'],'content':deepcopy(self.content)}
            async def asset(self,db,actor,tenant,scope,variant,platform,asset_id):
                await self.authorize_scope(db,actor,tenant,scope)
                assert asset_id=='actual_large_image'; return image
            f.sources.load_source=MethodType(source,f.sources); f.sources.load_asset=MethodType(asset,f.sources)
            device,req=await prepare(f,'handoff')
            binding=(await f.call('POST','/bindings',actor=8,json={**SCOPE,'device_id':device['id'],
                'account_id':'synthetic-xhs','external_account_id':'synthetic-xhs-public','platform':'xiaohongshu-image',
                'confirm_account_ownership':True})).json()['binding']
            req.update(binding_id=binding['id'],expected_digest=content_digest(f.sources.content))
            assert (await f.call('POST','/tasks',json=req)).status_code==200
            async with f.sessions() as db:
                row=await core.one(db,'SELECT id,grant_id FROM distribution_tasks')
                task_id,grant_id=str(row['id']),str(row['grant_id'])
            with tempfile.TemporaryDirectory(prefix='snipers-distribution-image-tls-') as temp:
                root=Path(temp); key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
                name=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'image-loopback-test')])
                cert=(x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
                    .serial_number(x509.random_serial_number()).not_valid_before(datetime.now(timezone.utc)-timedelta(minutes=1))
                    .not_valid_after(datetime.now(timezone.utc)+timedelta(days=1)).add_extension(x509.BasicConstraints(ca=True,path_length=None),critical=True)
                    .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address('127.0.0.1'))]),critical=False).sign(key,hashes.SHA256()))
                cert_path=root/'loopback.pem'; key_path=root/'loopback.key'
                cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
                key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))
                sock=socket.socket(); sock.bind(('127.0.0.1',0)); port=sock.getsockname()[1]
                server=uvicorn.Server(uvicorn.Config(f.app,host='127.0.0.1',port=port,ssl_keyfile=str(key_path),ssl_certfile=str(cert_path),
                    access_log=False,log_level='critical',lifespan='off'))
                running=asyncio.create_task(server.serve(sockets=[sock])); host=None
                env={**os.environ,'NODE_EXTRA_CA_CERTS':str(cert_path),'MHT_DISTRIBUTION_DEVICE_TOKEN':device['credential'],
                    'MHT_DISTRIBUTION_ROOT':str(root/'isolated-product'),'MHT_DISTRIBUTION_WORKSPACE':str(workspace)}
                async def command(action,payload=None):
                    process=await asyncio.create_subprocess_exec(node,str(cli),action,stdin=asyncio.subprocess.PIPE,
                        stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.DEVNULL,env=env,cwd=workspace)
                    stdout,_=await asyncio.wait_for(process.communicate(json.dumps(payload).encode() if payload else b''),25)
                    return process.returncode,json.loads(stdout)
                try:
                    async with asyncio.timeout(10):
                        while not server.started: await asyncio.sleep(.02)
                    code,_=await command('configure',{'origin':f'https://127.0.0.1:{port}','deviceId':device['id']}); assert code==0
                    host=await asyncio.create_subprocess_exec(node,str(cli),'run',stdout=asyncio.subprocess.DEVNULL,
                        stderr=asyncio.subprocess.DEVNULL,env=env,cwd=workspace)
                    async with asyncio.timeout(45):
                        while True:
                            item=(await f.call('GET','/tasks',params=SCOPE)).json()['items'][0]
                            if item['status']=='awaiting-human': break
                            assert item['status'] not in ('unknown','failed','canceled'),'Actual image preparation failed'
                            await asyncio.sleep(.1)
                    request={'grantId':grant_id,'taskId':task_id,'assetId':'actual_large_image'}
                    code,preview=await command('image',request); assert code==0,'Authorized actual image read failed'
                    assert base64.b64decode(preview['dataBase64'])==image and preview['sha256']==hashlib.sha256(image).hexdigest()
                    assert (await f.call('POST','/control',json={**SCOPE,'action':'pause','expected_revision':1,'request_id':str(uuid4())})).status_code==200
                    code,_=await command('image',request); assert code!=0,'Paused image read must be rejected'
                finally:
                    if host and host.returncode is None:
                        try: await command('shutdown'); await asyncio.wait_for(host.wait(),10)
                        except Exception: host.kill(); await host.wait()
                    server.should_exit=True; await asyncio.wait_for(running,10); sock.close()
    asyncio.run(run())
