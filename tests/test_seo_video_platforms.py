import asyncio
import hashlib
import io
import logging
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from urllib.parse import parse_qs,urlparse
from uuid import uuid4
import pytest
from fastapi import HTTPException,UploadFile
from sqlalchemy import MetaData,select
from app import seo_video_platforms as video
from app.api import seo_video as api
from app.models.seo import SeoDistributionConnection,SeoContentPublication,SeoPublishAttempt,SeoContentAsset
from app.models.module_workspace import SeoSite
from app.seo_distribution import encrypt_credentials,decrypt_credentials
from app.security.auth import AuthContext
from test_seo_cockpit import run_database

def credentials(platform='douyin_video'):
    return {'client_key':'app','client_secret':'secret','app_id':'app','app_secret':'secret','access_token':'access','refresh_token':'refresh','open_id':'user','expires_at':str(time.time()+3600)}

@pytest.mark.parametrize('platform',list(video.PLATFORMS))
def test_oauth_url_uses_fixed_origin_and_no_secret(platform):
    url=video.authorization_url(platform,credentials(),'nonce')
    parsed=urlparse(url);params=parse_qs(parsed.query)
    assert parsed.scheme=='https' and parsed.hostname in {'open.douyin.com','open.kuaishou.com'}
    assert params['state']==['nonce'] and params['redirect_uri']==[video.REDIRECT]
    assert 'secret' not in url and 'access_token' not in url

@pytest.mark.parametrize('platform,method,path', [('douyin_video','POST','/oauth/access_token/'),('kuaishou_video','GET','/oauth2/access_token')])
def test_token_exchange_uses_documented_envelopes(platform,method,path):
    async def run():
        with patch.object(video,'request',new=AsyncMock(return_value={'access_token':'new','refresh_token':'rotated','open_id':'user','expires_in':3600,'scopes':['user_video_publish']})) as request:
            result=await video.token(platform,credentials(),code='code')
            assert result['refresh_token']=='rotated' and result['access_token']=='new'
            args,kwargs=request.call_args
            assert args==(platform,method,path)
            assert kwargs['data' if method=='POST' else 'params']['grant_type']=='authorization_code'
    asyncio.run(run())

@pytest.mark.parametrize('value',[{},[],{'data':{}},{'data':{'error_code':1}},{'data':{'error_code':0},'result':0}])
def test_kuaishou_never_accepts_wrong_success_envelope(value):
    with pytest.raises(video.VideoError):video.checked('kuaishou_video',value)

@pytest.mark.parametrize('value',['http://evil.test','127.0.0.1:8000','foo@evil.test','evil.test/path',''])
def test_upload_gateway_rejects_url_injection(value):
    with pytest.raises(video.VideoError):video.upload_origin(value)

def test_status_requires_matching_reviewed_work_and_never_uses_stream_as_link():
    assert video.observed('douyin_video',{'list':[]},'id')['status']=='publishing'
    item={'item_id':'id','is_reviewed':True,'create_time':1,'share_url':'https://www.douyin.com/video/1'}
    assert video.observed('douyin_video',{'list':[item]},'id')['status']=='published'
    for change in [{'item_id':'other'},{'is_reviewed':False},{'share_url':'https://evil.test/video/1'}]:
        assert video.observed('douyin_video',{'list':[{**item,**change}]},'id')['status']=='publishing'
    assert video.observed('kuaishou_video',{'video_info':{'photo_id':'id','pending':False,'play_url':'https://cdn.test/video.mp4'}},'id')=={'status':'published','page_url':None,'pending':False,'title':None}

def test_authorization_state_binds_actor_site_expiry_and_nonce():
    req=SimpleNamespace(state='nonce',site_id=10);ctx=SimpleNamespace(user_id=7)
    pending={'digest':hashlib.sha256(b'nonce').hexdigest(),'actor':7,'site_id':10,'expires':time.time()+60}
    assert api.valid_state(pending,req,ctx)
    for field,value in [('actor',8),('site_id',20),('expires',0),('digest','invalid')]:assert not api.valid_state({**pending,field:value},req,ctx)

def test_token_query_logging_is_redacted():
    record=logging.LogRecord('httpx',20,'',0,'HTTP Request: %s %s',('GET','https://open.kuaishou.com/oauth2/access_token?app_secret=secret'),None)
    assert video.RedactVideoRequest().filter(record)
    assert 'secret' not in record.getMessage()

@pytest.mark.parametrize('data,image',[ (b'fake',False),(b'not png',True),(b'',False)])
def test_invalid_upload_bytes_are_rejected(data,image):
    with pytest.raises(HTTPException):asyncio.run(api.file_bytes(UploadFile(file=io.BytesIO(data)),100,image))

def test_video_durable_claim_idempotency_uncertainty_and_tenant_isolation():
    async def scenario(sessions):
        ctx=AuthContext(7,'test','operator',1,{'seo.content':'edit'})
        async with sessions() as db:
            for model in [SeoDistributionConnection,SeoContentPublication,SeoPublishAttempt]:
                table=model.__table__.to_metadata(MetaData())
                for fk in list(table.foreign_key_constraints):table.constraints.remove(fk)
                await db.run_sync(lambda sync:table.create(sync.connection()))
            db.add(SeoSite(id=1,tenant_id=1,tenant_module_id=1,name='brand',domain='brand.example',canonical_domain='brand.example',status='active'))
            db.add(SeoContentAsset(id=1,tenant_id=1,site_id=1,title='video',status='ready',version_count=1))
            db.add(SeoDistributionConnection(id=1,tenant_id=1,name='video account',platform_code='douyin_video',mode='api',enabled=True,has_credentials=True,credentials_encrypted=encrypt_credentials(credentials())))
            await db.commit()
            request=uuid4()
            async def uploaded(*args):
                async with sessions() as other:
                    pub=await other.scalar(select(SeoContentPublication))
                    assert pub.status=='uploading'
                return {'video_id':'media'}
            with patch.object(video,'upload',new=AsyncMock(side_effect=uploaded)) as remote:
                kwargs=dict(tenant_id=1,site_id=1,connection_id=1,content_id=1,source_version=1,request_id=request,title='approved title',ctx=ctx,session=db)
                first=await api.upload(file=UploadFile(file=io.BytesIO(b'0000ftypmp42')),**kwargs)
                second=await api.upload(file=UploadFile(file=io.BytesIO(b'0000ftypmp42')),**kwargs)
                assert first['id']==second['id'] and first['status']=='draft' and remote.await_count==1
            pub_id=first['id']
            attempt=await db.scalar(select(SeoPublishAttempt))
            assert attempt.response_summary['sealed_video_media']!='media'
            assert decrypt_credentials(attempt.response_summary['sealed_video_media'])=={'video_id':'media'}
            async def uncertain(*args):
                async with sessions() as other:assert (await other.get(SeoContentPublication,pub_id)).status=='publishing'
                raise TimeoutError('sensitive provider details')
            with patch.object(video,'publish',new=AsyncMock(side_effect=uncertain)) as remote:
                result=await api.publish(pub_id,1,1,1,True,None,ctx,db)
                assert result['status']=='manual_required' and 'sensitive' not in result['last_error']
                with pytest.raises(HTTPException):await api.publish(pub_id,1,1,1,True,None,ctx,db)
                assert remote.await_count==1
            with pytest.raises(HTTPException):await api.publication(api.Scope(tenant_id=2,site_id=1,connection_id=1),pub_id,ctx,db)
            await db.rollback()
            req=api.Scope(tenant_id=1,site_id=1,connection_id=1)
            with patch.object(video,'sync',new=AsyncMock(return_value={'status':'published','page_url':None,'title':'wrong title'})):
                with pytest.raises(HTTPException):await api.recover(pub_id,api.Recovery(**req.model_dump(),item_id='work'),ctx,db)
            with patch.object(video,'sync',new=AsyncMock(return_value={'status':'published','page_url':None,'title':'approved title'})):
                assert (await api.recover(pub_id,api.Recovery(**req.model_dump(),item_id='work'),ctx,db))['external_id']=='work'
                assert (await api.sync(pub_id,req,ctx,db))['status']=='published'
                content=await db.get(SeoContentAsset,1)
                assert content.status=='published' and content.published_at
            state=(await api.authorize(req,ctx,db))['state']
            complete=api.Authorization(**req.model_dump(),state=state,code='valid')
            with patch.object(video,'token',new=AsyncMock(return_value=credentials())) as exchange:
                assert (await api.complete(complete,ctx,db))['authorized']
                with pytest.raises(HTTPException):await api.complete(complete,ctx,db)
                assert exchange.await_count==1
    run_database(scenario)
