from datetime import date, datetime
from types import SimpleNamespace

from app.geo.content.report_data import citation_match, citation_rows, normalize_report_url


def test_exact_normalization_and_loose_are_distinct():
    assert normalize_report_url('HTTPS://Example.COM:443/a/?utm_source=x#top') == 'https://example.com/a'
    assert citation_match('https://example.com/a', ['https://EXAMPLE.com:443/a/?spm=1#x'])[0] == 'exact'
    assert citation_match('https://example.com/a', ['https://example.com/a/section'])[0] == 'loose'
    assert citation_match('https://example.com/a', ['https://example.com/other'])[0] == 'loose'
    assert citation_match('https://example.com/a', [], 'See https://example.com/a')[0] == 'loose'
    assert citation_match('https://example.com/a', ['https://other.example/a'])[0] is None


def test_no_samples_never_fabricates_and_source_is_separate():
    pub = SimpleNamespace(id=1, task_id=2, channel='web', published_url='https://example.com/a', published_at=None)
    assert citation_rows([pub], [], date(2026, 9, 1), date(2026, 9, 2))[0]['matches'] == []
    real = SimpleNamespace(id=9, prompt_id=1, engine='E', captured_at=datetime(2026, 9, 1), sample_mode='openai_compat', patrol_run_id=1, simulated=False, note='', cited_urls=[pub.published_url], raw_text='')
    manual = SimpleNamespace(**{**vars(real), 'id': 10, 'sample_mode': 'manual'})
    got = citation_rows([pub], [real, manual], date(2026, 9, 1), date(2026, 9, 2))
    assert got[0]['exact_count'] == 1
    assert got[0]['matches'][0]['sample_id'] == 9
