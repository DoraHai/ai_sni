"""Pure QA rules. Unknown demand and unavailable observations stay unknown."""
import csv
import hashlib
import io
import re
import unicodedata
from datetime import datetime, timezone
from urllib.parse import urlsplit, urlunsplit
from bs4 import BeautifulSoup

PLATFORMS = [
    {'key': 'website', 'name': '官网 FAQ', 'mode': 'export', 'description': '导出审核稿，由网站发布后回填网址并核验'},
    {'key': 'zhihu', 'name': '知乎回答', 'mode': 'manual', 'description': '打开指定问题、复制审核稿，真人发布后回填回答网址'},
    {'key': 'baidu_zhidao', 'name': '百度知道', 'mode': 'manual', 'description': '打开指定问题、复制审核稿，真人发布后回填网址'},
    {'key': 'csdn_qa', 'name': 'CSDN 问答', 'mode': 'manual', 'description': '适用于技术问题，账号权限需在平台确认'},
]


def normalized(value):
    return ''.join(c for c in unicodedata.normalize('NFKC', value).casefold() if c.isalnum() or c in './%+-=')


def fingerprint(value):
    if not any(c.isalnum() for c in value):
        raise ValueError('问题必须包含文字或数字')
    # Preserve model separators, decimal points and arithmetic operators.
    # Only spacing and terminal question punctuation are formatting differences.
    key = re.sub(r'\s+', '', unicodedata.normalize('NFKC', value).casefold()).rstrip('?。')
    return hashlib.sha256(key.encode()).hexdigest()


def body_hash(value):
    return hashlib.sha256(value.encode()).hexdigest()


def public_url(value):
    from app.seo_backlink_sources import candidate_url
    return candidate_url(value)


def platform_url(platform, value, *, answer=False, question_url=None, domain=None):
    from app.seo_backlinks import belongs_to_site
    url = public_url(value)
    parsed = urlsplit(url)
    host = (parsed.hostname or '').lower()
    if platform == 'website':
        valid = bool(domain) and belongs_to_site(url, domain)
    elif platform == 'zhihu':
        valid = host in {'www.zhihu.com', 'zhihu.com'} and bool(re.fullmatch(r'/question/\d+' + (r'/answer/\d+' if answer else '') + r'/?', parsed.path))
        if answer and question_url:
            valid = valid and parsed.path.split('/')[2] == urlsplit(question_url).path.split('/')[2]
    elif platform == 'baidu_zhidao':
        valid = host == 'zhidao.baidu.com' and bool(re.fullmatch(r'/question/\d+\.html', parsed.path))
        if answer and question_url:
            valid = valid and parsed.path == urlsplit(question_url).path
    elif platform == 'csdn_qa':
        valid = host == 'ask.csdn.net' and bool(re.fullmatch(r'/questions/\d+/?', parsed.path))
        if answer and question_url:
            valid = valid and parsed.path.rstrip('/') == urlsplit(question_url).path.rstrip('/')
    else:
        valid = False
    if not valid:
        raise ValueError('网址必须属于所选平台和指定问题；官网网址必须属于当前网站')
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, '', parsed.fragment if answer else ''))


def parse_questions_csv(value):
    if len(value.encode()) > 500_000:
        raise ValueError('CSV 最大 500 KB')
    reader = csv.DictReader(io.StringIO(value.lstrip('\ufeff')))
    if not reader.fieldnames or 'title' not in reader.fieldnames:
        raise ValueError('CSV 必须有 title 列，可选 source_url、source_name、topic 列')
    items = []
    for line, row in enumerate(reader, 2):
        if len(items) >= 200:
            raise ValueError('一次最多导入 200 个问题')
        title = (row.get('title') or '').strip()
        if not title or len(title) > 300:
            raise ValueError(f'第 {line} 行问题为空或超过 300 字')
        items.append({'title': title, 'topic': (row.get('topic') or '未分类').strip(),
                      'source': {'kind': 'import', 'name': (row.get('source_name') or 'CSV 导入').strip(),
                                 'url': (row.get('source_url') or '').strip() or None}})
    if not items:
        raise ValueError('CSV 中没有问题')
    return items


def fact_is_current(fact, now=None):
    now = now or datetime.now(timezone.utc)
    expires = fact.expires_at
    if expires and expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    return fact.status == 'active' and (not expires or expires > now)


def answer_checks(body, snapshots):
    problems = []
    if not body.strip():
        problems.append('回答正文为空')
    if not snapshots:
        problems.append('尚未关联事实证据')
    refs = {int(x) for x in re.findall(r'\[F(\d+)\]', body)}
    known = {item['id'] for item in snapshots}
    if refs - known:
        problems.append('正文引用了未关联的事实编号')
    if known and not refs:
        problems.append('请在关键事实后使用 [F编号] 标记证据')
    if re.search(r'待补充|待核验|TODO|TBD', body, re.I):
        problems.append('正文仍有待补充或待核验内容')
    return problems


def observe_answer(result, body, expected_url):
    from app.seo_backlinks import page_evidence
    evidence = page_evidence(result)
    evidence['checked_at'] = datetime.now(timezone.utc).isoformat()
    if evidence['state'] != 'readable':
        return {**evidence, 'state': 'unavailable'}
    expected, actual = urlsplit(expected_url), urlsplit(result.final_url)
    if expected.hostname != actual.hostname or expected.path.rstrip('/') != actual.path.rstrip('/'):
        return {**evidence, 'state': 'unavailable', 'reason': 'redirected'}
    soup = BeautifulSoup(result.body, 'html.parser')
    for node in soup.select('script,style,template,noscript'):
        node.decompose()
    page = normalized(soup.get_text(' ', strip=True))
    # Require the entire normalized answer, preserving numeric punctuation.
    # Matching scattered snippets could otherwise identify unrelated answers.
    text = normalized(re.sub(r'\[F\d+\]', '', body))
    if len(text) < 12:
        return {**evidence, 'state': 'unavailable', 'reason': 'answer_too_short_to_identify'}
    found = text in page
    return {**evidence, 'state': 'content_observed' if found else 'not_observed',
            'reason': 'matching_answer_text' if found else 'text_not_found', 'body_hash': body_hash(body),
            'meaning': '公开页面正文匹配，不证明账号归属、平台审核结论或阅读量'}
