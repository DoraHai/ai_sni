"""Human-only ledger annotations; synthetic authority and immutable-device regressions."""
import asyncio
import copy
import json
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.geo.content import distribution_protocol as p, distribution_report as s, distribution_routes as r
from app.security.auth import AuthContext, _required
from app.security.advisor_scope import AdvisorScope
from app.security import geo_distribution_advisor as guard


def fixture():
    store = s.Store(NS(flush=AsyncMock(), commit=AsyncMock()), 7,
        NS(module_settings={'unrelated': {'kept': True}}), p.registry({}))
    task = {'wire': {'id': 'task-1', 'leaseId': 'lease-1'},
        'target': {'contentVersion': 'v1', 'contentDigest': 'a' * 64},
        'native_task_id': 12, 'variant_id': 3, 'article_id': 112, 'scope_id': 5,
        'outcome': 'succeeded', 'last_code': 'HUMAN_PUBLISHED', 'publication_id': None,
        'reportedAccount': {'name': '合成上报公众号'},
        'events': {'receipt': {'receipt-1': {'digest': 'immutable-digest', 'ack': {'sequence': 3}}}, 'observation': {}}}
    store.book['tasks']['task-1'] = task
    variant = NS(adapt_meta={p.KEY: {'taskId': 'newer-task', 'reportedAccount': {'name': '更新任务上报'}}})
    native = AsyncMock(return_value=(NS(), variant, NS()))
    return store, task, variant, native


ACTOR = {'kind': 'admin', 'user_id': 9, 'grant_id': None}


def test_annotation_clear_audit_and_legacy_device_projection_stay_independent():
    async def run():
        store, task, variant, native = fixture()
        before = copy.deepcopy(task)
        variant_before = copy.deepcopy(variant.adapt_meta)
        device_before = await s.verification(store, task)
        with patch.object(s, 'actor_authorized', AsyncMock()) as authority, patch.object(s, 'native_task', native):
            result = await s.change_publish_account(store, 5, 'task-1', ACTOR,
                {'name': ' 合成\u200b号\u3000  编辑😀 ', 'expected_revision': 0})
            authority.assert_awaited_once_with(store, 5, ACTOR)
            assert result['advisorAccount']['name'] == '合成号 编辑😀'
            assert result['advisorAccount']['actor'] == ACTOR
            assert isinstance(result['advisorAccount']['at'], int)
            assert result['revision'] == 1
            persisted = p.registry(store.row.module_settings)
            assert persisted['tasks']['task-1']['advisorAccount'] == result['advisorAccount']
            assert store.row.module_settings['unrelated'] == {'kept': True}
            audit = store.book['audit'][-1]
            assert audit['code'] == 'PUBLISH_ACCOUNT_UPDATED' and audit['actor_id'] == 9
            assert audit['task_id'] == 'task-1' and audit['before'] is None
            assert audit['after'] == result['advisorAccount'] and isinstance(audit['at'], int)
            assert await s.verification(store, task) == device_before
            assert task['reportedAccount'] == before['reportedAccount'] and task['events'] == before['events']
            assert variant.adapt_meta == variant_before
            assert 'advisorAccount' not in s.task_projection(task)
            annotated = copy.deepcopy(task['advisorAccount'])
            cleared = await s.change_publish_account(store, 5, 'task-1', ACTOR,
                {'name': None, 'expected_revision': 1})
            assert cleared['revision'] == 2 and 'advisorAccount' not in cleared
            assert task == before
            assert await s.verification(store, task) == device_before
            assert store.book['audit'][-1]['before'] == annotated and store.book['audit'][-1]['after'] is None
            assert len(store.book['audit']) == 2
            assert variant.adapt_meta == variant_before
    asyncio.run(run())


@pytest.mark.parametrize('name', ['x' * 60, '😀' * 60, ' <img> 合成号 ', ' 甲\t乙\u2028  丙\u200b '])
def test_name_cleaning_matches_reported_account_and_counts_codepoints(name):
    async def run():
        store, task, _, native = fixture()
        expected = p.reported_account({'reportedAccount': {'name': name}, 'code': 'HUMAN_PUBLISHED', 'status': 'succeeded'})
        with patch.object(s, 'actor_authorized', AsyncMock()), patch.object(s, 'native_task', native):
            result = await s.change_publish_account(store, 5, 'task-1', ACTOR, {'name': name, 'expected_revision': 0})
        assert result['advisorAccount']['name'] == expected['name']
    asyncio.run(run())


@pytest.mark.parametrize('name', ['', ' \u200b\t ', 'x' * 61, '😀' * 61, 12, {}, []])
def test_invalid_name_never_mutates_ledger(name):
    async def run():
        store, _, _, native = fixture(); before = copy.deepcopy(store.book)
        with patch.object(s, 'actor_authorized', AsyncMock()), patch.object(s, 'native_task', native):
            with pytest.raises(HTTPException) as denied:
                await s.change_publish_account(store, 5, 'task-1', ACTOR, {'name': name, 'expected_revision': 0})
        assert denied.value.status_code == 422 and store.book == before
        store.session.flush.assert_not_awaited()
    asyncio.run(run())


@pytest.mark.parametrize('body', [{'name': '合成'}, {'name': '合成', 'expected_revision': True},
    {'name': '合成', 'expected_revision': -1}, {'name': '合成', 'expected_revision': 0, 'tenant_id': 7}])
def test_exact_body_and_integer_revision(body):
    async def run():
        store, _, _, _ = fixture()
        with pytest.raises(HTTPException) as denied:
            await s.change_publish_account(store, 5, 'task-1', ACTOR, body)
        assert denied.value.status_code == 422 and store.book['revision'] == 0
    asyncio.run(run())


def test_revision_conflict_and_foreign_project_do_not_write():
    async def run():
        for scope, revision, code in [(5, 1, 'SOURCE_CHANGED'), (6, 0, 'TASK_NOT_FOUND')]:
            store, _, _, native = fixture(); before = copy.deepcopy(store.book)
            with patch.object(s, 'actor_authorized', AsyncMock()), patch.object(s, 'native_task', native):
                with pytest.raises(HTTPException) as denied:
                    await s.change_publish_account(store, scope, 'task-1', ACTOR,
                        {'name': '合成顾问号', 'expected_revision': revision})
            assert denied.value.detail['code'] == code and store.book == before
            store.session.flush.assert_not_awaited()
    asyncio.run(run())


def test_revoked_authority_and_native_ownership_denial_are_fail_closed():
    async def run():
        for denied_guard in ('actor_authorized', 'native_task'):
            store, _, _, native = fixture(); before = copy.deepcopy(store.book)
            with patch.object(s, 'actor_authorized', AsyncMock()), patch.object(s, 'native_task', native), \
                 patch.object(s, denied_guard, AsyncMock(side_effect=HTTPException(403))):
                with pytest.raises(HTTPException):
                    await s.change_publish_account(store, 5, 'task-1', ACTOR, {'name': None, 'expected_revision': 0})
            assert store.book == before
            store.session.flush.assert_not_awaited()
    asyncio.run(run())


def request(data=None):
    req = Request({'type': 'http', 'method': 'POST', 'path': p.PREFIX + '/tasks/task-1/publish-account',
        'query_string': b'tenant_id=7&project_id=5', 'headers': [], 'path_params': {'taskId': 'task-1'}})
    req._body = json.dumps(data or {'name': '合成编辑号', 'expected_revision': 0}).encode()
    return req


def test_exact_advisor_rule_rechecks_task_scope_before_commit_without_rechecking_old_revision():
    async def run():
        rule = guard.RULES[('POST', p.PREFIX + '/tasks/{taskId}/publish-account')]
        assert rule.fields == frozenset({'name', 'expected_revision'})
        store, _, _, native = fixture()
        # Commit checks see revision after the handler's increment; they must
        # recheck fresh authority/objects, not reject their own prior revision.
        store.book['revision'] = 1
        ctx = NS(ensure_tenant=lambda _: None)
        with patch.object(s, 'management_store', AsyncMock(return_value=store)) as management, patch.object(s, 'native_task', native):
            await guard.check_objects(NS(), ctx, request(), {'name': '合成', 'expected_revision': 0}, rule)
            management.assert_awaited_once_with(management.call_args.args[0], ctx, 7, 5, write=True)
            native.assert_awaited_once()
            with pytest.raises(HTTPException):
                await guard.check_objects(NS(), ctx, request(), {'name': '合成', 'expected_revision': 0, 'extra': True}, rule)
        req = request(); req.scope['route'] = NS(path=rule.template)
        assert guard.match(req) == rule
        req.scope['method'] = 'PATCH'; assert guard.match(req) is None
        req.scope['method'] = 'POST'; req.scope['route'] = NS(path=rule.template + '/extra')
        assert guard.match(req) is None
        assert _required(p.PREFIX + '/tasks/task-1/publish-account', 'POST') == ({'geo.content', 'settings.accounts'}, True)
    asyncio.run(run())


def test_management_route_commits_and_returns_current_revision():
    async def run():
        store, _, _, native = fixture()
        ctx = AuthContext(9, 'synthetic-admin', '管理员', None, {'settings.accounts': 'edit'})
        with patch.object(s, 'management_store', AsyncMock(return_value=store)) as managed, \
             patch.object(s, 'actor_authorized', AsyncMock()), patch.object(s, 'native_task', native):
            result = await r.publish_account('task-1', request(), ctx, store.session)
            assert json.loads(result.body)['revision'] == 1
            assert managed.call_args.kwargs == {'write': True}
            store.session.commit.assert_awaited_once()
            read = await r.task_status('task-1', request(), ctx, store.session)
            assert json.loads(read.body)['advisorAccount']['name'] == '合成编辑号'
            assert json.loads(read.body)['revision'] == 1
    asyncio.run(run())


def test_readonly_and_ungranted_customer_are_rejected_by_existing_management_gate():
    async def run():
        readonly = AuthContext(11, 'synthetic-reader', '只读', 7, {'geo.content': 'view'})
        store, _, _, _ = fixture()
        with patch.object(s, 'open_store', AsyncMock(return_value=store)), patch.object(s, 'selected_project', AsyncMock()):
            with pytest.raises(HTTPException):
                await s.management_store(NS(), readonly, 7, 5, write=True)
        advisor = AuthContext(10, 'synthetic-advisor', '顾问', 7, {'geo.content': 'edit', 'geo.assets': 'edit'},
            advisor_scope=AdvisorScope(frozenset({7}), 7, 1))
        with patch.object(s, 'open_store', AsyncMock()) as opened:
            with pytest.raises(HTTPException):
                await s.management_store(NS(), advisor, 8, 5, write=True)
            opened.assert_not_awaited()
    asyncio.run(run())
