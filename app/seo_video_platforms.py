"""Official user-authorized video APIs. No password login or automatic resubmission."""
import logging
import time
from urllib.parse import urlencode, urlparse
import httpx
from app.seo_crawler import pin_public_target, pinned_async_client

PLATFORMS={
    'douyin_video':{'origin':'https://open.douyin.com','scopes':'video.create,video.data','app_key':'client_key','secret_key':'client_secret'},
    'kuaishou_video':{'origin':'https://open.kuaishou.com','scopes':'user_video_publish,user_video_info','app_key':'app_id','secret_key':'app_secret'},
}
REDIRECT='https://gsnipers.snipers.com.cn/seo/distribution'

class VideoError(ValueError):pass

class RedactVideoRequest(logging.Filter):
    def filter(self,record):
        # httpx logs full request URLs at INFO. Never log OAuth query credentials.
        if record.name=='httpx' and any(origin in record.getMessage() for origin in ('open.kuaishou.com','open.douyin.com','upload_token=')):
            record.msg='SEO official video HTTP request (URL redacted)';record.args=()
        return True

logging.getLogger('httpx').addFilter(RedactVideoRequest())

def authorization_url(platform,credentials,state):
    spec=PLATFORMS[platform]
    params={spec['app_key']:credentials[spec['app_key']],'scope':spec['scopes'],'response_type':'code','redirect_uri':REDIRECT,'state':state}
    if platform=='kuaishou_video':params['ua']='pc'
    return spec['origin']+('/platform/oauth/connect/' if platform=='douyin_video' else '/oauth2/authorize')+'?'+urlencode(params)

def checked(platform,payload):
    if not isinstance(payload,dict):raise VideoError('平台响应格式异常，请核实平台记录')
    value=payload.get('data') if platform=='douyin_video' else payload
    if not isinstance(value,dict) or str(value.get('error_code') if platform=='douyin_video' else value.get('result'))!=('0' if platform=='douyin_video' else '1'):
        raise VideoError('平台拒绝请求，请检查应用权限、授权范围和素材要求')
    return value

async def request(platform,method,path,**kwargs):
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(60,connect=10),follow_redirects=False,trust_env=False) as client:
            response=await client.request(method,PLATFORMS[platform]['origin']+path,**kwargs)
            response.raise_for_status()
            return checked(platform,response.json())
    except VideoError:raise
    except Exception:raise VideoError('平台请求未确认完成；请核实平台记录，系统不会自动重复提交') from None

async def token(platform,credentials,*,code=None,refresh=False):
    spec=PLATFORMS[platform]
    params={spec['app_key']:credentials[spec['app_key']],'grant_type':'refresh_token' if refresh else 'authorization_code'}
    if not refresh or platform=='kuaishou_video':params[spec['secret_key']]=credentials[spec['secret_key']]
    params['refresh_token' if refresh else 'code']=credentials['refresh_token'] if refresh else code
    prefix='/oauth/' if platform=='douyin_video' else '/oauth2/'
    path=prefix+('refresh_token' if refresh else 'access_token')+('/' if platform=='douyin_video' else '')
    data=await request(platform,'POST' if platform=='douyin_video' else 'GET',path,**({'data':params} if platform=='douyin_video' else {'params':params}))
    if not data.get('access_token') or (not refresh and not data.get('open_id')):raise VideoError('平台未返回完整用户授权')
    return {**credentials,**{key:str(data[key]) for key in ('access_token','refresh_token','open_id') if data.get(key)},
            'expires_at':str(int(time.time())+int(data.get('expires_in',0))),
            'scope':','.join(data.get('scopes') or []) if isinstance(data.get('scopes'),list) else str(data.get('scope') or credentials.get('scope') or '')}

def require_token(credentials):
    if not credentials.get('access_token') or float(credentials.get('expires_at',0))<=time.time()+30:
        raise VideoError('用户授权缺失或即将过期，请先刷新授权或重新授权')

def upload_origin(endpoint):
    if not isinstance(endpoint,str) or not endpoint or '/' in endpoint or '@' in endpoint or ':' in endpoint:
        raise VideoError('平台上传网关无效')
    return 'https://'+endpoint

async def upload(platform,credentials,data):
    require_token(credentials)
    if platform=='douyin_video':
        value=await request(platform,'POST','/video/upload/',params={'open_id':credentials['open_id']},headers={'access-token':credentials['access_token']},files={'video':('video.mp4',data,'video/mp4')})
        video_id=(value.get('video') or {}).get('video_id')
        if not video_id:raise VideoError('平台未返回视频素材 ID')
        return {'video_id':str(video_id)}
    value=await request(platform,'POST','/openapi/photo/start_upload',params={'app_id':credentials['app_id'],'access_token':credentials['access_token']})
    if not value.get('upload_token'):raise VideoError('平台未返回上传凭据')
    origin=upload_origin(value.get('endpoint'))
    try:
        async with pin_public_target(origin):
            async with pinned_async_client(timeout=90,follow_redirects=False) as client:
                response=await client.post(origin+'/api/upload/multipart',params={'upload_token':value['upload_token']},files={'file':('video.mp4',data,'video/mp4')})
                response.raise_for_status();checked(platform,response.json())
    except Exception:raise VideoError('上传网关未确认完成，请检查 HTTPS 支持、素材和网络；未自动重试') from None
    return {'upload_token':str(value['upload_token'])}

async def publish(platform,credentials,media,title,cover=None):
    require_token(credentials)
    if platform=='douyin_video':
        data=await request(platform,'POST','/video/create/',params={'open_id':credentials['open_id']},headers={'access-token':credentials['access_token']},json={'video_id':media['video_id'],'text':title})
        item=data.get('item_id')
    else:
        if not cover:raise VideoError('快手发布需要 JPG 或 PNG 封面')
        data=await request(platform,'POST','/openapi/photo/publish',params={'app_id':credentials['app_id'],'access_token':credentials['access_token'],'upload_token':media['upload_token']},data={'caption':title},files={'cover':cover})
        item=(data.get('video_info') or {}).get('photo_id')
    if not item:raise VideoError('平台未返回作品 ID，请到平台核实，不能直接重复发布')
    return str(item)

def observed(platform,data,item_id):
    if platform=='douyin_video':
        candidates=[row for row in data.get('list',[]) if str(row.get('item_id'))==item_id]
        value=candidates[0] if len(candidates)==1 else {}
        url=value.get('share_url'); parsed=urlparse(url or '')
        valid=parsed.scheme=='https' and parsed.hostname in {'www.douyin.com','douyin.com','v.douyin.com'} and not parsed.username and not parsed.password and not parsed.port and parsed.path not in {'','/'}
        done=value.get('is_reviewed') is True and int(value.get('create_time') or 0)>0 and valid
        return {'status':'published' if done else 'publishing','page_url':url if done else None,'reviewed':value.get('is_reviewed'),'title':value.get('title')}
    value=data.get('video_info') or {}
    done=str(value.get('photo_id'))==item_id and value.get('pending') is False
    # play_url is a media stream, not an article/backlink URL.
    return {'status':'published' if done else 'publishing','page_url':None,'pending':value.get('pending'),'title':value.get('caption') if str(value.get('photo_id'))==item_id else None}

async def sync(platform,credentials,item_id):
    require_token(credentials)
    if platform=='douyin_video':
        data=await request(platform,'POST','/video/data/',params={'open_id':credentials['open_id']},headers={'access-token':credentials['access_token']},json={'item_ids':[item_id]})
    else:
        data=await request(platform,'GET','/openapi/photo/info',params={'app_id':credentials['app_id'],'access_token':credentials['access_token'],'photo_id':item_id})
    try:return observed(platform,data,item_id)
    except (ValueError,TypeError,AttributeError):raise VideoError('作品状态数据不完整，请稍后核实') from None
