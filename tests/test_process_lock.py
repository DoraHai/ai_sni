import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("BAIDU_APP_ID", "test-app")
os.environ.setdefault("BAIDU_SECRET_KEY", "test-secret")
os.environ.setdefault("BAIDU_DEFAULT_USERNAME", "test-user")
os.environ.setdefault("BAIDU_DEFAULT_UCID", "1")
os.environ.setdefault("BAIDU_SELF_ACCESS_TOKEN", "test-token")
os.environ.setdefault("BAIDU_SELF_TOKEN_EXPIRES_AT", "2099-01-01T00:00:00")
os.environ.setdefault("CRYPTO_MASTER_KEY_B64", "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=")
os.environ.setdefault("ADMIN_API_KEY", "test-admin-key")

from app.process_lock import (
    _lock_unix,
    _lock_windows,
    _unlock_unix,
    _unlock_windows,
    acquire_file_lock,
    release_file_lock,
)
from app.scheduler import start_scheduler


class ProcessLockBackendTests(unittest.TestCase):
    def test_real_lock_is_exclusive_until_released(self):
        with tempfile.TemporaryDirectory() as directory:
            lock_path = os.path.join(directory, "scheduler.lock")
            first_handle = acquire_file_lock(lock_path)
            self.assertIsNotNone(first_handle)
            self.assertIsNone(acquire_file_lock(lock_path))

            release_file_lock(first_handle)
            self.assertTrue(os.path.exists(lock_path))

            next_handle = acquire_file_lock(lock_path)
            self.assertIsNotNone(next_handle)
            release_file_lock(next_handle)

    def test_unix_lock_is_exclusive_and_non_blocking(self):
        file_handle = MagicMock()
        backend = SimpleNamespace(LOCK_EX=2, LOCK_NB=4, LOCK_UN=8, flock=MagicMock())

        _lock_unix(file_handle, backend)
        _unlock_unix(file_handle, backend)

        self.assertEqual(
            backend.flock.call_args_list,
            [
                call(file_handle, backend.LOCK_EX | backend.LOCK_NB),
                call(file_handle, backend.LOCK_UN),
            ],
        )

    def test_windows_lock_is_exclusive_and_non_blocking(self):
        file_handle = MagicMock()
        file_handle.fileno.return_value = 17
        backend = SimpleNamespace(LK_NBLCK=2, LK_UNLCK=3, locking=MagicMock())

        _lock_windows(file_handle, backend)
        _unlock_windows(file_handle, backend)

        self.assertEqual(
            backend.locking.call_args_list,
            [call(17, backend.LK_NBLCK, 1), call(17, backend.LK_UNLCK, 1)],
        )
        self.assertEqual(file_handle.seek.call_args_list, [call(0), call(0)])

    def test_failed_non_blocking_acquire_closes_handle(self):
        file_handle = MagicMock()
        file_handle.tell.return_value = 1
        with (
            patch("app.process_lock.open", return_value=file_handle),
            patch("app.process_lock._lock_file", side_effect=OSError("busy")),
        ):
            self.assertIsNone(acquire_file_lock("scheduler.lock"))

        file_handle.close.assert_called_once_with()

    def test_release_closes_handle_after_unlock_error(self):
        file_handle = MagicMock()
        with patch(
            "app.process_lock._unlock_file", side_effect=OSError("unlock failed")
        ):
            with self.assertRaisesRegex(OSError, "unlock failed"):
                release_file_lock(file_handle)

        file_handle.close.assert_called_once_with()


class SchedulerLockTests(unittest.TestCase):
    def test_lock_contention_does_not_start_duplicate_scheduler(self):
        with (
            patch("app.scheduler._acquire_scheduler_lock", return_value=False),
            patch("app.scheduler.scheduler.add_job") as add_job,
            patch("app.scheduler.scheduler.start") as scheduler_start,
        ):
            start_scheduler()

        add_job.assert_not_called()
        scheduler_start.assert_not_called()

    def test_start_exception_releases_scheduler_lock(self):
        with (
            patch("app.scheduler._acquire_scheduler_lock", return_value=True),
            patch("app.scheduler.scheduler.add_job", side_effect=RuntimeError("boom")),
            patch("app.scheduler._release_scheduler_lock") as release_lock,
        ):
            with self.assertRaisesRegex(RuntimeError, "boom"):
                start_scheduler()

        release_lock.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
