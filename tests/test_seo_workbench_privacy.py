import pytest
from app.seo_workbench_privacy import redact, redact_text, REDACTED


@pytest.mark.parametrize('text',[
    'Bearer abcdefghijklmnopqrstuvwxyz', 'sk-abcdefghijklmnop1234567890',
    'eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.c2lnbmF0dXJl',
    '"DEEPSEEK_API_KEY":"synthetic-key"', '密码：synthetic-password',
    'postgresql+asyncpg://user:synthetic-pass@localhost/database',
    'test@example.com', '+86 138 0013 8000', '11010519491231002X',
    '4111 1111 1111 1111', '-----BEGIN PRIVATE KEY-----\nsynthetic\n-----END PRIVATE KEY-----',
])
def test_redacts_supported_sensitive_patterns(text):
    assert REDACTED in redact_text(text) and text not in redact_text(text)


def test_preserves_business_counts_dates_and_nested_numeric_identifiers():
    value={'content':{'total':123,'items':[{'id':1234,'title':'2026-10-09 SEO关键词优化，排名12，咨询 a@example.com'}]}}
    result=redact(value)
    assert result['content']['total']==123 and result['content']['items'][0]['id']==1234
    assert '2026-10-09 SEO关键词优化，排名12' in result['content']['items'][0]['title']
    assert 'a@example.com' not in result['content']['items'][0]['title']
