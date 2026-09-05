import asyncio
import pytest
from app import seo_distribution as distribution


def test_domestic_platforms_first_and_no_false_api_capability():
    catalog = distribution.platform_catalog()
    assert catalog[0]['code'] == 'baijiahao'
    by_code = {p['code']: p for p in catalog}
    for code in ('baijiahao', 'toutiao', 'sohu', 'wangyi', 'penguin', 'wechat_browser', 'xiaohongshu', 'weibo'):
        p = by_code[code]
        assert p['available'] and p['mode'] == 'assisted'
        assert p['credential_fields'] == []
        assert 'publish' not in p['capabilities']
        assert p['editor_url'].startswith('https://')
    assert not {'wordpress','ghost','douyin'} & by_code.keys()
    assert len(by_code) == 13
    assert all(p['region']=='domestic' and p['available'] for p in catalog)
    assert by_code['wechat_official']['mode'] == 'api'


@pytest.mark.parametrize('code', ['baijiahao','toutiao','sohu','wangyi','penguin','wechat_browser','xiaohongshu','weibo'])
def test_domestic_tasks_do_not_report_published_or_use_network(code, monkeypatch):
    def reject_network(*args, **kwargs):
        raise AssertionError('browser task must not use network')
    monkeypatch.setattr(distribution.httpx, 'AsyncClient', reject_network)
    result = asyncio.run(distribution.publish_content(platform_code=code, base_url=None, credentials={}, prepared=distribution.prepare_content('核验过的文章', '事实与依据', code), action='publish'))
    assert result.status == 'manual_required'
    assert result.page_url is None
    assert result.response_summary['handoff_url'] == distribution.platform_definition(code)['editor_url']


def test_domestic_preflight_flags_notes_images_links_and_claims_without_truncation():
    body = '<p>' + '实际资料' * 400 + '</p><a href="https://example.com">参考</a>'
    messages = distribution.domestic_content_warnings('保证排名', body, 'xiaohongshu')
    assert len(messages) == 5
    assert any('不会自动截断' in m for m in messages)
    assert any('尚无配图' in m for m in messages)
    prepared = distribution.prepare_content('资料核验', body, 'xiaohongshu')
    assert '实际资料' * 400 in prepared['content_html']
    assert distribution.domestic_content_warnings('保证排名', body, 'wordpress') == []
