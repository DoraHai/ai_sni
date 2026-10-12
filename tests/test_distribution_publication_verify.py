"""Public-page parsing and fixed-host transport checks without platform access."""
import asyncio
from types import SimpleNamespace

import pytest

from app import distribution_publication_verify as verifier


CONTENT = {'version': 'frozen1', 'title': '审核标题', 'body': '<p>正文第一段。</p><p>正文第二段。</p>', 'assets': []}


def page(title='审核标题', body='<p>正文第一段。</p><p>正文第二段。</p>', identity='gh_test'):
    return verifier.PublicPage(200, 'text/html', (
        '<html><body><h1 id="activity-name">' + title + '</h1><div id="js_content">' + body + '</div>'
        + '<script>\nvar user_name = "' + identity + '";\n</script></body></html>').encode())


def test_complete_text_and_stable_account_match_only():
    result = verifier.inspect_page('wechat-article', page(), CONTENT, 'gh_test')
    assert result['status'] == 'needs-human'
    assert result['code'] == 'PUBLIC_TEXT_AND_ACCOUNT_MATCHED'
    assert 'verification' not in result
    assert len(result['observed_digest']) == 64
    assert verifier.inspect_page('wechat-article', page(identity='gh_other'), CONTENT, 'gh_test')['code'] == 'ACCOUNT_UNVERIFIED'
    assert verifier.inspect_page('wechat-article', page(body='<p>只有第一段。</p>'), CONTENT, 'gh_test')['code'] == 'CONTENT_MISMATCH'
    assert verifier.inspect_page('wechat-article', page(title='另一个标题'), CONTENT, 'gh_test')['status'] == 'needs-human'


def test_assets_extra_images_and_wrong_page_never_pass():
    assert verifier.inspect_page('wechat-article', page(), {**CONTENT, 'assets': [{'id': 'a'}]}, 'gh_test')['code'] == 'ASSETS_REQUIRE_HUMAN'
    assert verifier.inspect_page('wechat-article', page(body=CONTENT['body']+'<img src="https://example.invalid/extra.png">'), CONTENT, 'gh_test')['code'] == 'ASSETS_REQUIRE_HUMAN'
    assert verifier.inspect_page('wechat-article', verifier.PublicPage(302, 'text/html', b''), CONTENT, 'gh_test')['code'] == 'PAGE_UNAVAILABLE'
    assert verifier.inspect_page('xiaohongshu-image', page(), CONTENT, 'gh_test')['code'] == 'CHANNEL_REQUIRES_HUMAN'
    assert verifier.inspect_page('wechat-article', verifier.PublicPage(200, 'text/html', '<title>登录</title>'.encode()), CONTENT, 'gh_test')['code'] == 'PAGE_LAYOUT_UNVERIFIED'


def test_hidden_duplicate_fields_and_body_identity_cannot_self_attest():
    wrong = page(body='<p style="display: none">正文第一段。正文第二段。</p>')
    assert verifier.inspect_page('wechat-article', wrong, CONTENT, 'gh_test')['status'] == 'needs-human'
    duplicate = verifier.PublicPage(200, 'text/html', page().body + b'<div id="js_content"></div>')
    assert verifier.inspect_page('wechat-article', duplicate, CONTENT, 'gh_test')['code'] == 'PAGE_LAYOUT_UNVERIFIED'
    forged = page().body.replace(b'<script>\nvar user_name = "gh_test";\n</script>', b'<p>var user_name = "gh_test";</p>')
    assert verifier.inspect_page('wechat-article', verifier.PublicPage(200, 'text/html', forged), CONTENT, 'gh_test')['code'] == 'ACCOUNT_UNVERIFIED'


@pytest.mark.parametrize('extra', ['<style>#js_content {display:none}</style>',
    '<style>body {visibility:hidden}</style>'])
def test_stylesheet_visibility_is_never_a_final_machine_seal(extra):
    hidden = verifier.PublicPage(200, 'text/html', extra.encode() + page().body)
    result = verifier.inspect_page('wechat-article', hidden, CONTENT, 'gh_test')
    assert result['status'] == 'needs-human' and 'verification' not in result


@pytest.mark.parametrize('extra', ['<svg><image href="extra.png"/></svg>', '<video src="extra.mp4"></video>',
    '<audio src="extra.mp3"></audio>', '<iframe src="extra.html"></iframe>', '<object></object>',
    '<embed src="extra.bin">', '<canvas></canvas>', '<picture></picture>'])
def test_non_img_media_requires_human(extra):
    result = verifier.inspect_page('wechat-article', page(body=CONTENT['body'] + extra), CONTENT, 'gh_test')
    assert result == {'status': 'needs-human', 'code': 'ASSETS_REQUIRE_HUMAN'}


@pytest.mark.parametrize('html', ['<div>' * 5000 + '</mismatch>' * 5000,
    '<br>' * (verifier.MAX_PARSE_EVENTS + 1), '<!--comment-->' * (verifier.MAX_PARSE_EVENTS + 1)],
    ids=['excessive-depth', 'excessive-tags', 'excessive-comments'])
def test_html_resource_limits_are_bounded_and_fail_closed(html):
    result = verifier.inspect_page('wechat-article', page(body=html), CONTENT, 'gh_test')
    assert result == {'status': 'needs-human', 'code': 'PAGE_UNAVAILABLE'}


def test_approved_body_parser_failure_also_needs_human():
    result = verifier.inspect_page('wechat-article', page(), {**CONTENT, 'body': '<div>' * 5000}, 'gh_test')
    assert result == {'status': 'needs-human', 'code': 'PAGE_UNAVAILABLE'}


def test_parser_time_budget_fails_closed(monkeypatch):
    clock = iter([0, verifier.PARSE_SECONDS + 1])
    monkeypatch.setattr(verifier.time, 'monotonic', lambda: next(clock))
    assert verifier.inspect_page('wechat-article', page(), CONTENT, 'gh_test') == {'status':'needs-human','code':'PAGE_UNAVAILABLE'}


@pytest.mark.parametrize('url', ['http://mp.weixin.qq.com/s/a', 'https://mp.weixin.qq.com.evil.invalid/s/a',
    'https://u@mp.weixin.qq.com/s/a', 'https://mp.weixin.qq.com:443/s/a', 'https://mp.weixin.qq.com/s/a?x=1',
    'https://mp.weixin.qq.com/s/a#x', 'https://mp.weixin.qq.com/s/../a', 'https://127.0.0.1/s/a'])
def test_fixed_official_target_rejects_alternatives(url):
    with pytest.raises(ValueError): verifier.fixed_target('wechat-article', url)


def test_dns_answer_is_pinned_and_any_private_address_denies_all(monkeypatch):
    def answer(addresses): return [(2, 1, 6, '', (a, 443)) for a in addresses]
    monkeypatch.setattr(verifier.socket, 'getaddrinfo', lambda *_a, **_kw: answer(['1.1.1.1', '1.1.1.1']))
    assert verifier.public_addresses('mp.weixin.qq.com') == ['1.1.1.1']
    monkeypatch.setattr(verifier.socket, 'getaddrinfo', lambda *_a, **_kw: answer(['1.1.1.1', '127.0.0.1']))
    with pytest.raises(ValueError): verifier.public_addresses('mp.weixin.qq.com')


def test_pinned_socket_uses_resolved_address_and_original_tls_hostname(monkeypatch):
    calls=[]
    raw=SimpleNamespace(settimeout=lambda t:None, close=lambda:None)
    monkeypatch.setattr(verifier.socket, 'create_connection', lambda address, timeout:(calls.append(address) or raw))
    connection=verifier.PinnedHTTPSConnection('mp.weixin.qq.com',['1.1.1.1'],verifier.time.monotonic()+5)
    connection._context=SimpleNamespace(wrap_socket=lambda sock, server_hostname:(calls.append(server_hostname) or raw))
    connection.connect()
    assert calls==[('1.1.1.1',443),'mp.weixin.qq.com']


def test_async_fetch_errors_are_unavailable_and_do_not_leak(monkeypatch):
    def fail(*_args): raise OSError('synthetic-sensitive-details')
    monkeypatch.setattr(verifier, 'fetch_public_page', fail)
    result=asyncio.run(verifier.verify_publication('wechat-article','https://mp.weixin.qq.com/s/test',CONTENT,'gh_test'))
    assert result=={'status':'needs-human','code':'PAGE_UNAVAILABLE'}


def test_transport_does_not_follow_redirect_or_take_page_credentials(monkeypatch):
    calls=[]
    class FakeConnection:
        sock=SimpleNamespace(settimeout=lambda t:None)
        def __init__(self,host,addresses,deadline):calls.append((host,addresses))
        def request(self,method,path,headers):calls.append((method,path,headers))
        def remaining(self):return 5
        def getresponse(self):return SimpleNamespace(status=302,getheader=lambda name,default='': 'text/html' if name=='Content-Type' else default)
        def close(self):calls.append('closed')
    monkeypatch.setattr(verifier,'public_addresses',lambda host:['1.1.1.1'])
    monkeypatch.setattr(verifier,'PinnedHTTPSConnection',FakeConnection)
    assert verifier.fetch_public_page('wechat-article','https://mp.weixin.qq.com/s/test').status==302
    assert calls[-1]=='closed' and len(calls)==3
    assert not any(k.lower() in ('cookie','authorization') for k in calls[1][2])
