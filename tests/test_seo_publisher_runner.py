import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, MagicMock, patch

import pytest

spec = importlib.util.spec_from_file_location('seo_runner', Path(__file__).resolve().parents[1] / 'frontend/src/views/seo/publisher-runner/runner.py')
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


def task(platform='baijiahao'):
    return {'publication_id': 7, 'platform_code': platform, 'account': '品牌账号',
            'source_version': '2', 'title': '测试标题', 'text': '真实内容\n第二段',
            'editor_url': 'https://' + runner.PROFILES[platform]['host'] + '/'}


@pytest.mark.parametrize('field,value', [('editor_url','https://baijiahao.baidu.com.evil.test/'), ('publication_id',True), ('platform_code','unknown'), ('source_version','')])
def test_task_rejects_invalid_package(field, value):
    with pytest.raises(ValueError):
        runner.validate_task({**task(), field: value})


def test_task_key_includes_account_version_and_content():
    original = runner.task_key(task())
    for field in ['account', 'source_version', 'text']:
        assert runner.task_key({**task(), field:'changed'}) != original


def test_public_result_refuses_editor_and_other_platform():
    for value in ['https://mp.toutiao.com/editor/1', 'https://www.sohu.com/a/123', 'https://www.toutiao.com/']:
        with pytest.raises(ValueError):
            runner.public_url(value, 'toutiao')
    assert runner.public_url('https://www.toutiao.com/article/123#x', 'toutiao') == 'https://www.toutiao.com/article/123'


def test_nonempty_field_is_not_overwritten():
    element=Mock()
    element.evaluate.return_value='用户已有正文'
    with pytest.raises(ValueError):
        runner.fill_empty(element, '新正文')
    element.fill.assert_not_called()


def test_cross_origin_frames_are_never_used():
    frame=SimpleNamespace(url='https://other.example/editor',locator=Mock())
    page=SimpleNamespace(url='https://baijiahao.baidu.com/',frames=[frame])
    with pytest.raises(ValueError):runner.unique_visible(page,runner.TITLE)
    frame.locator.assert_not_called()


def test_atomic_journal_roundtrip(tmp_path):
    path=tmp_path/'journal.json'
    runner.save_json(path, {'state':'submit_attempted'})
    runner.save_json(path, {'state':'needs_result_check'})
    assert 'needs_result_check' in path.read_text()
    assert not path.with_suffix('.tmp').exists()


def test_draft_recovery_rejects_nonofficial_url():
    for url in ['http://mp.toutiao.com/editor/1','https://mp.toutiao.com.evil.test/','https://user@mp.toutiao.com/editor/1']:
        with pytest.raises(ValueError):runner.editor_url(url,'toutiao')
    assert runner.editor_url('https://mp.toutiao.com/editor/1','toutiao').endswith('/1')


@pytest.mark.parametrize('actual',['','不同的草稿'])
def test_recovery_does_not_refill_redirected_or_changed_draft(actual):
    field=Mock();field.evaluate.return_value=actual
    with patch.object(runner,'unique_visible',return_value=field):
        with pytest.raises(ValueError):runner.confirm_restored_draft(SimpleNamespace(url=task()['editor_url']),task())
    field.fill.assert_not_called()


def test_recovery_requires_both_original_title_and_original_body():
    title=Mock();title.evaluate.return_value=task()['title']
    body=Mock();body.evaluate.return_value=task()['text']
    with patch.object(runner,'unique_visible',side_effect=[title,body]):runner.confirm_restored_draft(SimpleNamespace(url=task()['editor_url']),task())
    title.fill.assert_not_called();body.fill.assert_not_called()


def test_real_browser_category_cover_and_scoped_result_collection(tmp_path):
    import os,base64
    if not os.environ.get('SEO_RUNNER_BROWSER_TEST'):pytest.skip('opt-in Chromium fixture')
    from playwright.sync_api import sync_playwright
    png=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=')
    cover=tmp_path/'cover.png';cover.write_bytes(png)
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True,channel='chromium')
        try:
            page=browser.new_page()
            html='''<label>分类<select><option>资讯</option><option>科技</option></select></label>
              <label>封面<input type=file accept="image/png" onchange="document.querySelector('img').src='/cover.png'"></label><img alt="封面">
              <table><tr><td>其他标题</td><td>已发布</td><td><a href="https://www.toutiao.com/article/old">查看</a></td></tr>
              <tr><td>测试标题</td><td>审核中</td></tr></table>'''
            page.route('**/*',lambda route:route.fulfill(status=200,content_type='image/png' if route.request.url.endswith('cover.png') else 'text/html; charset=utf-8',body=png if route.request.url.endswith('cover.png') else html))
            page.goto(task('toutiao')['editor_url'])
            runner.apply_settings(page,{'category':'科技','cover':str(cover)})
            assert page.locator('select').input_value()=='科技'
            result=runner.collect_result(page,task('toutiao'))
            assert result['state']=='审核中' and result['page_url'] is None
            page.locator('tr').last.evaluate("el=>el.innerHTML='<td>测试标题</td><td>已发布</td><td><a href=\"https://www.toutiao.com/article/new\">查看</a></td>'")
            assert runner.collect_result(page,task('toutiao'))['page_url']=='https://www.toutiao.com/article/new'
            page.locator('table').evaluate('(el)=>el.insertAdjacentHTML("beforeend",el.lastElementChild.outerHTML)')
            assert runner.collect_result(page,task('toutiao'))['state']=='unknown'
        finally:browser.close()


def test_browser_start_failure_does_not_abort_later_tasks(tmp_path):
    import sys
    browser = MagicMock()
    context = MagicMock()
    page = context.pages[0]
    page.url = task()['editor_url']
    browser.chromium.launch_persistent_context.side_effect = [RuntimeError('profile locked'), context]
    manager = MagicMock()
    manager.__enter__.return_value = browser
    args = SimpleNamespace(workdir=tmp_path, images=None, publish=False)
    with patch.dict(sys.modules, {'playwright.sync_api': SimpleNamespace(sync_playwright=lambda: manager)}), patch('builtins.input', return_value=''), patch.object(runner, 'prepare', return_value='prepared'):
        report = runner.execute(args, [task(), {**task(), 'publication_id': 8}])
    assert browser.chromium.launch_persistent_context.call_count == 2
    assert report['failed'] == 1 and report['pending'] == 1
    assert (tmp_path/'run-report.json').exists()
    context.close.assert_called_once()


def test_submit_timeout_is_recorded_before_click_and_not_retried(tmp_path):
    import sys,json
    browser=MagicMock();context=MagicMock();context.pages[0].url=task()['editor_url']
    browser.chromium.launch_persistent_context.return_value=context
    manager=MagicMock();manager.__enter__.return_value=browser
    args=SimpleNamespace(workdir=tmp_path,images=None,publish=True)
    def timeout(*_):
        journal=json.loads((tmp_path/'journal.json').read_text())
        assert journal[runner.task_key(task())]['state']=='submit_attempted'
        raise TimeoutError('uncertain submit')
    with patch.dict(sys.modules,{'playwright.sync_api':SimpleNamespace(sync_playwright=lambda:manager)}), patch.object(runner,'prepare',return_value='prepared') as prepare, patch.object(runner,'click_exact',side_effect=timeout) as click:
        with patch('builtins.input',side_effect=['','publish']):
            result=runner.execute(args,[task()])
        assert result['failed']==1
        with patch('builtins.input',return_value=''):
            resumed=runner.execute(args,[task()])
        assert resumed['pending']==1
        assert click.call_count==1 and prepare.call_count==1


def test_default_mode_cannot_submit_even_if_operator_types_publish(tmp_path):
    import sys
    browser=MagicMock();context=MagicMock();context.pages[0].url=task()['editor_url']
    browser.chromium.launch_persistent_context.return_value=context
    manager=MagicMock();manager.__enter__.return_value=browser
    args=SimpleNamespace(workdir=tmp_path,images=None,publish=False)
    with patch.dict(sys.modules,{'playwright.sync_api':SimpleNamespace(sync_playwright=lambda:manager)}),patch.object(runner,'prepare',return_value='prepared'),patch.object(runner,'click_exact') as click,patch('builtins.input',side_effect=['','publish','']):
        assert runner.execute(args,[task()])['pending']==1
    click.assert_not_called()


def test_opaque_sandbox_frame_and_incompatible_image_types_are_rejected():
    frame=SimpleNamespace(url='about:srcdoc',parent_frame=SimpleNamespace(url='https://baijiahao.baidu.com/'),frame_element=lambda:SimpleNamespace(get_attribute=lambda _:'allow-scripts'))
    assert runner.allowed_frame(frame,'baijiahao.baidu.com') is False
    assert runner.accepts_images('.png,.jpg',[Path('image.png')]) is True
    assert runner.accepts_images('image/jpeg',[Path('image.png')]) is False
    assert runner.accepts_images('image/*',[Path('document.txt')]) is False


def test_inherited_editor_and_extension_only_image_upload(tmp_path):
    import os
    if not os.environ.get('SEO_RUNNER_BROWSER_TEST'):
        pytest.skip('opt-in real Chromium fixture')
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True,channel='chromium')
        try:
            page=browser.new_page()
            html='<input placeholder="标题"><iframe srcdoc="&lt;body contenteditable=true&gt;&lt;/body&gt;"></iframe><input type=file accept=".jpg,.jpeg,.png">'
            page.route('**/*',lambda route:route.fulfill(status=200,content_type='text/html; charset=utf-8',body=html))
            page.goto(task()['editor_url'])
            page.frame_locator('iframe').locator('body').wait_for()
            image=tmp_path/'test.png';image.write_bytes(b'fixture')
            runner.prepare(page,task(),[image])
            assert page.frame_locator('iframe').locator('body').inner_text()==task()['text']
            assert page.locator('input[type=file]').evaluate('(el)=>el.files.length')==1
        finally:browser.close()


@pytest.mark.parametrize('platform', list(runner.PROFILES))
def test_real_browser_simulated_editor_fill_upload_and_no_implicit_publish(platform, tmp_path):
    import os
    if not os.environ.get('SEO_RUNNER_BROWSER_TEST'):
        pytest.skip('opt-in real Chromium fixture; no live platform account')
    from playwright.sync_api import sync_playwright
    item=task(platform)
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True, channel='chromium')
        try:
            page=browser.new_page()
            html='<input placeholder="请输入标题"><textarea></textarea><input type="file" accept="image/*" multiple><button onclick="window.saved=true">保存草稿</button><button onclick="window.sent=true">发布</button>'
            page.route('**/*', lambda route: route.fulfill(status=200, content_type='text/html; charset=utf-8', body=html))
            page.goto(item['editor_url'])
            image=tmp_path/'test.png'
            import base64
            image.write_bytes(base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII='))
            runner.prepare(page,item,[image])
            assert page.locator('textarea').input_value()==item['text']
            assert page.locator('input[type=file]').evaluate('(el)=>el.files.length')==1
            assert page.evaluate('window.sent') is None
            runner.click_exact(page,['保存草稿','存草稿'])
            assert page.evaluate('window.saved') is True
            assert page.evaluate('window.sent') is None
            page.locator('textarea').fill('用户修改')
            with pytest.raises(ValueError):runner.prepare(page,item,[])
            assert page.locator('textarea').input_value()=='用户修改'
            page.locator('body').evaluate('(el)=>el.insertAdjacentHTML("beforeend","<textarea></textarea>")')
            with pytest.raises(ValueError):runner.prepare(page,item,[])
        finally:
            browser.close()



def qa_module():
    import sys
    spec=importlib.util.spec_from_file_location('qa_local_runner',Path(__file__).resolve().parents[1]/'frontend/src/views/seo/publisher-runner/qa_runner.py')
    module=importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules,{'runner':runner}): spec.loader.exec_module(module)
    return module


def qa_task():
    from datetime import datetime,timedelta,timezone
    return {'kind':'seo_qa_assist','schema_version':1,'tenant_id':1,'site_id':1,'placement_id':1,
        'content_version':2,'platform':'zhihu','question_url':'https://www.zhihu.com/question/12',
        'body':'这是经过审核的回答正文，用于验证本地填稿。','expires_at':(datetime.now(timezone.utc)+timedelta(minutes=30)).isoformat()}


@pytest.mark.parametrize('field,value',[('question_url','https://www.zhihu.com.evil.test/question/12'),
    ('question_url','https://www.zhihu.com/question/12/answer/34'),('platform','website'),
    ('expires_at','2000-01-01T00:00:00Z'),('placement_id',True)])
def test_qa_assistant_rejects_wrong_target_and_expired_tasks(field,value):
    with pytest.raises(ValueError): qa_module().validate_task({**qa_task(),field:value})


@pytest.mark.parametrize('platform,url', [('zhihu','https://www.zhihu.com/question/12'),('csdn_qa','https://ask.csdn.net/questions/12')])
def test_qa_assistant_browser_only_fills_selected_empty_answer(tmp_path,platform,url):
    import os
    if not os.environ.get('SEO_RUNNER_BROWSER_TEST'): pytest.skip('opt-in Chromium fixture, no live platform login')
    from playwright.sync_api import sync_playwright
    qa=qa_module();task={**qa_task(),'platform':platform,'question_url':url}
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True,channel='chromium')
        page=browser.new_page()
        page.route('**/*',lambda route:route.fulfill(body='<textarea id="answer"></textarea><textarea placeholder="评论"></textarea><button onclick="window.published=true">发布</button>',content_type='text/html; charset=utf-8'))
        page.goto(task['question_url'])
        with pytest.raises(ValueError): qa.prepare_answer(page,task)
        page.locator('[placeholder="评论"]').focus()
        with pytest.raises(ValueError): qa.prepare_answer(page,task)
        page.locator('#answer').focus();qa.prepare_answer(page,task)
        assert page.locator('#answer').input_value()==task['body']
        assert page.evaluate('window.published') is None
        page.locator('#answer').fill('已有其他内容')
        with pytest.raises(ValueError): qa.prepare_answer(page,task)
        page.goto(url[:-2]+'13');page.locator('#answer').focus()
        with pytest.raises(ValueError): qa.prepare_answer(page,task)
        browser.close()


@pytest.mark.parametrize('platform,question,answer', [
    ('zhihu','https://www.zhihu.com/question/12','https://www.zhihu.com/question/12/answer/34'),
    ('csdn_qa','https://ask.csdn.net/questions/12','https://ask.csdn.net/questions/12#answer_34')])
def test_qa_receipt_only_records_operator_url_without_success_claim(platform,question,answer):
    qa=qa_module(); task={**qa_task(),'version':3,'platform':platform,'question_url':question,
                           'expires_at':'2000-01-01T00:00:00Z'}
    # Filling TTL is not a deadline for reporting an actual later publication.
    result=qa.make_receipt(task,answer)
    assert result['answer_url']==answer and result['version']==3
    assert 'body' not in result and 'status' not in result and result['kind']=='seo_qa_receipt'
    for bad in ['https://evil.example/questions/12',question.replace('/12','/99'),
                'javascript:alert(1)','https://user:pass@'+question[8:]]:
        with pytest.raises(ValueError): qa.make_receipt(task,bad)
    with pytest.raises(ValueError): qa.make_receipt({**task,'version':None},answer)
