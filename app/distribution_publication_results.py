"""Advisor checks and transactional native publication writebacks.

Device envelopes remain v1. No unverifiable receipt becomes native delivery.
"""
from __future__ import annotations

import importlib
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy.exc import SQLAlchemyError

from app import distribution_control as core
from app import distribution_scheduling as scheduling
from app.distribution_contract import ApprovedContent, PublicationMonitor, content_digest
from app.distribution_publication_verify import verify_publication


def result_adapter(module):
    try:
        return importlib.import_module('app.seo_distribution_results' if module == 'seo' else 'app.geo.distribution_results')
    except ImportError:
        raise core.problem('WRITEBACK_ADAPTER_UNAVAILABLE', 503) from None


def scope_of(task):
    return {k: task[k] for k in ('module', 'tenant_id', 'scope_id')}


def frozen_content(task):
    content = ApprovedContent.model_validate(task['content']).model_dump()
    if content['version'] != task['source_revision'] or content_digest(content) != task['content_digest']:
        raise core.problem('source_changed')
    return content


async def task_for_actor(db, actor, scope, task_id, *, locked=False):
    await core.authorize_scope(db, actor, scope)
    task = await core.one(db, 'SELECT * FROM distribution_tasks WHERE id=:id', id=task_id)
    if not task or any(task[k] != scope[k] for k in scope) or task['advisor_user_id'] != actor:
        raise core.problem('scope_forbidden', 403)
    if locked:
        await core.lock(db, 'device:' + task['device_id'])
        await core.lock(db, 'scope:' + core.canonical(scope))
        task = await core.one(db, 'SELECT * FROM distribution_tasks WHERE id=:id', id=task_id)
        await core.authorize_scope(db, actor, scope)
    return task


async def reported(db, task):
    if task['action'] != 'publish' or task['status'] != 'succeeded':
        raise core.problem('publication_not_confirmed')
    resolution = await core.one(db, 'SELECT * FROM distribution_task_resolutions WHERE task_id=:id ORDER BY id DESC LIMIT 1', id=task['id'])
    if resolution:
        if resolution['outcome'] != 'published':
            raise core.problem('publication_not_confirmed')
        url, at = resolution['public_url'], resolution['checked_at']
    else:
        receipt = task['receipt'] or {}
        if receipt.get('code') != 'HUMAN_PUBLISHED' or receipt.get('evidence') != 'human-reported':
            raise core.problem('publication_not_confirmed')
        url, at = receipt.get('publicUrl'), receipt.get('at')
    if not url or not isinstance(at, int) or at < 0:
        raise core.problem('publication_not_confirmed')
    return core.public_url(task['platform'], url), at


async def view(db, task_id):
    check = await core.one(db, 'SELECT id,task_id,actor_id,mode,public_url,reported_at,checked_at,status,code,verification '
                           'FROM distribution_publication_checks WHERE task_id=:id ORDER BY sequence DESC LIMIT 1', id=task_id)
    writeback = await core.one(db, 'SELECT event_id,state,attempts,updated_at,code,result FROM distribution_publication_writebacks WHERE task_id=:id', id=task_id)
    if check:
        check['id'], check['task_id'] = str(check['id']), str(check['task_id'])
    if writeback:
        writeback['event_id'] = str(writeback['event_id'])
    return {'check': check, 'writeback': writeback}


async def monitor_view(db, actor, scope, task_id):
    """Read current native observation for a server-owned publication identity.

    Initial writeback metadata stays immutable; reading never runs a worker or
    re-publishes. A failed native query cannot poison the caller's transaction.
    """
    task = await task_for_actor(db, actor, scope, task_id)
    entry = await core.one(db, 'SELECT state,result FROM distribution_publication_writebacks WHERE task_id=:id', id=task_id)
    if not entry or entry['state'] != 'written':
        raise core.problem('publication_not_registered')
    publication_id = (entry['result'] or {}).get('publication_id')
    if type(publication_id) is not int or publication_id <= 0:
        raise core.problem('publication_not_registered')
    value = {'module': task['module'], 'publication_id': publication_id,
             'basis': {'seo': 'page-capture', 'geo': 'public-text'}[task['module']],
             'state': 'unavailable', 'evidence_source': 'none', 'observed_at': None,
             'next_check_at': None, 'evidence_id': None, 'code': 'MONITOR_UNAVAILABLE'}
    try:
        async with db.begin_nested():
            reader = getattr(result_adapter(task['module']), 'publication_monitor_status', None)
            if not callable(reader):
                raise core.problem('MONITOR_NOT_INTEGRATED', 503)
            native = PublicationMonitor.model_validate(await reader(
                db, actor, task['tenant_id'], task['scope_id'], publication_id))
            if native.module != task['module'] or native.publication_id != publication_id:
                raise ValueError('Wrong native publication identity')
            value = native.model_dump()
    except HTTPException as exc:
        if exc.status_code in (401, 403):
            raise
    except (SQLAlchemyError, ImportError, OSError, AttributeError, KeyError, TypeError):
        pass
    except ValueError:
        value['code'] = 'MONITOR_CONTRACT_MISMATCH'
    return {'schema': 1, **scope, 'task_id': str(task_id), 'as_of': core.now_ms(), 'monitor': value}


async def prepare_check(db, actor, request):
    scope = request.model_dump(include={'module', 'tenant_id', 'scope_id'})
    task = await task_for_actor(db, actor, scope, request.task_id)
    fingerprint, prior = await scheduling.request_prior(db, actor, request)
    if prior:
        return None, fingerprint, prior
    url, at = await reported(db, task)
    if request.expected_public_url != url:
        raise core.problem('publication_link_changed')
    if at > core.now_ms():
        raise core.problem('publication_report_clock_ahead')
    content = frozen_content(task)
    binding = await core.one(db, 'SELECT external_account_id FROM distribution_bindings WHERE id=:id', id=task['binding_id'])
    if not binding:
        raise core.problem('binding_unavailable')
    return {'task': task, 'url': url, 'reported_at': at, 'content': content,
            'identity': binding['external_account_id']}, fingerprint, None


async def inspect(prepared, request):
    if request.mode == 'human':
        return {'status': 'verified', 'code': 'ADVISOR_CONFIRMED_PUBLIC_CONTENT', 'verification': 'human-verified'}
    return await verify_publication(prepared['task']['platform'], prepared['url'], prepared['content'], prepared['identity'])


def clean_native_result(value, payload, module):
    if (not isinstance(value, dict) or value.get('module') != module
        or type(value.get('publication_id')) is not int or value['publication_id'] <= 0
        or value.get('verification') != payload['verification'] or type(value.get('idempotent')) is not bool
        or not isinstance(value.get('monitor_state'), str) or not 1 <= len(value['monitor_state']) <= 40
        or not all(c.isalnum() or c in '_-' for c in value['monitor_state'])):
        raise core.problem('WRITEBACK_CONTRACT_MISMATCH', 503)
    result = {k: value[k] for k in ('module', 'publication_id', 'monitor_state', 'verification', 'idempotent')}
    if 'placement_id' in value:
        if type(value['placement_id']) is not int or value['placement_id'] <= 0:
            raise core.problem('WRITEBACK_CONTRACT_MISMATCH', 503)
        result['placement_id'] = value['placement_id']
    return result


async def apply_writeback(db, actor, task):
    entry = await core.one(db, 'SELECT * FROM distribution_publication_writebacks WHERE task_id=:id', id=task['id'])
    if not entry or entry['state'] == 'written':
        return
    # A changed/conflicting receipt must be reconciled before retrying a native
    # write. The originally checked URL and the frozen source cannot be changed.
    url, _at = await reported(db, task)
    if url != entry['payload']['public_url']:
        raise core.problem('publication_link_changed')
    payload = entry['payload']
    code, state, result = 'WRITEBACK_WRITTEN', 'written', None
    try:
        # A failed native insert is rolled back independently. Keep the public
        # check and its durable pending entry even if a module is unavailable.
        async with db.begin_nested():
            value = await result_adapter(task['module']).record_publication(
                db, actor, task['tenant_id'], task['scope_id'], task['variant_id'], payload)
            result = clean_native_result(value, payload, task['module'])
    except HTTPException as exc:
        detail = exc.detail if isinstance(exc.detail, dict) else {}
        candidate = detail.get('code', 'WRITEBACK_BLOCKED')
        code = candidate if isinstance(candidate, str) and candidate.isascii() and candidate.replace('_', '').isalnum() and len(candidate) <= 64 else 'WRITEBACK_BLOCKED'
        state = 'pending' if exc.status_code >= 500 else 'blocked'
    except (SQLAlchemyError, ImportError, OSError, AttributeError, KeyError, ValueError, TypeError):
        code, state = 'WRITEBACK_UNAVAILABLE', 'pending'
    await db.execute(core.text('UPDATE distribution_publication_writebacks SET state=:state,attempts=attempts+1,updated_at=:at,code=:code,result=CAST(:result AS jsonb) WHERE task_id=:id'),
                     {'state': state, 'at': core.now_ms(), 'code': code, 'result': core.canonical(result), 'id': task['id']})
    await core.audit(db, actor, 'publication_writeback', scope_of(task), code, task['id'])


async def finish_check(db, actor, request, prepared, observation):
    scope = request.model_dump(include={'module', 'tenant_id', 'scope_id'})
    task = await task_for_actor(db, actor, scope, request.task_id, locked=True)
    fingerprint, prior = await scheduling.request_prior(db, actor, request)
    if prior:
        return prior
    url, reported_at = await reported(db, task)
    if (url != prepared['url'] or reported_at != prepared['reported_at']
        or task['content_digest'] != prepared['task']['content_digest'] or task['source_revision'] != prepared['task']['source_revision']):
        raise core.problem('publication_link_changed')
    check_id, at = uuid4(), core.now_ms()
    await db.execute(core.text('INSERT INTO distribution_publication_checks '
        '(id,task_id,actor_id,mode,public_url,reported_at,checked_at,status,code,verification,observed_digest) '
        'VALUES(:id,:task,:actor,:mode,:url,:reported,:at,:status,:code,:verification,:digest)'),
        {'id': check_id, 'task': task['id'], 'actor': actor, 'mode': request.mode, 'url': url, 'reported': reported_at,
         'at': at, **observation, 'verification': observation.get('verification'), 'digest': observation.get('observed_digest')})
    await core.audit(db, actor, 'publication_checked', scope, observation['code'], task['id'])
    if observation['status'] == 'verified':
        payload = {'event_id': str(check_id), 'task_id': str(task['id']), 'source_revision': task['source_revision'],
                   'content_digest': task['content_digest'], 'platform': task['platform'], 'public_url': url,
                   'reported_at': reported_at, 'verification': observation['verification'], 'verified_at': at, 'verified_by': actor}
        await db.execute(core.text('INSERT INTO distribution_publication_writebacks '
            '(task_id,event_id,actor_id,payload,state,updated_at,code) VALUES(:task,:event,:actor,CAST(:payload AS jsonb),\'pending\',:at,\'WRITEBACK_PENDING\') '
            'ON CONFLICT(task_id) DO NOTHING'),
            {'task': task['id'], 'event': check_id, 'actor': actor, 'payload': core.canonical(payload), 'at': at})
        await apply_writeback(db, actor, task)
    result = {'schema': 1, **scope, 'task_id': str(task['id']), 'publication': await view(db, task['id'])}
    await scheduling.save_request(db, actor, request, fingerprint, result)
    return result


async def retry_writeback(db, actor, request):
    scope = request.model_dump(include={'module', 'tenant_id', 'scope_id'})
    task = await task_for_actor(db, actor, scope, request.task_id, locked=True)
    fingerprint, prior = await scheduling.request_prior(db, actor, request)
    if prior:
        return prior
    entry = await core.one(db, 'SELECT event_id FROM distribution_publication_writebacks WHERE task_id=:id', id=task['id'])
    if not entry:
        raise core.problem('publication_not_verified')
    if str(entry['event_id']) != str(request.event_id):
        raise core.problem('version_conflict')
    await reported(db, task)
    await apply_writeback(db, actor, task)
    result = {'schema': 1, **scope, 'task_id': str(task['id']), 'publication': await view(db, task['id'])}
    await scheduling.save_request(db, actor, request, fingerprint, result)
    return result
