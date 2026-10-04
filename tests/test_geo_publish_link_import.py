from io import BytesIO
import asyncio
from types import SimpleNamespace

from openpyxl import Workbook

from app.geo.content.publication_import import MAX_BYTES, parse_rows, validate_rows


def test_csv_and_paste_preview_validates_scope_duplicates_urls_and_dates():
    text = ('task_id,channel,url,published_at\n'
            '1,website,https://example.com/a,2026-09-01 10:00:00\n'
            '1,website,https://example.com/a,\n'
            '2,website,https://example.com/b,\n'
            '9,website,https://example.com/c,\n'
            '1,website,javascript:bad,\n'
            '1,website,https://example.com/d,bad-date\n')
    tasks = [SimpleNamespace(id=1, title='A', business_id=4), SimpleNamespace(id=2, title='B', business_id=5)]
    pubs = []
    rows = validate_rows(parse_rows(pasted=text), tasks, pubs, business_id=4)
    assert rows[0]['status'] == '有效'
    assert rows[0]['published_at'].startswith('2026-09-01')
    assert '发布链接重复' in rows[1]['errors']
    assert '任务不属于当前项目' in rows[2]['errors']
    assert '任务不存在' in rows[3]['errors'][0]
    assert 'http(s)' in rows[4]['errors'][0]
    assert '发布时间格式无效' in rows[5]['errors'][0]


def test_xlsx_and_title_resolution_and_limits():
    wb = Workbook()
    ws = wb.active
    ws.append(['任务标题', '平台', '发布链接'])
    ws.append(['题目', 'website', 'https://example.com/a'])
    output = BytesIO()
    wb.save(output)
    rows = parse_rows(filename='links.xlsx', content=output.getvalue())
    checked = validate_rows(rows, [SimpleNamespace(id=3, title='题目', business_id=1)], [])
    assert checked[0]['task_id'] == 3
    assert checked[0]['status'] == '有效'
    try:
        parse_rows(pasted='task_id,channel,url\n' + '1,x,https://a.cn\n' * 501)
    except ValueError as exc:
        assert '500' in str(exc)
    else:
        assert False, 'row limit must be enforced'
    try:
        parse_rows(filename='links.csv', content=b'x' * (MAX_BYTES + 1))
    except ValueError as exc:
        assert '2 MB' in str(exc)
    else:
        assert False, 'file size limit must be enforced'
    bad = validate_rows([{'task_id': '3', 'channel': 'website', 'url': 'https://example.com/' + 'x' * 2000,
                          'published_at': '', 'row_number': 2}], [SimpleNamespace(id=3, title='题目', business_id=1)], [])
    assert '2000' in bad[0]['errors'][0]


def test_confirm_revalidates_then_calls_existing_publication_backfill(monkeypatch):
    from app.geo.content import report_routes, routes
    calls = []
    task = SimpleNamespace(id=1, title='题目', prompt_id=8, business_id=4)
    variant = SimpleNamespace(channel='website')
    async def tasks_pubs(*args): return [task], [], {8: '问题'}
    async def entitlement(*args): return None
    async def get_task(*args): return task
    async def variants(*args): return [variant]
    async def channels(*args): return []
    async def write(*args, **kwargs): calls.append(kwargs['published_url'])
    class Session:
        async def scalar(self, statement): return SimpleNamespace(id=4, tenant_id=1)
        async def commit(self): pass
        async def rollback(self): pass
    monkeypatch.setattr(report_routes, '_tasks_pubs', tasks_pubs)
    monkeypatch.setattr(report_routes, 'ensure_geo_entitlement', entitlement)
    monkeypatch.setattr(routes, '_get_task', get_task)
    monkeypatch.setattr(routes, '_variants', variants)
    monkeypatch.setattr(routes, '_ensure_default_publishing_channels', channels)
    monkeypatch.setattr(routes, '_write_publication', write)
    req = report_routes.ImportConfirm(tenant_id=1, business_id=4, rows=[
        {'task_id': 1, 'channel': 'website', 'url': 'https://example.com/a', 'published_at': ''},
        {'task_id': 9, 'channel': 'website', 'url': 'https://example.com/b', 'published_at': ''},
    ])
    result = asyncio.run(report_routes.confirm_publication_links(req, ctx=SimpleNamespace(ensure_tenant=lambda _: None), session=Session()))
    assert result['applied_count'] == 1 and calls == ['https://example.com/a']
