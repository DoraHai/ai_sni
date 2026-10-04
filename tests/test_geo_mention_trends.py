from datetime import date, datetime
from types import SimpleNamespace

from app.geo.content.report_data import trend_rows


def snap(id, captured_at, mentioned, mode='openai_compat'):
    return SimpleNamespace(id=id, prompt_id=1, engine='E', captured_at=captured_at,
                           mentions_brand=mentioned, sample_mode=mode, patrol_run_id=1 if mode == 'openai_compat' else None, simulated=False, note='')


def test_shanghai_day_iso_week_month_and_summed_denominator():
    samples = [snap(1, datetime(2025, 12, 28, 17), True),
               snap(2, datetime(2025, 12, 29, 1), False),
               snap(3, datetime(2026, 1, 1, 0), False)]
    prompts = {1: SimpleNamespace(is_brand_probe=False)}
    start, end = date(2025, 12, 29), date(2026, 1, 2)
    daily = trend_rows(samples, prompts, start, end, 'day')
    assert daily[0]['samples'] == 2 and daily[0]['rate'] == .5
    assert daily[-1]['rate'] is None
    weekly = trend_rows(samples, prompts, start, end, 'week')
    assert weekly[0]['bucket'] == '2026-W01'
    assert weekly[0]['mentions'] == 1 and weekly[0]['samples'] == 3
    assert weekly[0]['rate'] == 1 / 3
    monthly = trend_rows(samples, prompts, start, end, 'month')
    assert [(r['bucket'], r['samples']) for r in monthly] == [('2025-12', 2), ('2026-01', 1)]


def test_manual_simulated_unknown_do_not_enter_default_real_rate():
    samples = [snap(1, datetime(2026, 9, 1), True), snap(2, datetime(2026, 9, 1), False, 'manual'),
               SimpleNamespace(**{**vars(snap(3, datetime(2026, 9, 1), False)), 'simulated': True})]
    prompts = {1: SimpleNamespace(is_brand_probe=False)}
    day = date(2026, 9, 1)
    assert trend_rows(samples, prompts, day, day, 'day')[0]['rate'] == 1
    assert trend_rows(samples, prompts, day, day, 'day', 'manual')[0]['rate'] == 0
    assert trend_rows(samples, prompts, day, day, 'day', 'simulated')[0]['samples'] == 1
    unverified = snap(4, datetime(2026, 9, 1), True)
    unverified.patrol_run_id = None
    assert trend_rows([unverified], prompts, day, day, 'day')[0]['rate'] is None
    assert trend_rows([unverified], prompts, day, day, 'day', 'unknown')[0]['samples'] == 1
