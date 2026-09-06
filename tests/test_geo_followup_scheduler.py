from types import SimpleNamespace as NS
from unittest.mock import Mock, patch
from pathlib import Path


def test_independent_geo_startup_registers_followups_without_duplicate_patrol():
    from app.geo.scheduler import start_geo_followup_scheduler
    scheduler=NS(running=False,add_job=Mock(),start=Mock())
    with patch('app.geo.scheduler.geo_scheduler',scheduler), patch('app.geo.scheduler._acquire_scheduler_lock',return_value=True):
        assert start_geo_followup_scheduler() is True
    assert [call.kwargs['id'] for call in scheduler.add_job.call_args_list]==['geo_publication_monitor','geo_outcome_reviews']
    scheduler.start.assert_called_once()
    assert 'start_geo_followup_scheduler()' in Path('app/geo_main.py').read_text(encoding='utf-8')
    assert 'start_geo_followup_scheduler' not in Path('app/main.py').read_text(encoding='utf-8')


def test_other_geo_worker_holds_lock_so_no_duplicate_jobs_start():
    from app.geo.scheduler import start_geo_followup_scheduler
    scheduler=NS(running=False,add_job=Mock(),start=Mock())
    with patch('app.geo.scheduler.geo_scheduler',scheduler), patch('app.geo.scheduler._acquire_scheduler_lock',return_value=False):
        assert start_geo_followup_scheduler() is False
    scheduler.add_job.assert_not_called()
    scheduler.start.assert_not_called()
