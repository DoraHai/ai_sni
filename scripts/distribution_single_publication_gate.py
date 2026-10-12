"""Default-deny, one-publication fence for the owned Linux acceptance factory.

This is an extra admission check, never a replacement for native auth, reviewed
source, running-project, scheduling, receipt or publication verification gates.
No configuration is written and no grant is minted here.
"""
from __future__ import annotations

import json
import hashlib
import os
from pathlib import Path
import re
import stat
import sys
import time
from typing import Annotated, Literal
from uuid import UUID

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError, model_validator

WORK = Path('/opt/gsnipers-distribution-acceptance/work/distribution-server-pilot-20261012')
FILE = 'single-publication-seo.json'
MAX_BYTES = 8192
MAX_WINDOW_MS = 30 * 60 * 1000
PREFIX = '/api/distribution/v1'
NATIVE_PUBLICATIONS = '/api/v1/seo/content-distribution/publications'
DEVICE = '0c764dd4-ebc0-45e9-912e-d46f7a42fc05'
BINDING = 'a68a1fb9-af29-4b31-bb08-2f5d43bda3e5'
ACCOUNT = 'acceptance-seo-gh-1864ed0c0506'
EXTERNAL_ACCOUNT = 'gh_1864ed0c0506'
SCOPE = {'module': 'seo', 'tenant_id': 15, 'scope_id': 6}


class Permit(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    schema_version: Literal[1] = Field(alias='schema')
    purpose: Literal['isolated-single-seo-publication']
    module: Literal['seo']
    tenant_id: Literal[15]
    scope_id: Literal[6]
    actor_id: Literal[100007]
    device_id: Literal[DEVICE]
    binding_id: Literal[BINDING]
    account_id: Literal[ACCOUNT]
    external_account_id: Literal[EXTERNAL_ACCOUNT]
    platform: Literal['wechat-article']
    content_id: Annotated[int, Field(gt=0)]
    variant_id: Annotated[int, Field(gt=0)]
    source_revision: Annotated[str, StringConstraints(pattern=r'^[A-Za-z0-9_-]{1,100}$')]
    expected_digest: Annotated[str, StringConstraints(pattern=r'^[a-f0-9]{64}$')]
    request_id: Annotated[UUID, Field(strict=False)]
    issued_at: Annotated[int, Field(ge=946684800000, le=4102444800000)]
    expires_at: Annotated[int, Field(ge=946684800000, le=4102444800000)]
    expires_in_seconds: Annotated[int, Field(ge=300, le=900)]
    task_id: Annotated[UUID | None, Field(strict=False)]

    @model_validator(mode='before')
    @classmethod
    def integer_literals(cls, values):
        if not isinstance(values, dict) or any(type(values.get(key)) is not int for key in (
            'schema', 'tenant_id', 'scope_id', 'actor_id')):
            raise ValueError('Integer identity fields required')
        return values

    def task_request(self):
        return {**SCOPE, 'variant_id': self.variant_id, 'binding_id': self.binding_id,
                'source_revision': self.source_revision, 'expected_digest': self.expected_digest,
                'action': 'publish', 'confirm_reviewed_content': True,
                'confirm_manual_publication': True, 'expires_in_seconds': self.expires_in_seconds,
                'request_id': str(self.request_id)}


def denied():
    return HTTPException(403, 'Acceptance single publication not authorized')


def now_ms():
    return time.time_ns() // 1_000_000


def unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError('Duplicate field')
        value[key] = item
    return value


def invalid_constant(_):
    raise ValueError('Non-JSON number')


def parse_permit(data: bytes, at: int) -> Permit:
    """Pure contract validation; errors never include the private file contents."""
    try:
        if not 1 <= len(data) <= MAX_BYTES:
            raise ValueError()
        permit = Permit.model_validate(json.loads(data.decode('utf-8'), object_pairs_hook=unique_object,
                                                  parse_constant=invalid_constant))
        if not permit.issued_at <= at < permit.expires_at or not 0 < permit.expires_at - permit.issued_at <= MAX_WINDOW_MS:
            raise ValueError()
        return permit
    except (ValueError, TypeError, UnicodeError, ValidationError):
        raise denied() from None


def read_permit(root: Path, config: dict, module: str) -> Permit:
    """Only the fixed private Linux WORK, no symlink or special-file reads."""
    try:
        if (sys.platform != 'linux' or module != 'seo' or root != WORK or root.resolve() != WORK
            or config.get('root') != str(WORK) or config.get('platform') != 'linux-acceptance'
            or config.get('production') is not False
            or config.get('ports') != {'pg': 55483, 'seo': 55861, 'geo': 55862}
            or Path.cwd() != WORK or (WORK / '.env').exists()):
            raise ValueError()
        for directory in (root, *root.parents):
            if stat.S_ISLNK(directory.lstat().st_mode):
                raise ValueError()
        directory = root.stat()
        if directory.st_uid != os.getuid() or stat.S_IMODE(directory.st_mode) & 0o077:
            raise ValueError()
        path = root / FILE
        before = path.lstat()
        if not stat.S_ISREG(before.st_mode):
            raise ValueError()
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(descriptor, 'rb') as source:
            current = os.fstat(source.fileno())
            if (not stat.S_ISREG(current.st_mode) or current.st_uid != os.getuid()
                or stat.S_IMODE(current.st_mode) & 0o077 or current.st_nlink != 1
                or (before.st_dev, before.st_ino) != (current.st_dev, current.st_ino)
                or not 1 <= current.st_size <= MAX_BYTES):
                raise ValueError()
            data = source.read(MAX_BYTES + 1)
        return parse_permit(data, now_ms())
    except (OSError, ValueError, AttributeError):
        raise denied() from None


def publication_request(request, payload=None):
    """Recognize protected paths conservatively, including redirect spellings."""
    path = request.url.path
    return (any(part in path for part in ('/publication-', '/publications', '/push'))
            or request.method == 'POST' and path.rstrip('/').endswith('/tasks')
            and isinstance(payload, dict) and payload.get('action') == 'publish')


async def request_payload(request):
    """Publication JSON is tiny, no unknown-length body buffering or duplicates."""
    length = request.headers.get('content-length', '')
    if not length.isdecimal() or not 1 <= int(length) <= MAX_BYTES:
        raise denied()
    data = await request.body()
    try:
        if len(data) != int(length):
            raise ValueError()
        value = json.loads(data.decode('utf-8'), object_pairs_hook=unique_object, parse_constant=invalid_constant)
        if not isinstance(value, dict):
            raise ValueError()
        return value
    except (ValueError, UnicodeError):
        raise denied() from None


def exactly(left, right):
    # Python True==1 and 15.0==15 must not bypass strict wire matching.
    return json.dumps(left, sort_keys=True, separators=(',', ':'), allow_nan=False) == json.dumps(
        right, sort_keys=True, separators=(',', ':'), allow_nan=False)


def route_parameters(request, permit, payload):
    """Allowlist exact methods/paths/queries before touching a database."""
    path = request.url.path
    try:
        if request.scope.get('raw_path', path.encode()) != path.encode('ascii'):
            raise denied()
    except UnicodeError:
        raise denied() from None
    query = list(request.query_params.multi_items())
    if len({key for key, _ in query}) != len(query):
        raise denied()
    values = dict(query)
    if request.method == 'POST' and path == PREFIX + '/tasks':
        if values or not exactly(payload, permit.task_request()) or now_ms() + permit.expires_in_seconds * 1000 > permit.expires_at:
            raise denied()
        return 'create'
    if request.method == 'GET' and path == NATIVE_PUBLICATIONS:
        if values != {'tenant_id': '15', 'site_id': '6', 'content_id': str(permit.content_id)}:
            raise denied()
        return 'delivery'
    if permit.task_id is None:
        raise denied()
    scope_query = {key: str(value) for key, value in SCOPE.items()}
    if request.method == 'GET' and path in {PREFIX + '/publication-source', PREFIX + '/publication-monitor'}:
        if values != {**scope_query, 'task_id': str(permit.task_id)}:
            raise denied()
        return 'read'
    asset = re.fullmatch(re.escape(PREFIX) + r'/publication-assets/([a-f0-9-]{36})/([A-Za-z0-9_-]{1,100})', path)
    if request.method == 'GET' and asset:
        if asset[1] != str(permit.task_id) or values != scope_query:
            raise denied()
        return 'read'
    if request.method == 'POST' and path in {PREFIX + '/publication-check', PREFIX + '/publication-writeback'}:
        if (values or not isinstance(payload, dict) or not exactly({k: payload.get(k) for k in SCOPE}, SCOPE)
            or payload.get('task_id') != str(permit.task_id)):
            raise denied()
        # The original Pydantic contracts still check URL/check boxes/event IDs.
        return 'write'
    raise denied()


def assert_binding(permit, binding, route):
    expected = {**SCOPE, 'device_id': permit.device_id, 'account_id': permit.account_id,
                'external_account_id': permit.external_account_id, 'platform': permit.platform}
    if not binding or any(binding.get(key) != value for key, value in expected.items()):
        raise denied()
    if route != 'delivery' and not (binding['active'] and binding['device_active']):
        raise denied()
    return expected


def assert_source(permit, source):
    if not source or (source['content_asset_id'], source['tenant_id'], source['site_id']) != (permit.content_id, 15, 6):
        raise denied()


def assert_task(permit, task, expected):
    # external_account_id lives in the current binding, not distribution_tasks.
    target = {**{k: expected[k] for k in ('module', 'tenant_id', 'scope_id', 'device_id', 'account_id', 'platform')},
              'variant_id': permit.variant_id, 'source_revision': permit.source_revision,
              'content_digest': permit.expected_digest, 'advisor_user_id': permit.actor_id, 'action': 'publish'}
    fingerprint = hashlib.sha256(json.dumps(permit.task_request(), ensure_ascii=False, sort_keys=True,
                                            separators=(',', ':'), allow_nan=False).encode()).hexdigest()
    if (any(str(task.get(k)) != str(v) for k, v in target.items())
        or str(task['binding_id']) != permit.binding_id or str(task['request_id']) != str(permit.request_id)
        or task['request_fingerprint'] != fingerprint
        or not task['grant_id'] or not task['publication_grant_id'] or not task['lease_id']
        or task['grant_id'] == task['publication_grant_id']
        or permit.task_id and str(task['id']) != str(permit.task_id)):
        raise denied()


async def authorize(request, root, config, sessions, module, payload=None):
    """Current JWT/database identity plus exact account/source/task metadata.

    These reads cannot grant execution: the original route repeats native auth
    and source gates and creates the two distinct grants transactionally.
    """
    permit = read_permit(root, config, module)
    route = route_parameters(request, permit, payload)
    from fastapi.security import HTTPAuthorizationCredentials
    from app.security.auth import require_auth
    from app import distribution_control as core
    from app.api.distribution import named
    header = request.headers.get('authorization', '')
    if not header.startswith('Bearer '):
        raise denied()
    async with sessions() as db:
        url = db.bind.url
        if (url.drivername, url.host, url.port, url.username, url.database) != (
            'postgresql+asyncpg', '127.0.0.1', 55483, 'distribution_acceptance', 'distribution_acceptance_seo') or url.query:
            raise denied()
        if (await core.one(db, 'SELECT current_schema() AS name'))['name'] != 'acceptance_seo':
            raise denied()
        ctx = await require_auth(bearer=HTTPAuthorizationCredentials(scheme='Bearer', credentials=header[7:]),
                                 header_key=None, key=None, session=db)
        fresh = await named(db, ctx)
        if route == 'delivery' and fresh.user_id != permit.actor_id:
            if fresh.tenant_id != permit.tenant_id or not fresh.can_view('seo.content'):
                raise denied()
        else:
            if fresh.user_id != permit.actor_id:
                raise denied()
            await core.authorize_scope(db, fresh.user_id, SCOPE)
        binding = await core.one(db, 'SELECT b.*,d.active AS device_active FROM distribution_bindings b '
                                'JOIN distribution_devices d ON d.id=b.device_id WHERE b.id=:id', id=permit.binding_id)
        expected = assert_binding(permit, binding, route)
        source = await core.one(db, 'SELECT v.content_asset_id,c.tenant_id,c.site_id FROM seo_distribution_variants v '
                               'JOIN seo_content_assets c ON c.id=v.content_asset_id WHERE v.id=:id AND v.tenant_id=:tenant',
                               id=permit.variant_id, tenant=permit.tenant_id)
        assert_source(permit, source)
        task = None
        if permit.task_id:
            task = await core.one(db, 'SELECT * FROM distribution_tasks WHERE id=:id', id=permit.task_id)
        elif route == 'create':
            task = await core.one(db, 'SELECT * FROM distribution_tasks WHERE advisor_user_id=:actor AND request_id=:request',
                                  actor=permit.actor_id, request=permit.request_id)
        if permit.task_id and not task:
            raise denied()
        if task:
            assert_task(permit, task, expected)
        if now_ms() >= permit.expires_at:
            raise denied()
