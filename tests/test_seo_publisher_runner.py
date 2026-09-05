import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

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
