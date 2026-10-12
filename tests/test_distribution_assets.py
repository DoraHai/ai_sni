"""Actual PNG/JPEG delivery rechecks current device, review and account controls."""
import asyncio
import hashlib
from io import BytesIO
from types import MethodType
from uuid import uuid4

from PIL import Image, ImageFile
from test_distribution_control_postgres import fixture, prepare, device_exchange, SCOPE, BASE, core
from app.distribution_contract import content_digest


def image_bytes(format):
    value=BytesIO(); Image.new('RGB',(3,2),(120,140,180)).save(value,format=format); return value.getvalue()


async def setup(f,format='PNG'):
    data=image_bytes(format); f.sources.data=data
    f.sources.content['assets']=[{'id':'reviewed_image_1','sha256':hashlib.sha256(data).hexdigest(),
        'mediaType':'image/png' if format=='PNG' else 'image/jpeg','bytes':len(data)}]
    async def load_asset(self,db,actor,tenant,scope,variant,platform,asset):
        await self.authorize_scope(db,actor,tenant,scope)
        assert asset=='reviewed_image_1'
        return self.data
    f.sources.load_asset=MethodType(load_asset,f.sources)
    d,req=await prepare(f,'publish'); req['expected_digest']=content_digest(f.sources.content)
    assert (await f.call('POST','/tasks',json=req)).status_code==200
    task=(await device_exchange(f,d)).json()['tasks'][0]
    async def download(device=d,asset='reviewed_image_1',extra=''):
        return await f.client.get(BASE+f"/device/tasks/{task['id']}/assets/{asset}"+extra,
            headers={'Authorization':'Bearer '+device['credential']})
    return d,req,task,download


def test_png_jpeg_actual_bytes_hash_auth_and_control_rechecks(monkeypatch):
    async def run():
        for format in ('PNG','JPEG'):
            async with fixture(monkeypatch) as f:
                d,req,task,get=await setup(f,format)
                response=await get(); assert response.status_code==200
                assert response.content==f.sources.data
                assert response.headers['etag']=='"'+hashlib.sha256(response.content).hexdigest()+'"'
                assert response.headers['cache-control']=='no-store' and response.headers['x-content-type-options']=='nosniff'
                assert (await get(asset='foreign_image')).status_code==403
                assert (await get(extra='?url=https://evil.invalid')).status_code==401
                other=(await f.call('POST','/devices',actor=8,json={'label':'另一设备'})).json()['device']
                assert (await get(device=other)).status_code==401
                pause={**SCOPE,'action':'pause','expected_revision':1,'request_id':str(uuid4())}
                assert (await f.call('POST','/control',json=pause)).status_code==200
                assert (await get()).status_code==403
                pause.update(action='resume',expected_revision=2,request_id=str(uuid4()))
                assert (await f.call('POST','/control',json=pause)).status_code==200
                account_pause={'binding_id':req['binding_id'],'expected_revision':1,'action':'pause','request_id':str(uuid4())}
                assert (await f.call('POST','/account-pause',actor=8,json=account_pause)).status_code==200
                assert (await get()).status_code==409
                account_pause.update(action='resume',expected_revision=2,request_id=str(uuid4()))
                assert (await f.call('POST','/account-pause',actor=8,json=account_pause)).status_code==200
                assert (await get()).status_code==200
                f.sources.content['title']='改稿后旧授权失效'
                assert (await get()).status_code==409
    asyncio.run(run())


def test_corrupt_undecodable_revoked_and_permissive_decoder_are_rejected(monkeypatch):
    async def run():
        async with fixture(monkeypatch) as f:
            d,req,task,get=await setup(f)
            original=f.sources.data; f.sources.data=b'bad'
            assert (await get()).status_code==409
            f.sources.data=original
            monkeypatch.setattr(ImageFile,'LOAD_TRUNCATED_IMAGES',True)
            assert (await get()).status_code==503
            monkeypatch.setattr(ImageFile,'LOAD_TRUNCATED_IMAGES',False)
            f.sources.revoked=True
            assert (await get()).status_code==403
        async with fixture(monkeypatch) as f:
            f.sources.data=b'not an image'
            # Hash and length can match while actual decoding must still fail.
            f.sources.content['assets']=[{'id':'reviewed_image_1','sha256':hashlib.sha256(f.sources.data).hexdigest(),
                'mediaType':'image/png','bytes':len(f.sources.data)}]
            async def load(self,*args): return self.data
            f.sources.load_asset=MethodType(load,f.sources)
            d,req=await prepare(f,'handoff')
            assert (await f.call('POST','/tasks',json=req)).status_code==200
            task=(await device_exchange(f,d)).json()['tasks'][0]
            response=await f.client.get(BASE+f"/device/tasks/{task['id']}/assets/reviewed_image_1",headers={'Authorization':'Bearer '+d['credential']})
            assert response.status_code==409
    asyncio.run(run())
