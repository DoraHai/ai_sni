"""Version-bound native media. Local DB bytes only; no paths or network."""
from datetime import datetime, timezone
import asyncio
import hashlib
import io
import json
import warnings
from uuid import UUID, uuid4

from PIL import Image, ImageFile, ImageOps, UnidentifiedImageError
from bs4 import BeautifulSoup
from sqlalchemy import text

from app.seo_distribution_sources import authorize_scope, denied, positive, PLATFORMS

MAX_IMAGE = 20_000_000
MAX_TOTAL = 40_000_000
MAX_IMAGES = 9
MAX_PIXELS = 25_000_000
VARIANT_FIELDS = ('id','tenant_id','content_asset_id','connection_id','platform_code','source_version',
    'revision_number','status','title','content','reviewed_by','reviewed_at','updated_at')


def central_platform(row):
    return 'wechat-article' if row['platform_code'] in PLATFORMS['wechat-article'] else 'xiaohongshu-image'


def image_limit(row):
    return 1 if row['platform_code'] in PLATFORMS['wechat-article'] else MAX_IMAGES


def hash_value(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,default=str).encode()).hexdigest()


def variant_seal(row):
    return hash_value({key:row[key] for key in VARIANT_FIELDS})


def draft_hash(row):
    return hash_value({key:row[key] for key in VARIANT_FIELDS if key not in
        {'status','reviewed_by','reviewed_at','updated_at'}})


def require_strict_decoder():
    if ImageFile.LOAD_TRUNCATED_IMAGES:
        raise denied('source_unavailable','图片解码环境未处于严格模式，请联系管理员核对',503)


def validate_image(data,media_type):
    """Verify structure AND pixels without changing process-global Pillow flags."""
    require_strict_decoder()
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error',Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as image:
                if (image.format!=('PNG' if media_type=='image/png' else 'JPEG') or
                        getattr(image,'n_frames',1)!=1 or image.width*image.height>MAX_PIXELS):
                    raise ValueError()
                image.verify()
            require_strict_decoder()
            with Image.open(io.BytesIO(data)) as image: image.load()
            require_strict_decoder()
    except (ValueError,OSError,SyntaxError,Image.DecompressionBombError,Image.DecompressionBombWarning):
        raise denied('assets_unavailable','图片无法严格完整解码，请重新上传审核') from None


def normalized_image(raw):
    """Fully decode then re-encode pixels, removing metadata/trailing payloads."""
    require_strict_decoder()
    if not isinstance(raw,bytes) or not 0 < len(raw) <= MAX_IMAGE:
        raise denied('asset_invalid','单张图片必须为 1 至 20000000 字节',422)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error',Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(raw)) as image:
                fmt = image.format
                if fmt not in {'PNG','JPEG'} or getattr(image,'n_frames',1)!=1 or image.width*image.height>MAX_PIXELS:
                    raise ValueError()
                image.verify()
            require_strict_decoder()
            with Image.open(io.BytesIO(raw)) as image:
                image.load()
                require_strict_decoder()
                pixels = ImageOps.exif_transpose(image).convert('RGBA' if fmt=='PNG' and
                    ('A' in image.getbands() or 'transparency' in image.info) else 'RGB')
                output = io.BytesIO()
                # Fresh image strips EXIF, profiles and other caller metadata.
                clean = Image.new(pixels.mode,pixels.size)
                clean.paste(pixels)
                clean.save(output,format=fmt)
                data = output.getvalue()
                if len(data)>MAX_IMAGE: raise ValueError()
                require_strict_decoder()
                return data,'image/png' if fmt=='PNG' else 'image/jpeg'
    except (ValueError,OSError,SyntaxError,UnidentifiedImageError,Image.DecompressionBombError,Image.DecompressionBombWarning):
        raise denied('asset_invalid','图片须为可完整解码的单帧 PNG/JPEG，最多 2500 万像素及 20000000 字节',422) from None


async def variant_row(db,actor,tenant,scope,variant_id,*,lock=False):
    await authorize_scope(db,actor,tenant,scope)
    if not positive(variant_id): raise denied('invalid_scope','渠道稿编号无效',422)
    result = await db.execute(text('SELECT v.* FROM seo_distribution_variants v '
        'JOIN seo_content_assets c ON c.id=v.content_asset_id '
        'JOIN seo_distribution_connections a ON a.id=v.connection_id '
        'WHERE v.id=:variant AND v.tenant_id=:tenant AND c.tenant_id=:tenant AND c.site_id=:scope '
        "AND a.tenant_id=:tenant AND a.platform_code=v.platform_code "
        "AND v.platform_code IN ('xiaohongshu','wechat_official','wechat_browser') "
        "AND c.content_type='article' AND a.enabled "
        "AND (a.mode<>'api' OR a.status='connected') "
        'AND v.source_version=c.version_count AND v.id=(SELECT n.id FROM seo_distribution_variants n '
        'WHERE n.tenant_id=v.tenant_id AND n.content_asset_id=v.content_asset_id AND n.connection_id=v.connection_id '
        'ORDER BY n.revision_number DESC,n.id DESC LIMIT 1)' + (' FOR UPDATE OF v' if lock else '')),
        {'variant':variant_id,'tenant':tenant,'scope':scope})
    row = result.mappings().one_or_none()
    if row is None: raise denied('source_not_found','当前网站最新的图文或公众号文章稿不可用',404)
    return row


async def latest_set(db,variant_id):
    return (await db.execute(text('SELECT * FROM seo_distribution_media_sets WHERE variant_id=:id '
        'ORDER BY created_at DESC,id DESC LIMIT 1'),{'id':variant_id})).mappings().one_or_none()


async def preview(db,actor,tenant,scope,variant_id):
    with db.no_autoflush:
        row = await variant_row(db,actor,tenant,scope,variant_id)
        bundle = await latest_set(db,variant_id)
        return {'variant_id':variant_id,'edit_token':variant_seal(row),'title':row['title'],'body':row['content'],
            'body_text':BeautifulSoup(row['content'],'html.parser').get_text('\n',strip=True),
            'status':row['status'],'set_id':str(bundle['id']) if bundle else None,
            'assets':bundle['manifest'] if bundle else [], 'platform':central_platform(row),
            'max_images':image_limit(row), 'asset_role':'cover' if image_limit(row)==1 else 'image-text'}


async def list_drafts(db,actor,tenant,scope):
    """Authorized editing picker; separate from approved distribution list."""
    await authorize_scope(db,actor,tenant,scope)
    with db.no_autoflush:
        rows=(await db.execute(text('SELECT v.id AS variant_id,v.title,v.status FROM seo_distribution_variants v '
            'JOIN seo_content_assets c ON c.id=v.content_asset_id JOIN seo_distribution_connections a ON a.id=v.connection_id '
            'WHERE v.tenant_id=:tenant AND c.tenant_id=:tenant AND c.site_id=:scope AND a.tenant_id=:tenant '
            "AND v.platform_code IN ('xiaohongshu','wechat_official','wechat_browser') "
            "AND a.platform_code=v.platform_code AND c.content_type='article' AND a.enabled "
            "AND (a.mode<>'api' OR a.status='connected') AND v.source_version=c.version_count "
            'AND v.id=(SELECT n.id FROM seo_distribution_variants n WHERE n.tenant_id=v.tenant_id '
            'AND n.content_asset_id=v.content_asset_id AND n.connection_id=v.connection_id '
            'ORDER BY n.revision_number DESC,n.id DESC LIMIT 1) ORDER BY v.updated_at DESC,v.id DESC LIMIT 50'),
            {'tenant':tenant,'scope':scope})).mappings().all()
    await authorize_scope(db,actor,tenant,scope)
    return [dict(row) for row in rows]


async def replace_assets(db,actor,tenant,scope,variant_id,expected_token,images):
    # Caller owns atomic commit/rollback; all mutations use SQL (no autoflush).
    with db.no_autoflush:
        row = await variant_row(db,actor,tenant,scope,variant_id,lock=True)
        if variant_seal(row)!=expected_token: raise denied('source_stale','稿件已变化，请重新预览')
        if not isinstance(images,list) or not 1<=len(images)<=image_limit(row) or sum(map(len,images))>MAX_TOTAL:
            raise denied('asset_invalid','公众号须上传 1 张封面，小红书为 1 至 9 张图片，合计不超过 40000000 字节',422)
        decoded = [await asyncio.to_thread(normalized_image,raw) for raw in images]
        if sum(len(data) for data,_ in decoded)>MAX_TOTAL:
            raise denied('asset_invalid','规范化后图片合计超过 40000000 字节',422)
        manifest = [{'id':str(uuid4()),'sha256':hashlib.sha256(data).hexdigest(),'mediaType':media,
            'bytes':len(data)} for data,media in decoded]
        bundle_id = uuid4()
        row = (await db.execute(text("UPDATE seo_distribution_variants SET status='draft',reviewed_by=NULL,"
            'reviewed_at=NULL,updated_at=:at,revision_number=revision_number+1 WHERE id=:id RETURNING *'),
            {'id':variant_id,'at':datetime.now(timezone.utc).replace(tzinfo=None)})).mappings().one()
        await db.execute(text('INSERT INTO seo_distribution_media_sets '
            '(id,tenant_id,site_id,variant_id,draft_hash,manifest,uploaded_by) '
            'VALUES(:id,:tenant,:site,:variant,:hash,CAST(:manifest AS jsonb),:actor)'),
            {'id':bundle_id,'tenant':tenant,'site':scope,'variant':variant_id,'hash':draft_hash(row),
                'manifest':json.dumps(manifest),'actor':actor})
        for position,((data,media),item) in enumerate(zip(decoded,manifest)):
            await db.execute(text('INSERT INTO seo_distribution_media_bytes '
                '(id,set_id,position,sha256,media_type,byte_count,data) VALUES(:id,:set,:pos,:sha,:media,:size,:data)'),
                {'id':UUID(item['id']),'set':bundle_id,'pos':position,'sha':item['sha256'],
                    'media':media,'size':len(data),'data':data})
        await authorize_scope(db,actor,tenant,scope)
        return await preview(db,actor,tenant,scope,variant_id)


def checked_manifest(bundle,records,limit=MAX_IMAGES):
    manifest = [{'id':str(row['id']),'sha256':row['sha256'],'mediaType':row['media_type'],
        'bytes':row['byte_count']} for row in records]
    if (not 1<=len(manifest)<=limit or manifest!=bundle['manifest']
            or sum(item['bytes'] for item in manifest)>MAX_TOTAL):
        raise denied('assets_unavailable','图片清单不完整或不匹配，请重新上传审核')
    return manifest


async def records_for(db,set_id):
    return (await db.execute(text('SELECT * FROM seo_distribution_media_bytes WHERE set_id=:id ORDER BY position'),
        {'id':set_id})).mappings().all()


def checked_bytes(record):
    require_strict_decoder()
    data = bytes(record['data'])
    if len(data)!=record['byte_count'] or hashlib.sha256(data).hexdigest()!=record['sha256']:
        raise denied('assets_unavailable','图片字节校验失败，请重新上传审核')
    validate_image(data,record['media_type'])
    return data


async def review_assets(db,actor,tenant,scope,variant_id,expected_token,set_id):
    with db.no_autoflush:
        row = await variant_row(db,actor,tenant,scope,variant_id,lock=True)
        bundle = await latest_set(db,variant_id)
        if (variant_seal(row)!=expected_token or not bundle or str(bundle['id'])!=str(set_id)
                or bundle['draft_hash']!=draft_hash(row)):
            raise denied('source_stale','正文或素材已变化，请重新核对')
        if actor in {bundle['uploaded_by'],row['created_by']}:
            raise denied('independent_review_required','请由其他有权限的顾问审核正文及图片',403)
        records = await records_for(db,bundle['id'])
        checked_manifest(bundle,records,image_limit(row))
        for record in records: await asyncio.to_thread(checked_bytes,record)
        prior = await db.scalar(text('SELECT 1 FROM seo_distribution_media_reviews WHERE set_id=:id'),{'id':bundle['id']})
        if prior: raise denied('source_stale','该素材集已冻结，需要重新上传后再审')
        row = (await db.execute(text("UPDATE seo_distribution_variants SET status='approved',reviewed_by=:actor,"
            'reviewed_at=:at,updated_at=:at WHERE id=:id RETURNING *'),
            {'id':variant_id,'actor':actor,'at':datetime.now(timezone.utc).replace(tzinfo=None)})).mappings().one()
        await db.execute(text('INSERT INTO seo_distribution_media_reviews(set_id,reviewed_by,variant_seal) '
            'VALUES(:id,:actor,:seal)'),{'id':bundle['id'],'actor':actor,'seal':variant_seal(row)})
        # Reuse every mother/confirmation/keyword/content gate; failure rolls back.
        from app.seo_distribution_sources import load_source
        return await load_source(db,actor,tenant,scope,variant_id,central_platform(row))


async def preview_asset(db,actor,tenant,scope,variant_id,asset_id):
    with db.no_autoflush:
        await variant_row(db,actor,tenant,scope,variant_id)
        bundle = await latest_set(db,variant_id)
        if not bundle: raise denied('assets_unavailable','尚未上传图片')
        for record in await records_for(db,bundle['id']):
            if str(record['id'])==asset_id:
                await authorize_scope(db,actor,tenant,scope)
                return await asyncio.to_thread(checked_bytes,record),record['media_type']
        raise denied('asset_not_found','当前稿件不存在该图片',404)
