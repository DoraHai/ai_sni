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


def question_plan(items):
    """A reversible topic/intent view; lexical suggestions never merge records."""
    groups = {}
    for item in items:
        group = groups.setdefault(item['topic'], {'topic': item['topic'], 'intents': {}, 'question_count': 0,
            'unanswered_count': 0, 'reviewed_count': 0})
        group['question_count'] += 1
        group['unanswered_count'] += int(item['answer_count'] == 0)
        group['reviewed_count'] += int(item['reviewed_answer_count'] > 0)
        group['intents'].setdefault(item['intent'], []).append(item)
    tree = [{**group, 'intents': [{'intent': key, 'questions': rows} for key, rows in sorted(group['intents'].items())]}
            for group in sorted(groups.values(), key=lambda g: (-g['unanswered_count'], g['topic']))]

    def features(title):
        value = unicodedata.normalize('NFKC', title).casefold()
        identifiers = frozenset(re.findall(r'\d+(?:\.\d+)?|[a-z][a-z0-9./+-]*', value))
        value = re.sub(r'如何|怎么|怎样|什么|为什么|哪些|是否|请问', '', value)
        value = normalized(value)
        grams = {value[i:i+2] for i in range(len(value)-1)}
        return grams, identifiers

    prepared = [(item, *features(item['title'])) for item in items]
    suggestions = []
    for index, (left, a, left_ids) in enumerate(prepared):
        if len(a) < 4:
            continue
        for right, b, right_ids in prepared[index+1:]:
            if len(b) < 4 or left_ids != right_ids:
                continue
            score = 2 * len(a & b) / (len(a) + len(b))
            if score >= .65:
                suggestions.append({'left_id': left['id'], 'right_id': right['id'],
                    'left_title': left['title'], 'right_title': right['title'], 'overlap_pct': round(score*100),
                    'reason': '去除通用疑问词后，二字片段重合；请人工核对意图和适用条件'})
    suggestions.sort(key=lambda pair: (-pair['overlap_pct'], pair['left_id'], pair['right_id']))
    return {'groups': tree, 'similar_pairs': suggestions[:50], 'similar_pair_count': len(suggestions),
            'unanswered_count': sum(item['answer_count'] == 0 for item in items),
            'reviewed_count': sum(item['reviewed_answer_count'] > 0 for item in items)}


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


def placement_followup(answer_url, observations, *, now=None):
    """Read-only follow-up reasons; inaccessible pages never prove removal."""
    now = now or datetime.now(timezone.utc)
    reasons = []
    last = observations[-1] if observations else {}
    checked_at = last.get('checked_at')
    try:
        checked = datetime.fromisoformat(checked_at.replace('Z', '+00:00'))
        if checked.tzinfo is None:
            checked = checked.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError, AttributeError):
        checked = None
    if not answer_url:
        reasons.append('待回填回答网址')
    elif not last:
        reasons.append('网址已回填，待首次核验')
    else:
        state = last.get('state')
        if state == 'unavailable':
            reasons.append('页面暂时无法核验，不代表回答已删除')
        elif state == 'not_observed':
            was_observed = any(o.get('state') == 'content_observed' for o in observations[:-1])
            reasons.append('此前正文匹配，本次未匹配，请复查' if was_observed else '未匹配到审核正文，请核对网址或正文')
        elif state != 'content_observed':
            reasons.append('核验状态未知，请复查')
        if checked is None or (now - checked).total_seconds() >= 7 * 86400:
            reasons.append('距上次核验已满 7 天或核验时间未知，建议复查')
        link_history = [o for o in observations if (o.get('backlink_discovery') or {}).get('state') not in {None, 'not_checked'}]
        current = (link_history[-1].get('backlink_discovery') or {}) if link_history else {}
        if current.get('state') in {'unavailable', 'blocked', 'unreachable'}:
            reasons.append('外链暂时无法核验，请稍后复查')
        if current.get('state') == 'readable':
            previous = next((o.get('backlink_discovery') for o in reversed(link_history[:-1])
                if (o.get('backlink_discovery') or {}).get('state') == 'readable'), None)
            if previous is not None:
                # Compare targets, not counts: one link may replace another.
                before = {x.get('target_url') for x in previous.get('links', []) if x.get('target_url')}
                after = {x.get('target_url') for x in current.get('links', []) if x.get('target_url')}
                if before != after:
                    reasons.append(f'页面官网链接发生变化：新增 {len(after-before)} 条，未再发现 {len(before-after)} 条')
    return {'needed': bool(reasons), 'reasons': reasons, 'last_checked_at': checked_at}


def validated_semantic_pairs(raw, questions):
    """Do not accept invented references or silently coerce model output."""
    if not isinstance(raw, dict) or not isinstance(raw.get('pairs'), list) or len(raw['pairs']) > 30:
        raise ValueError('Invalid semantic result')
    known = {q['id']:q for q in questions}
    seen, pairs = set(), []
    for pair in raw['pairs']:
        if not isinstance(pair, dict):
            raise ValueError('Invalid semantic pair')
        left, right, reason = pair.get('left_id'), pair.get('right_id'), pair.get('reason')
        if type(left) is not int or type(right) is not int or left == right or left not in known or right not in known:
            raise ValueError('Invalid question references')
        if not isinstance(reason, str) or not reason.strip() or len(reason) > 500:
            raise ValueError('Invalid semantic reason')
        key = tuple(sorted((left, right)))
        if key in seen:
            continue
        seen.add(key)
        pairs.append({'left_id':left,'right_id':right,'left_title':known[left]['title'],
                      'right_title':known[right]['title'],'reason':reason.strip()})
    return pairs
