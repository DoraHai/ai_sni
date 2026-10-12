"""Native image upload -> independent review -> immutable source/bytes."""
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime
import hashlib
import io
import os
from pathlib import Path
from uuid import uuid4

from PIL import Image, ImageFile
import httpx
import pytest
from fastapi import FastAPI, HTTPException
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app import seo_distribution_media as media, seo_distribution_sources as source
from app.api.seo_distribution_media import router
from app.database import get_session
from app.models.seo import SeoDistributionVariant, SeoDistributionConnection, SeoSiteAdvisorAssignment, SeoContentConfirmation
from app.models.user import User
from app.security.auth import issue_token
from test_seo_distribution_sources_postgres import fixture

pytestmark=pytest.mark.skipif(not os.getenv('SEO_WORKFLOW_TEST_DATABASE_URL'),reason='isolated local PostgreSQL required')


def picture(fmt='PNG',color='red'):
    output=io.BytesIO()
    Image.new('RGB',(12,8),color).save(output,format=fmt)
    return output.getvalue()


@asynccontextmanager
async def images_fixture():
    async with fixture() as sessions:
        async with sessions.begin() as db:
            connection=await db.connection()
            raw=await connection.get_raw_connection()
            await raw.driver_connection.execute((Path(__file__).parents[1]/'scripts/seo_distribution_media_schema.sql').read_text())
            row=await db.get(SeoDistributionVariant,60)
            row.platform_code='xiaohongshu'; row.created_by=7
            (await db.get(SeoDistributionConnection,50)).platform_code='xiaohongshu'
            db.add(User(id=8,username='media-reviewer',password_hash='unused',role_id=5,is_active=True))
            db.add(SeoSiteAdvisorAssignment(id=4,tenant_id=4,site_id=2,advisor_user_id=8,active=True))
        yield sessions


async def upload(db,images=None):
    preview=await media.preview(db,7,4,2,60)
    return await media.replace_assets(db,7,4,2,60,preview['edit_token'],images or [picture(),picture('JPEG','blue')])


async def freeze(sessions):
    async with sessions.begin() as db: draft=await upload(db)
    async with sessions.begin() as db:
        snapshot=await media.review_assets(db,8,4,2,60,draft['edit_token'],draft['set_id'])
    return snapshot


def test_native_upload_review_load_bytes_and_manifest_order(monkeypatch):
    async def forbidden(*args,**kwargs): pytest.fail('No external transport allowed')
    monkeypatch.setattr(httpx.AsyncHTTPTransport,'handle_async_request',forbidden)
    async def scenario():
        async with images_fixture() as sessions:
            async with sessions.begin() as db:
                draft=await upload(db)
                assert draft['status']=='draft' and len(draft['assets'])==2
                row=(await db.execute(text('SELECT reviewed_by,reviewed_at FROM seo_distribution_variants WHERE id=60'))).one()
                assert row==(None,None)
            async with sessions() as db:
                with pytest.raises(HTTPException): await source.load_source(db,7,4,2,60,'xiaohongshu-image')
                with pytest.raises(HTTPException) as exc:
                    await media.review_assets(db,7,4,2,60,draft['edit_token'],draft['set_id'])
                assert exc.value.status_code==403
            async with sessions.begin() as db:
                snapshot=await media.review_assets(db,8,4,2,60,draft['edit_token'],draft['set_id'])
            async with sessions() as db:
                await db.execute(text('SET TRANSACTION READ ONLY'))
                assert snapshot==await source.load_source(db,7,4,2,60,'xiaohongshu-image')
                assert snapshot['content']['assets']==draft['assets']
                assert [a['mediaType'] for a in draft['assets']]==['image/png','image/jpeg']
                assert len(await source.list_sources(db,7,4,2,'xiaohongshu-image'))==1
                for item in snapshot['content']['assets']:
                    data=await source.load_asset(db,7,4,2,60,'xiaohongshu-image',item['id'])
                    assert len(data)==item['bytes'] and hashlib.sha256(data).hexdigest()==item['sha256']
                    with Image.open(io.BytesIO(data)) as image: image.load()
                for bad in [str(uuid4()),'../../etc/passwd','https://example.com/a.png']:
                    with pytest.raises(HTTPException) as exc: await source.load_asset(db,7,4,2,60,'xiaohongshu-image',bad)
                    assert exc.value.status_code==404
    asyncio.run(scenario())


@pytest.mark.parametrize('change',['body','review','assignment','confirmation','replacement','new_draft'])
def test_media_changes_reject_old_snapshots_and_asset_ids(change):
    async def scenario():
        async with images_fixture() as sessions:
            old=await freeze(sessions)
            async with sessions.begin() as db:
                if change=='body': (await db.get(SeoDistributionVariant,60)).content='<p>selection changed</p>'
                elif change=='review': (await db.get(SeoDistributionVariant,60)).status='draft'
                elif change=='assignment': (await db.get(SeoSiteAdvisorAssignment,3)).active=False
                elif change=='confirmation': (await db.get(SeoContentConfirmation,70)).decision='reject'
                elif change=='replacement': await upload(db,[picture('PNG','green')])
                else: db.add(SeoDistributionVariant(id=61,tenant_id=4,content_asset_id=40,connection_id=50,
                    platform_code='xiaohongshu',source_version=3,revision_number=99,status='draft',title='new',content='new'))
            async with sessions() as db:
                with pytest.raises(HTTPException): await source.load_source(db,7,4,2,60,'xiaohongshu-image')
                with pytest.raises(HTTPException):
                    await source.load_asset(db,7,4,2,60,'xiaohongshu-image',old['content']['assets'][0]['id'])
    asyncio.run(scenario())


def test_replacement_reapproval_new_revision_and_no_old_asset_access():
    async def scenario():
        async with images_fixture() as sessions:
            old=await freeze(sessions)
            new=await freeze(sessions)
            assert old['source_revision']!=new['source_revision']
            async with sessions() as db:
                with pytest.raises(HTTPException) as exc:
                    await source.load_asset(db,7,4,2,60,'xiaohongshu-image',old['content']['assets'][0]['id'])
                assert exc.value.status_code==404
                for table in ['seo_distribution_media_sets','seo_distribution_media_bytes','seo_distribution_media_reviews']:
                    with pytest.raises(DBAPIError):
                        async with db.begin_nested(): await db.execute(text(f'DELETE FROM {table}'))
    asyncio.run(scenario())


@pytest.mark.parametrize('raw',[b'',b'<svg/>',b'GIF89a',b'\x89PNG\r\n\x1a\ninvalid',b'x'*(media.MAX_IMAGE+1)],
    ids=['empty','svg','gif','broken-png','oversized'])
def test_bad_images_rejected_without_mutation(raw):
    async def scenario():
        async with images_fixture() as sessions:
            async with sessions() as db:
                before=await media.preview(db,7,4,2,60)
                with pytest.raises(HTTPException) as exc: await upload(db,[raw])
                assert exc.value.status_code==422
                assert await media.preview(db,7,4,2,60)==before
    asyncio.run(scenario())


def test_pixel_count_animation_and_metadata_normalization():
    assert media.MAX_IMAGE==20_000_000 and media.MAX_PIXELS==25_000_000
    raw=picture()+b'private trailing metadata'
    data,kind=media.normalized_image(raw)
    assert kind=='image/png' and b'private trailing metadata' not in data
    output=io.BytesIO()
    Image.new('RGB',(5001,5000)).save(output,format='PNG')
    with pytest.raises(HTTPException): media.normalized_image(output.getvalue())
    output=io.BytesIO()
    Image.new('RGB',(8,8),'red').save(output,format='PNG',save_all=True,append_images=[Image.new('RGB',(8,8),'blue')])
    with pytest.raises(HTTPException): media.normalized_image(output.getvalue())


def test_v1_decimal_byte_boundary_and_valid_image_above_old_pixel_cap():
    raw=picture()
    data,kind=media.normalized_image(raw+b'\0'*(20_000_000-len(raw)))
    assert kind=='image/png' and len(data)<20_000_000
    output=io.BytesIO()
    Image.new('RGB',(4096,4096)).save(output,format='PNG')
    data,kind=media.normalized_image(output.getvalue())
    with Image.open(io.BytesIO(data)) as image: assert image.size==(4096,4096)
    with pytest.raises(HTTPException): media.normalized_image(picture('JPEG')[:50])


def test_native_jwt_upload_preview_and_independent_review_route():
    async def scenario():
        async with images_fixture() as sessions:
            app=FastAPI(); app.include_router(router)
            async def database():
                async with sessions() as db: yield db
            app.dependency_overrides[get_session]=database
            async with sessions() as db:
                author={'Authorization':'Bearer '+issue_token(await db.get(User,7))}
                reviewer={'Authorization':'Bearer '+issue_token(await db.get(User,8))}
            base='/api/seo/distribution-media/variants/60'
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://synthetic') as client:
                assert (await client.get(base,params={'tenant_id':4,'site_id':2})).status_code==401
                preview=(await client.get(base,headers=author,params={'tenant_id':4,'site_id':2})).json()
                uploaded=await client.post(base+'/assets',headers=author,data={'tenant_id':'4','site_id':'2',
                    'expected_token':preview['edit_token']},files=[('files',('ignored.png',picture(),'image/png'))])
                assert uploaded.status_code==200,uploaded.text
                draft=uploaded.json()
                params={'tenant_id':4,'site_id':2}
                image=await client.get(base+'/assets/'+draft['assets'][0]['id'],headers=reviewer,params=params)
                assert image.status_code==200 and image.headers['content-type']=='image/png'
                assert image.headers['cache-control']=='no-store'
                bad=await client.get(base+'/assets/'+draft['assets'][0]['id'],headers=reviewer,params={**params,'tenant_id':9})
                assert bad.status_code==403
                request={**params,'set_id':draft['set_id'],'expected_token':draft['edit_token']}
                assert (await client.post(base+'/review',headers=author,json=request)).status_code==403
                approved=await client.post(base+'/review',headers=reviewer,json=request)
                assert approved.status_code==200,approved.text
                assert approved.json()['content']['assets']==draft['assets']
    asyncio.run(scenario())


def test_upload_limits_stale_review_and_failed_confirmation_roll_back():
    async def scenario():
        async with images_fixture() as sessions:
            async with sessions() as db:
                before=await media.preview(db,7,4,2,60)
                for images in [[],[picture()]*10,[b'x'*media.MAX_IMAGE]*3]:
                    with pytest.raises(HTTPException) as exc:
                        await media.replace_assets(db,7,4,2,60,before['edit_token'],images)
                    assert exc.value.status_code==422
                assert await media.preview(db,7,4,2,60)==before
            async with sessions.begin() as db: first=await upload(db)
            async with sessions.begin() as db: second=await upload(db)
            with pytest.raises(HTTPException):
                async with sessions.begin() as db:
                    await media.review_assets(db,8,4,2,60,first['edit_token'],first['set_id'])
            async with sessions.begin() as db: (await db.get(SeoContentConfirmation,70)).decision='reject'
            with pytest.raises(HTTPException) as exc:
                async with sessions.begin() as db:
                    await media.review_assets(db,8,4,2,60,second['edit_token'],second['set_id'])
            assert exc.value.detail['code']=='seo_distribution_confirmation_required'
            async with sessions() as db:
                assert (await db.get(SeoDistributionVariant,60)).status=='draft'
                assert await db.scalar(text('SELECT count(*) FROM seo_distribution_media_reviews'))==0
    asyncio.run(scenario())


def test_concurrent_replacement_uses_expected_token_and_one_commits():
    async def scenario():
        async with images_fixture() as sessions:
            async with sessions() as db: preview=await media.preview(db,7,4,2,60)
            async def attempt():
                try:
                    async with sessions.begin() as db:
                        await media.replace_assets(db,7,4,2,60,preview['edit_token'],[picture()])
                    return 'committed'
                except HTTPException as exc: return exc.detail['code']
            assert sorted(await asyncio.gather(attempt(),attempt()))==['committed','seo_distribution_source_stale']
            async with sessions() as db:
                assert await db.scalar(text('SELECT count(*) FROM seo_distribution_media_sets'))==1
    asyncio.run(scenario())


def test_corrupted_stored_bytes_fail_hash_check():
    async def scenario():
        async with images_fixture() as sessions:
            snapshot=await freeze(sessions)
            async with sessions.begin() as db:
                # Deliberately simulate privileged storage corruption only in random test schema.
                await db.execute(text('ALTER TABLE seo_distribution_media_bytes DISABLE TRIGGER seo_media_bytes_immutable'))
                await db.execute(text("UPDATE seo_distribution_media_bytes SET data=set_byte(data,0,0)"))
                await db.execute(text('ALTER TABLE seo_distribution_media_bytes ENABLE TRIGGER seo_media_bytes_immutable'))
            async with sessions() as db:
                with pytest.raises(HTTPException) as exc:
                    await source.load_asset(db,7,4,2,60,'xiaohongshu-image',snapshot['content']['assets'][0]['id'])
                assert exc.value.detail['code']=='seo_distribution_assets_unavailable'
    asyncio.run(scenario())


def test_creator_cannot_approve_other_upload_and_legacy_approval_cannot_freeze():
    async def scenario():
        async with images_fixture() as sessions:
            async with sessions.begin() as db:
                (await db.get(SeoDistributionVariant,60)).created_by=8
            async with sessions.begin() as db: draft=await upload(db)
            with pytest.raises(HTTPException) as exc:
                async with sessions.begin() as db:
                    await media.review_assets(db,8,4,2,60,draft['edit_token'],draft['set_id'])
            assert exc.value.detail['code']=='seo_distribution_independent_review_required'
            async with sessions.begin() as db:
                variant=await db.get(SeoDistributionVariant,60)
                variant.status='approved'; variant.reviewed_by=8; variant.reviewed_at=datetime(2026,10,11)
            async with sessions() as db:
                with pytest.raises(HTTPException) as exc: await source.load_source(db,7,4,2,60,'xiaohongshu-image')
                assert exc.value.detail['code']=='seo_distribution_assets_unavailable'
    asyncio.run(scenario())


def test_missing_media_schema_fails_closed_but_wechat_remains_available():
    async def scenario():
        async with fixture() as sessions:
            async with sessions() as db:
                assert (await source.load_source(db,7,4,2,60,'wechat-article'))['content']['assets']==[]
            async with sessions.begin() as db:
                (await db.get(SeoDistributionVariant,60)).platform_code='xiaohongshu'
                (await db.get(SeoDistributionConnection,50)).platform_code='xiaohongshu'
            async with sessions() as db:
                with pytest.raises(HTTPException) as exc: await source.load_source(db,7,4,2,60,'xiaohongshu-image')
                assert exc.value.status_code==503
                assert exc.value.detail['code']=='seo_distribution_source_unavailable'
    asyncio.run(scenario())


def test_truncated_jpeg_cannot_be_accepted_under_permissive_global_decoder(monkeypatch):
    truncated=picture('JPEG')[:-2]
    with pytest.raises(HTTPException): media.normalized_image(truncated)
    monkeypatch.setattr(ImageFile,'LOAD_TRUNCATED_IMAGES',True)
    for data in [picture('JPEG'),truncated,picture()]:
        with pytest.raises(HTTPException) as exc: media.normalized_image(data)
        assert exc.value.status_code==503
        assert ImageFile.LOAD_TRUNCATED_IMAGES is True


def test_global_decoder_flag_blocks_upload_review_preview_and_distribution_bytes(monkeypatch):
    async def scenario():
        async with images_fixture() as sessions:
            snapshot=await freeze(sessions)
            item=snapshot['content']['assets'][0]
            async with sessions.begin() as db: draft=await upload(db)
            monkeypatch.setattr(ImageFile,'LOAD_TRUNCATED_IMAGES',True)
            async with sessions() as db:
                before=await media.preview(db,7,4,2,60)
                for call in [lambda:upload(db),lambda:media.review_assets(db,8,4,2,60,draft['edit_token'],draft['set_id']),
                    lambda:media.preview_asset(db,8,4,2,60,draft['assets'][0]['id'])]:
                    with pytest.raises(HTTPException) as exc: await call()
                    assert exc.value.status_code==503
                assert await media.preview(db,7,4,2,60)==before
            monkeypatch.setattr(ImageFile,'LOAD_TRUNCATED_IMAGES',False)
            async with sessions.begin() as db: current=await media.review_assets(db,8,4,2,60,draft['edit_token'],draft['set_id'])
            monkeypatch.setattr(ImageFile,'LOAD_TRUNCATED_IMAGES',True)
            async with sessions() as db:
                with pytest.raises(HTTPException) as exc:
                    await source.load_asset(db,7,4,2,60,'xiaohongshu-image',current['content']['assets'][0]['id'])
                assert exc.value.status_code==503 and ImageFile.LOAD_TRUNCATED_IMAGES is True
    asyncio.run(scenario())


def test_global_decoder_change_during_decode_is_rechecked(monkeypatch):
    raw=picture('JPEG')
    original=Image.Image.load
    def changed(image,*args,**kwargs):
        result=original(image,*args,**kwargs)
        ImageFile.LOAD_TRUNCATED_IMAGES=True
        return result
    monkeypatch.setattr(ImageFile,'LOAD_TRUNCATED_IMAGES',False)
    monkeypatch.setattr(Image.Image,'load',changed)
    with pytest.raises(HTTPException) as exc: media.normalized_image(raw)
    assert exc.value.status_code==503


def test_editing_picker_includes_unapproved_only_with_current_scope():
    async def scenario():
        async with images_fixture() as sessions:
            async with sessions.begin() as db: await upload(db)
            async with sessions() as db:
                await db.execute(text('SET TRANSACTION READ ONLY'))
                assert await media.list_drafts(db,7,4,2)==[{'variant_id':60,'title':'selection article','status':'draft'}]
                assert await source.list_sources(db,7,4,2,'xiaohongshu-image')==[]
                with pytest.raises(HTTPException): await media.list_drafts(db,7,9,2)
    asyncio.run(scenario())
