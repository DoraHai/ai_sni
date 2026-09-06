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
    assert 'supervise_geo_followups()' in Path('app/geo_main.py').read_text(encoding='utf-8')
    assert 'start_geo_followup_scheduler' not in Path('app/main.py').read_text(encoding='utf-8')


def test_other_geo_worker_holds_lock_so_no_duplicate_jobs_start():
    from app.geo.scheduler import start_geo_followup_scheduler
    scheduler=NS(running=False,add_job=Mock(),start=Mock())
    with patch('app.geo.scheduler.geo_scheduler',scheduler), patch('app.geo.scheduler._acquire_scheduler_lock',return_value=False):
        assert start_geo_followup_scheduler() is False
    scheduler.add_job.assert_not_called()
    scheduler.start.assert_not_called()


def test_startup_failure_releases_ownership_for_retry():
    import pytest
    from app.geo.scheduler import start_geo_followup_scheduler
    scheduler=NS(running=False,add_job=Mock(),start=Mock(side_effect=RuntimeError('startup')))
    with patch('app.geo.scheduler.geo_scheduler',scheduler), patch('app.geo.scheduler._acquire_scheduler_lock',return_value=True), \
         patch('app.geo.scheduler._release_scheduler_lock') as release:
        with pytest.raises(RuntimeError):start_geo_followup_scheduler()
    release.assert_called_once()


def test_standby_retries_without_starting_duplicate_patrol():
    import asyncio
    import pytest
    from unittest.mock import AsyncMock
    from app.geo.scheduler import supervise_geo_followups
    with patch('app.geo.scheduler.start_geo_followup_scheduler',side_effect=[False,True]) as start, \
         patch('asyncio.sleep',AsyncMock(side_effect=[None,asyncio.CancelledError])) as sleep:
        with pytest.raises(asyncio.CancelledError):asyncio.run(supervise_geo_followups())
    assert start.call_count==2 and sleep.await_count==2


def test_startup_catches_up_without_waiting_until_next_day():
    from app.geo.scheduler import start_geo_followup_scheduler
    scheduler=NS(running=False,add_job=Mock(),start=Mock())
    with patch('app.geo.scheduler.geo_scheduler',scheduler),patch('app.geo.scheduler._acquire_scheduler_lock',return_value=True):
        start_geo_followup_scheduler()
    assert all(call.kwargs.get('next_run_time') is not None for call in scheduler.add_job.call_args_list)


def test_os_releases_lock_when_owner_process_exits(tmp_path):
    import os,sys,subprocess,pytest
    if os.name=='nt':pytest.skip('production uses Linux flock')
    from app.geo.scheduler import _acquire_scheduler_lock,_release_scheduler_lock
    path=str(tmp_path/'owner.lock')
    child=subprocess.Popen([sys.executable,'-c',"import fcntl,sys; f=open(sys.argv[1],'w'); fcntl.flock(f,fcntl.LOCK_EX); print('locked',flush=True); sys.stdin.read()",path],
                           stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True)
    try:
        assert child.stdout.readline().strip()=='locked'
        with patch('app.geo.scheduler._LOCK_PATH',path):
            assert _acquire_scheduler_lock() is False
            child.terminate();child.wait(timeout=5)
            assert _acquire_scheduler_lock() is True
            _release_scheduler_lock()
    finally:
        if child.poll() is None:child.terminate();child.wait(timeout=5)
        child.stdin.close();child.stdout.close()
