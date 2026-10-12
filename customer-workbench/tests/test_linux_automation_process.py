"""An actual killed owner releases Linux flock; the supervisor can take over.

Scheduler callbacks are captured, not run. There is no database or provider call.
"""
import asyncio
import os
import signal
import sys
import time
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

pytestmark=pytest.mark.skipif(sys.platform!='linux',reason='requires real Linux flock')


class ChildOwner:
    def __init__(self,pid,ready,hold):
        self.pid=pid;self.ready=ready;self.hold=hold;self.status=None

    def poll(self):
        if self.status is not None:return self.status
        found,status=os.waitpid(self.pid,os.WNOHANG)
        if found:self.status=status
        return self.status

    def kill(self):os.kill(self.pid,signal.SIGKILL)

    def wait(self,timeout):
        deadline=time.monotonic()+timeout
        while self.poll() is None:
            if time.monotonic()>deadline:raise AssertionError('owner did not exit')
            time.sleep(0.02)


def owner(path):
    # Fork an already imported worker. This tests a real OS process without
    # confusing slow emulator cold imports with flock acquisition behavior.
    from app.geo import scheduler
    ready_read,ready_write=os.pipe();hold_read,hold_write=os.pipe()
    pid=os.fork()
    if pid==0:
        try:
            os.close(ready_read);os.close(hold_write)
            scheduler._LOCK_PATH=str(path)
            assert scheduler._acquire_scheduler_lock()
            os.write(ready_write,b'owned\n');os.read(hold_read,1)
        finally:os._exit(0)
    os.close(ready_write);os.close(hold_read)
    child=ChildOwner(pid,ready_read,hold_write)
    import select
    if not select.select([ready_read],[],[],15)[0]:
        cleanup(child)
        raise AssertionError('owner failed to start within deadline')
    if os.read(ready_read,6)!=b'owned\n':
        cleanup(child);raise AssertionError('owner did not acquire the lock')
    return child


def cleanup(child):
    if child.poll() is None:child.kill();child.wait(timeout=5)
    os.close(child.ready);os.close(child.hold)


def test_killed_real_owner_releases_lock_without_unlock_call(tmp_path):
    from app.geo import scheduler
    child=owner(tmp_path/'crash.lock')
    try:
        with patch.object(scheduler,'_LOCK_PATH',str(tmp_path/'crash.lock')):
            assert scheduler._acquire_scheduler_lock() is False
            child.kill();child.wait(timeout=5)
            assert scheduler._acquire_scheduler_lock() is True
            scheduler._release_scheduler_lock()
    finally:cleanup(child)


def test_real_standby_supervisor_acquires_after_owner_crash_once(tmp_path):
    from app.geo import scheduler
    child=owner(tmp_path/'standby.lock')
    fake=SimpleNamespace(running=False,add_job=Mock(),start=Mock())
    state=[]
    async def checkpoint(seconds):
        state.append(scheduler.followup_scheduler_runtime_status()['state'])
        if len(state)==1:
            assert fake.add_job.call_count==0
            child.kill();child.wait(timeout=5)
        else:raise asyncio.CancelledError()
    try:
        with patch.object(scheduler,'_LOCK_PATH',str(tmp_path/'standby.lock')), \
             patch.object(scheduler,'geo_scheduler',fake),patch('asyncio.sleep',checkpoint):
            with pytest.raises(asyncio.CancelledError):asyncio.run(scheduler.supervise_geo_followups())
            assert state==['standby','active']
            assert [call.kwargs['id'] for call in fake.add_job.call_args_list]==['geo_publication_monitor','geo_outcome_reviews']
            fake.start.assert_called_once()
    finally:
        scheduler._release_scheduler_lock();cleanup(child)
