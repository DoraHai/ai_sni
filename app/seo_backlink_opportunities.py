"""Bounded index comparisons. An absent sample is not proof of absent links."""
from urllib.parse import urlparse

from app.seo_backlink_sources import candidate_url


def competitor_domains(values, own_domain):
    domains = []
    own = urlparse(candidate_url('https://' + own_domain)).hostname.removeprefix('www.')
    for value in values:
        value = value.strip()
        parsed = urlparse(candidate_url(value if '://' in value else 'https://' + value))
        if parsed.path not in {'', '/'} or parsed.query or parsed.fragment or parsed.port:
            raise ValueError('竞品请填写域名，不要填写文章路径、端口或查询参数')
        host = parsed.hostname.removeprefix('www.')
        if host == own or host.endswith('.' + own) or own.endswith('.' + host):
            raise ValueError('竞品不能是当前网站或其父域、子域')
        if host not in domains:
            domains.append(host)
    if not 1 <= len(domains) <= 3:
        raise ValueError('每次分析需要 1–3 个不同竞品域名')
    return domains


def compare_samples(own_domain, samples, known_sources=()):
    own = samples.get(own_domain)
    if not own or own.get('state') != 'completed':
        return {'items': [], 'comparison_available': False,
                'message': '我方索引查询未完成，不能判断差距；已有竞品结果保留供下次查看。'}
    own_hosts = {urlparse(item['source_url']).hostname for item in own['items']}
    own_hosts.update(urlparse(url).hostname for url in known_sources)
    groups = {}
    for domain, sample in samples.items():
        if domain == own_domain or sample.get('state') != 'completed':
            continue
        for item in sample['items']:
            host = urlparse(item['source_url']).hostname
            if host in own_hosts or host == own_domain or host.endswith('.' + own_domain):
                continue
            group = groups.setdefault(host, {'source_domain': host, 'competitors': set(), 'evidence': []})
            group['competitors'].add(domain)
            evidence = {**item, 'competitor': domain}
            if evidence not in group['evidence']:
                group['evidence'].append(evidence)
    items = [{**group, 'competitors': sorted(group['competitors']),
              'competitor_count': len(group['competitors']), 'state': 'candidate',
              'reason': '竞品索引出现该来源，我方索引样本及已核实资产未出现；需要人工评估合作价值'}
             for group in groups.values()]
    items.sort(key=lambda item: (-item['competitor_count'], item['source_domain']))
    return {'items': items, 'comparison_available': True,
            'message': '每站最多 100 条、每来源域名一条的索引样本；未出现不代表全网不存在。机会未计入我方外链。'}
