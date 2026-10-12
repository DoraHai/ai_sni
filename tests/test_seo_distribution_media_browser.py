"""Opt-in browser acceptance with native API/JWT/PostgreSQL; local network only."""
import asyncio
import json
import os
from pathlib import Path
import socket

from fastapi import FastAPI
import pytest
import uvicorn

from app.api.seo_distribution_media import router
from app.database import get_session
from app.security.auth import issue_token
from app.models.user import User
from app.models.seo import SeoDistributionVariant
from test_seo_distribution_media_postgres import images_fixture,picture

pytestmark=pytest.mark.skipif(os.getenv('SEO_MEDIA_BROWSER_TEST')!='true',reason='explicit local browser opt-in required')


def test_advisor_upload_independent_review_and_replacement_in_real_browser():
    from playwright.async_api import async_playwright,expect
    async def scenario():
        async with images_fixture() as sessions:
            app=FastAPI();app.include_router(router)
            async def database():
                async with sessions() as db: yield db
            app.dependency_overrides[get_session]=database
            identities={}
            async with sessions() as db:
                for actor in (7,8):
                    identities[actor]={'version':1,'token':issue_token(await db.get(User,actor)),
                        'user':{'id':actor,'tenant_id':None,'permissions':{'seo.content':'edit','seo.site':'edit'}}}
            listener=socket.socket();listener.bind(('127.0.0.1',0));listener.listen()
            origin=f'http://127.0.0.1:{listener.getsockname()[1]}'
            server=uvicorn.Server(uvicorn.Config(app,log_level='error',access_log=False))
            serving=asyncio.create_task(server.serve(sockets=[listener]))
            try:
                for _ in range(100):
                    if server.started:break
                    if serving.done():await serving
                    await asyncio.sleep(.05)
                assert server.started
                async with async_playwright() as playwright:
                    executables=list((Path(os.environ['LOCALAPPDATA'])/'ms-playwright').glob('chromium-*/chrome-win64/chrome.exe'))
                    assert executables,'Local test Chromium missing'
                    browser=await playwright.chromium.launch(headless=True,executable_path=str(sorted(executables)[-1]))
                    try:
                        pages={}; contexts=[];external=[];errors=[]
                        for actor in (7,8):
                            context=await browser.new_context(viewport={'width':1200,'height':1000})
                            contexts.append(context)
                            await context.add_init_script('sessionStorage.setItem("sem_auth_v1",'+json.dumps(json.dumps(identities[actor]))+');')
                            async def only_local(route):
                                if route.request.url.startswith(origin+'/'):await route.continue_()
                                else:external.append(route.request.url);await route.abort()
                            await context.route('**/*',only_local)
                            page=await context.new_page();page.on('pageerror',lambda error:errors.append(str(error)))
                            pages[actor]=page
                            await page.goto(origin+'/api/seo/distribution-media/workspace?tenant_id=4&site_id=2')
                        async def select(page):
                            await page.get_by_role('button',name='读取稿件').click()
                            await expect(page.locator('#variant option[value="60"]')).to_have_count(1)
                            await page.locator('#variant').select_option('60')
                            await expect(page.locator('#title')).to_have_text('selection article')
                        author,reviewer=pages[7],pages[8]
                        await select(author)
                        await author.locator('#files').set_input_files([
                            {'name':'one.png','mimeType':'image/png','buffer':picture()},
                            {'name':'two.jpg','mimeType':'image/jpeg','buffer':picture('JPEG','blue')}])
                        await author.get_by_role('button',name='上传并替换图片').click()
                        await expect(author.locator('#notice')).to_contain_text('图片已保存')
                        await expect(author.locator('#images img')).to_have_count(2)
                        await author.locator('#confirmed').check()
                        await author.get_by_role('button',name='审核通过并冻结').click()
                        await expect(author.locator('#notice')).to_contain_text('其他有权限的顾问')
                        await select(reviewer)
                        await expect(reviewer.locator('#images img')).to_have_count(2)
                        await reviewer.locator('#confirmed').check()
                        await reviewer.get_by_role('button',name='审核通过并冻结').click()
                        await expect(reviewer.locator('#notice')).to_contain_text('审核通过，当前正文与图片已冻结')
                        await expect(reviewer.locator('#variant option:checked')).to_contain_text('已审核')
                        await expect(reviewer.locator('#body')).to_have_text('selection article body')
                        await expect(reviewer.locator('#review')).to_be_disabled()
                        screenshot=Path(os.environ['TEMP'])/'seo-media-browser-approved.png'
                        await reviewer.screenshot(path=str(screenshot),full_page=True)
                        await select(author)
                        await author.locator('#files').set_input_files({'name':'replacement.png','mimeType':'image/png','buffer':picture('PNG','green')})
                        await author.get_by_role('button',name='上传并替换图片').click()
                        await expect(author.locator('#notice')).to_contain_text('旧审核已撤销')
                        async with sessions() as db:assert (await db.get(SeoDistributionVariant,60)).status=='draft'
                        await author.locator('#tenant').fill('9')
                        await expect(author.locator('#upload')).to_be_disabled()
                        await author.get_by_role('button',name='读取稿件').click()
                        await expect(author.locator('#notice')).to_have_attribute('data-error','true')
                        await expect(author.locator('#images img')).to_have_count(0)
                        assert not external and not errors,(external,errors)
                        (Path(os.environ['TEMP'])/'seo-media-browser-evidence.json').write_text(json.dumps({
                            'checks':['real JWT','native PostgreSQL','draft picker','upload PNG/JPEG','preview images',
                                'self-review rejected','independent review frozen','replacement revokes review','scope change clears stale view'],
                            'external_requests':0,'page_errors':0,'screenshot':str(screenshot)},indent=2),encoding='utf-8')
                        for context in contexts:await context.close()
                    finally:await browser.close()
            finally:
                server.should_exit=True
                await asyncio.wait_for(serving,10)
                listener.close()
    asyncio.run(scenario())
