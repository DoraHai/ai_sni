"""Native PostgreSQL row-lock/rollback tests; isolated loopback CI schema only."""
import asyncio
import os
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import select, text, func, update
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.schema import CreateTable
from starlette.requests import Request

from app.models import (Tenant, TenantModule, GeoProject, GeoOptimizationBusiness, GeoOptimizationUnit,
    GeoPrompt, GeoContentTask, GeoArticleVersion, GeoChannelVariant, GeoPublication,
    GeoPublishingChannel, GeoChannelAccount, User, Role)
from app.models.advisor_tenant_grant import AdvisorTenantGrant
from app.geo.content import distribution_report as s, distribution_protocol as p, routes

pytestmark = pytest.mark.skipif(not os.getenv('GEO_TEST_POSTGRES_URL'), reason='requires dedicated PostgreSQL; mandatory in GEO CI')


def test_pairing_claim_race_publication_race_rollback_and_scope():
    async def run():
        from ops.run_geo_checks import validate_ci_database
        url = os.environ['GEO_TEST_POSTGRES_URL']; validate_ci_database(url)
        schema = 'geo_report_' + uuid4().hex
        engine = create_async_engine(url, connect_args={'server_settings': {
            'search_path': schema, 'lock_timeout': '10000', 'statement_timeout': '15000'}},
            execution_options={'schema_translate_map': {'public': schema}})
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        created = False
        actor = {'kind': 'admin', 'user_id': 9, 'grant_id': None}
        try:
            async with engine.begin() as conn:
                await conn.execute(text(f'CREATE SCHEMA "{schema}"')); created = True
                for model in (Tenant, TenantModule, GeoProject, GeoOptimizationBusiness, GeoOptimizationUnit,
                    GeoPrompt, GeoContentTask, GeoArticleVersion, GeoChannelVariant, GeoPublication,
                    GeoPublishingChannel, GeoChannelAccount, User, Role, AdvisorTenantGrant):
                    await conn.execute(CreateTable(model.__table__, include_foreign_key_constraints=[]))
                await conn.execute(text('CREATE TABLE demo_tenant_bindings (tenant_id bigint, demo_tenant_id bigint, '
                    'dataset_key varchar(64), dataset_version varchar(40), status varchar(16), version integer)'))
            async with sessions() as db:
                book = p.registry({}); book['enabled'] = True; book['scopes']['5'] = {'enabled': True, 'revision': 1}
                db.add_all([Tenant(id=7, name='synthetic seven'), Tenant(id=8, name='synthetic eight'),
                    TenantModule(id=1, tenant_id=7, module_code='geo', status='active', module_settings={p.KEY: book, 'unrelated': {'limit': 20}}),
                    TenantModule(id=2, tenant_id=7, module_code='seo', status='active',
                        module_settings={p.KEY:{'devices':{'foreign-device':{'credential_hash':s.sha('z'*64)}}}}),
                    Role(id=1, name='synthetic admin', is_system=False, permissions={'settings.accounts': 'edit'}),
                    User(id=9, username='synthetic-operator', password_hash='unusable-synthetic-value', role_id=1, is_active=True),
                    GeoPublishingChannel(id=1, tenant_id=7, name='synthetic wechat', channel_type='wechat', enabled=True),
                    GeoChannelAccount(id=1, tenant_id=7, channel_id=1, display_name='synthetic manual account', auth_type='manual', status='active')])
                for project, business, prompt, task, variant in ((5,20,30,12,3), (6,21,31,14,4)):
                    db.add_all([
                        GeoProject(id=project, tenant_id=7, tenant_module_id=1, name='synthetic project',
                            primary_domain=f'p{project}.example.invalid', canonical_domain=f'p{project}.example.invalid',
                            status='active', project_settings={'geo_business_scope': {'revision': 1, 'business_ids': [business]}}),
                        GeoOptimizationBusiness(id=business, tenant_id=7, name='synthetic business'),
                        GeoOptimizationUnit(id=business, tenant_id=7, business_id=business, name='synthetic unit'),
                        GeoPrompt(id=prompt, tenant_id=7, unit_id=business, question='synthetic question'),
                        GeoContentTask(id=task, tenant_id=7, prompt_id=prompt, business_id=business, period_id=100,
                            title='synthetic content', status='ready', review_status='approved'),
                        GeoArticleVersion(id=task+100, task_id=task, title='synthetic article', body_markdown='synthetic body'),
                        GeoChannelVariant(id=variant, task_id=task, article_version_id=task+100, channel='wechat',
                            title='synthetic article', body_markdown='synthetic body', adapt_meta={}, status='draft')])
                await db.commit()
            async with sessions() as db:
                req = Request({'type':'http', 'method':'POST', 'path':p.PREFIX+'/device/exchange',
                    'query_string':b'', 'headers':[(b'authorization', ('Bearer '+'z'*64).encode())]})
                with pytest.raises(HTTPException) as denied:
                    await s.authenticate(db, req, reporting=True)
                assert denied.value.detail['code'] == 'DEVICE_CREDENTIAL_INVALID'
            async with sessions() as db:
                store = await s.open_store(db, 7)
                pair = await s.create_pairing(store, 5, actor,
                    {'label':'synthetic device', 'platform':'wechat-article', 'account_id':'1', 'expected_revision':0})
                await db.commit()
            async def claim():
                async with sessions() as db:
                    try:
                        value = await s.claim(db, {'pairing_code': pair['pairing_code'], 'request_id': str(uuid4())})
                        await db.commit(); return value
                    except HTTPException:
                        await db.rollback(); return None
            claims = await asyncio.gather(claim(), claim())
            assert sum(c is not None for c in claims) == 1
            credential = next(c for c in claims if c)['device']['credential']
            device_id = next(c for c in claims if c)['device']['id']
            with patch.object(routes, '_build_rule_input', AsyncMock(return_value=None)), \
                 patch.object(routes, '_brand_context_for_task', AsyncMock(return_value=('synthetic', []))), \
                 patch.object(routes, 'assert_can_publish'), patch.object(routes, '_sync_task_pipeline', AsyncMock()):
                async with sessions() as db:
                    store = await s.open_store(db, 7)
                    variant, article = await db.get(GeoChannelVariant, 3), await db.get(GeoArticleVersion, 112)
                    hash_value = p.content_digest(s.content_for(variant, article))
                    report = await s.create_task(store, 5, actor, {'content_task_id':12, 'variant_id':3, 'article_version_id':112,
                        'payload_hash':hash_value, 'device_id':device_id, 'request_id':'synthetic-task-request'})
                    await db.commit()
                async with sessions() as db:
                    store = await s.open_store(db, 7)
                    # Same tenant, different project; no global fallback.
                    with pytest.raises(HTTPException) as denied:
                        await s.native_task(store, 5, 14, 4, 114, publish=True)
                    assert denied.value.status_code == 404
                    await db.rollback()
                async def receive(*, fail_after_write=False):
                    async with sessions() as db:
                        try:
                            store = await s.open_store(db, 7)
                            device = store.book['devices'][device_id]
                            entry = store.book['tasks'][report['taskId']]
                            event = {**entry['target'], 'receiptId':'synthetic-receipt', 'sequence':3, 'contractVersion':1,
                                'deviceId':device_id, 'taskId':report['taskId'], 'status':'succeeded', 'code':'HUMAN_PUBLISHED',
                                'at':stamp, 'evidence':'human-reported', 'publicUrl':'https://mp.weixin.qq.com/s/synthetic'}
                            ack = await s.apply_events(store, device, [event], 'receipt')
                            await store.save()
                            if fail_after_write: raise RuntimeError('synthetic transaction interruption')
                            await db.commit(); return ack
                        except BaseException:
                            await db.rollback(); raise
                stamp = s.now_ms()
                with pytest.raises(RuntimeError): await receive(fail_after_write=True)
                async with sessions() as db:
                    assert await db.scalar(select(func.count()).select_from(GeoPublication)) == 0
                    module = await db.get(TenantModule, 1)
                    assert module.module_settings[p.KEY]['tasks'][report['taskId']]['events']['receipt'] == {}
                results = await asyncio.gather(receive(), receive())
                assert results[0] == results[1]
                async with sessions() as db:
                    assert await db.scalar(select(func.count()).select_from(GeoPublication)) == 1
                    module = await db.get(TenantModule, 1)
                    assert module.module_settings['unrelated'] == {'limit':20}
                    assert credential not in json_string(module.module_settings)
                    from app.geo.publication_monitor import state_for
                    pub = await db.scalar(select(GeoPublication))
                    assert state_for(await db.get(GeoChannelVariant, 3), pub)['state'] == 'pending'
                    # Disable the signing human: device authorization is immediately invalid.
                    (await db.get(User, 9)).is_active = False
                    await db.commit()
                async with sessions() as db:
                    store = await s.open_store(db, 7)
                    with pytest.raises(HTTPException) as denied: await s.actor_authorized(store, 5, actor)
                    assert denied.value.detail['code'] == 'ACTOR_AUTHORIZATION_REVOKED'
                # A stale ORM identity must not overwrite an unrelated JSON
                # namespace committed by another connection.
                async with sessions() as stale:
                    old = await stale.get(TenantModule, 1)
                    assert old.module_settings['unrelated'] == {'limit':20}
                    async with sessions() as fresh:
                        module = await fresh.get(TenantModule, 1, with_for_update=True)
                        module.module_settings = {**module.module_settings, 'unrelated':{'limit':21}}
                        await fresh.commit()
                    store = await s.open_store(stale, 7)
                    store.book['revision'] += 1
                    await store.save(); await stale.commit()
                async with sessions() as db:
                    module = await db.get(TenantModule, 1)
                    assert module.module_settings['unrelated'] == {'limit':21}
                    assert len(module.module_settings[p.KEY]['tasks'][report['taskId']]['events']['receipt']) == 1
                # Project-only pause writers cannot cross an admitted report's
                # project check. A committed pause is observed by the next check.
                async with sessions() as owner:
                    store = await s.open_store(owner, 7)
                    await s.selected_project(store, 5)
                    started = asyncio.Event()
                    async def pause_project():
                        async with sessions() as updater:
                            started.set()
                            await updater.execute(update(GeoProject).where(GeoProject.id == 5).values(status='paused'))
                            await updater.commit()
                    pending = asyncio.create_task(pause_project())
                    await started.wait(); await asyncio.sleep(0.05)
                    assert not pending.done()
                    await owner.rollback()
                    await pending
                async with sessions() as db:
                    store = await s.open_store(db, 7)
                    with pytest.raises(HTTPException) as denied: await s.selected_project(store, 5)
                    assert denied.value.detail['code'] == 'SCOPE_FORBIDDEN'
        finally:
            if created:
                async with engine.begin() as conn:
                    await conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
            await engine.dispose()
    asyncio.run(run())


def json_string(value):
    import json
    return json.dumps(value)
