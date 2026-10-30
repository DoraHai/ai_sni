"""Explicitly injected private OSS bucket adapter; no SDK import or configuration.

The caller supplies an authenticated SDK bucket with bounded connection/read
timeouts. Suggested constructor configuration names are SEM_ATTACHMENT_OSS_*
(bucket, endpoint, region and role); this module never reads the environment.
No application wiring, bucket administration, public URLs or delete operations.
"""
import hashlib
import re
import time

from app.sem_phase0.screenshots import MAX_IMAGE_BYTES
from app.sem_phase0.store import AttachmentUnavailable

CONNECT_TIMEOUT_SECONDS = 3
IO_TIMEOUT_SECONDS = 10
OPERATION_BUDGET_SECONDS = 20
ATTACHMENT_BATCH_BUDGET_SECONDS = 60
REQUEST_BUDGET_SECONDS = 90
MAX_ATTEMPTS = 3
BACKOFF_SECONDS = (.3, 1.)
_KEY = re.compile(r'sem-sources/[1-9][0-9]*/[1-9][0-9]*/[\w-]{1,80}/[1-9][0-9]*/[1-9][0-9]*-([0-9a-f]{64})')


class OSSPrivateAttachmentStore:
    """Wrap a preconfigured OSS SDK bucket (put_object/get_object interface).

    SDK socket timeouts are NOT a total deadline. Deployment must supply a
    deadline-bounded transport/worker; these finite retries only bound attempts.
    This unmounted adapter does not silently construct a network client.
    """
    def __init__(self, bucket, *, clock=time.monotonic, sleep=time.sleep):
        self.bucket, self.clock, self.sleep = bucket, clock, sleep

    @staticmethod
    def _key(key):
        if not isinstance(key, str) or _KEY.fullmatch(key) is None:
            raise AttachmentUnavailable()
        return _KEY.fullmatch(key).group(1)

    def _read_once(self, key, max_bytes):
        response = self.bucket.get_object(key)
        try:
            # Bound every stream read, including a hostile/oversized object.
            chunks, size = [], 0
            while size < max_bytes:
                chunk = response.read(min(65536, max_bytes - size))
                if not chunk:
                    break
                if not isinstance(chunk, bytes) or len(chunk) > max_bytes - size:
                    raise AttachmentUnavailable()
                chunks.append(chunk)
                size += len(chunk)
            return b''.join(chunks)
        finally:
            response.close()

    @staticmethod
    def _transient(exc):
        return isinstance(exc, (TimeoutError, ConnectionError)) or getattr(exc, 'status', None) in (408, 429, 500, 502, 503, 504)

    def _pause(self, attempt, started):
        delay = BACKOFF_SECONDS[attempt]
        if self.clock() - started + delay >= OPERATION_BUDGET_SECONDS:
            raise AttachmentUnavailable()
        self.sleep(delay)

    def read(self, key, max_bytes):
        self._key(key)
        if type(max_bytes) is not int or not 0 < max_bytes <= MAX_IMAGE_BYTES + 1:
            raise AttachmentUnavailable()
        started = self.clock()
        for attempt in range(MAX_ATTEMPTS):
            try:
                data = self._read_once(key, max_bytes)
                if self.clock() - started >= OPERATION_BUDGET_SECONDS:
                    raise AttachmentUnavailable()
                return data
            except Exception as exc:
                if attempt == MAX_ATTEMPTS - 1 or not self._transient(exc):
                    raise AttachmentUnavailable() from None
                self._pause(attempt, started)

    def put_if_absent(self, key, data, sha256):
        expected = self._key(key)
        if (not isinstance(data, bytes) or not 0 < len(data) <= MAX_IMAGE_BYTES
                or sha256 != expected or hashlib.sha256(data).hexdigest() != expected):
            raise AttachmentUnavailable()
        started = self.clock()
        for attempt in range(MAX_ATTEMPTS):
            retry = False
            try:
                self.bucket.put_object(key, data, headers={
                    'x-oss-forbid-overwrite': 'true',
                    'x-oss-object-acl': 'private',
                    'x-oss-server-side-encryption': 'AES256',
                    'Content-Type': 'application/octet-stream',
                })
            except Exception as exc:
                # 409 may mean a prior identical write. Ambiguous transient
                # failures also get a byte read-back before another condition PUT.
                if getattr(exc, 'status', None) not in (409, 412) and not self._transient(exc):
                    raise AttachmentUnavailable() from None
                retry = self._transient(exc)
            try:
                stored = self._read_once(key, MAX_IMAGE_BYTES + 1)
            except Exception as exc:
                if not (retry and getattr(exc, 'status', None) == 404):
                    raise AttachmentUnavailable() from None
            else:
                if (len(stored) != len(data) or hashlib.sha256(stored).hexdigest() != expected
                        or self.clock() - started >= OPERATION_BUDGET_SECONDS):
                    raise AttachmentUnavailable()
                return
            if attempt == MAX_ATTEMPTS - 1:
                raise AttachmentUnavailable()
            self._pause(attempt, started)
