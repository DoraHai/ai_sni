"""Synthetic SQLite HTTP fixtures: no server, real account or external database."""
import asyncio
from copy import deepcopy
from datetime import date, datetime, timedelta
import json
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock, patch

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import MetaData, create_engine, event, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.geo import project_client_store as store
from app.geo import project_client_view as view
from app.geo.project_client_protocol import CLIENT_TEMPLATES, ROUTES, decode_cursor, encode_cursor, safe_url
from app.geo.project_read_routes import router
from app.models import (GeoProject, GeoOptimizationBusiness as Business, GeoOptimizationUnit as Unit,
    GeoPrompt as Prompt, GeoAnswerSnapshot as Answer, GeoVisibilityPatrolRun as Run,
    GeoPublishingChannel as Channel, GeoContentTask as Task, GeoArticleVersion as Article,
    GeoChannelVariant as Variant, GeoPublication as Publication)
from app.security.auth import AuthContext, require_scoped_auth
from app.security.advisor_scope import AdvisorScope

NOW = datetime(2026, 10, 14, 5)
WEEK = '2026-10-19'


@compiles(JSONB, 'sqlite')
def sqlite_jsonb(element, compiler, **kw):
    return 'JSON'


class SelectOnly:
    """Real SQL evaluation, with no ORM mutation APIs exposed to the endpoint."""
    def __init__(self, session):
        self.session = session

    async def scalars(self, statement):
        assert statement.is_select
        return self.session.scalars(statement)

    async def scalar(self, statement):
        assert statement.is_select
        return self.session.scalar(statement)


@pytest.fixture
def env(monkeypatch):
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    models = (GeoProject, Business, Unit, Prompt, Answer, Run, Channel, Task, Article, Variant, Publication)
    from app.database import Base
    metadata = MetaData()
    for table in Base.metadata.tables.values():
        table.to_metadata(metadata)
    # Exercise the contract's defensive legacy-null path without changing models.
    metadata.tables[Answer.__tablename__].c.captured_at.nullable = True
    for model in models:
        metadata.tables[model.__tablename__].create(engine)
    session = Session(engine, expire_on_commit=False, autoflush=False)
    for pid, tid, bid in ((1, 101, 11), (2, 101, 22), (3, 202, 33), (4, 101, None)):
        session.add(GeoProject(id=pid, tenant_id=tid, tenant_module_id=tid, name=f'Project {pid}',
            primary_domain=f'p{pid}.example.com', canonical_domain=f'p{pid}.example.com',
            status='active', project_settings={'geo_business_scope': {'revision': 1, 'business_ids': [bid] if bid else []}}))
        if bid:
            session.add(Business(id=bid, tenant_id=tid, name=f'Business {bid}', profile={'private': 'SYNTHETIC_PRIVATE'}))
            session.add(Unit(id=bid, tenant_id=tid, business_id=bid, name=f'Unit {bid}'))
    for qid, tid, uid in ((1, 101, 11), (2, 101, 11), (3, 101, 11), (4, 101, 22),
                           (5, 202, 33), (6, 101, None), (7, 202, 11)):
        session.add(Prompt(id=qid, tenant_id=tid, unit_id=uid, question=f'Question {qid}',
                           demand_note='SYNTHETIC_PRIVATE', is_brand_probe=False))
    for qid, tid in ((1, 101), (2, 101), (3, 101), (4, 101), (5, 202)):
        session.add(Task(id=qid, tenant_id=tid, prompt_id=qid, business_id=None, title=f'Task {qid}',
            status='ready', pipeline_step='adapt', review_status='approved', reviewed_at=NOW,
            brief={'private': 'SYNTHETIC_PRIVATE'}, review_note='SYNTHETIC_PRIVATE',
            created_at=NOW, updated_at=NOW))
        session.add(Article(id=qid, task_id=qid, version_no=1, kind='master', title=f'Master {qid}',
            body_markdown=f'Full master {qid}', created_at=NOW-timedelta(days=1), generation_meta={'private': 'SYNTHETIC_PRIVATE'}))
        session.add(Variant(id=qid, task_id=qid, article_version_id=qid, title=f'Variant {qid}',
            channel='website', body_markdown=f'Full variant {qid}', created_at=NOW, updated_at=NOW,
            adapt_meta={'push_deliveries': {f'private-key-{qid}': {'state': 'succeeded', 'article_id': qid,
                'account_id': 77, 'updated_at': '2026-10-14T05:00:00Z', 'result': 'SYNTHETIC_PRIVATE'}}}))
        session.add(Publication(id=qid, variant_id=qid, channel='website', publish_mode='manual_export',
            status='published', published_url=f'https://p{1 if qid < 4 else qid-2}.example.com/post/{qid}',
            published_at=NOW, updated_at=NOW))
    # A conflicting task, cross-task variant and orphan prompt must never enter A–L.
    session.add(Task(id=6, tenant_id=101, prompt_id=1, business_id=22, title='Conflicting task'))
    session.add(Task(id=7, tenant_id=101, prompt_id=6, business_id=11, title='Orphan task'))
    session.add(Variant(id=6, task_id=1, article_version_id=4, title='Foreign article', channel='website', body_markdown='PRIVATE'))
    for cid, domain in ((1, 'p1.example.com'), (2, 'docs.p1.example.com'), (3, 'p2.example.com'), (4, 'evil-p1.example.com')):
        session.add(Channel(id=cid, tenant_id=101, name=f'Channel {cid}', channel_type='website',
                            base_url=f'https://{domain}', enabled=True))
    session.commit()
    ctx = AuthContext(9, 'synthetic-reader', 'customer', 101, {'geo.assets': 'view', 'geo.content': 'view'})
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[require_scoped_auth] = lambda: ctx
    app.dependency_overrides[store.client_read_session] = lambda: SelectOnly(session)
    monkeypatch.setattr(store, 'ensure_geo_entitlement', AsyncMock(return_value=NS(is_demo=False)))
    async def module_check(session, context, tid, code):
        context.ensure_tenant(tid)
        return NS(id=tid)
    monkeypatch.setattr(store, 'ensure_module_access', module_check)
    statements = []
    def guard(conn, cursor, statement, parameters, context, executemany):
        assert statement.lstrip().upper().startswith('SELECT'), 'write attempted by GET'
        statements.append(statement)
    event.listen(engine, 'before_cursor_execute', guard)
    value = NS(http=TestClient(app), session=session, ctx=ctx, statements=statements,
               engine=engine, guard=guard, monkeypatch=monkeypatch)
    def save(*objects):
        event.remove(engine, 'before_cursor_execute', guard)
        try:
            session.add_all(objects)
            session.commit()
        finally:
            event.listen(engine, 'before_cursor_execute', guard)
    value.save = save
    yield value
    session.close()
    engine.dispose()


def get(env, suffix, *, project=1, tenant=101, **query):
    if suffix.split('/')[1] in {'overview', 'visibility', 'questions', 'answers'}:
        query.setdefault('week_end', WEEK)
    return env.http.get(f'/api/v1/geo/projects/{project}/client{suffix}', params={'tenant_id': tenant, **query})


def add_answers(env, count=8, *, previous=False, simulated=False, mention=True, engines=2, questions=3):
    rows, cells = [], []
    offset = 100 if previous else 0
    captured = NOW - timedelta(days=7 if previous else 0)
    run_id = 100 if previous else 99
    for i in range(count):
        row = Answer(id=offset+i+1, tenant_id=101, prompt_id=i % questions+1, engine=f'e{i % engines}',
            captured_at=captured, sample_mode='mock_persona' if simulated else 'openai_compat', simulated=simulated,
            note='method=unprimed_json_v2 analysis=completed', citation_accuracy='unknown', raw_text='Saved answer',
            mentions_brand=mention, competitors=[], cited_urls=[], patrol_run_id=run_id)
        rows.append(row)
        cells.append({'snapshot_id': row.id, 'prompt_id': row.prompt_id, 'engine': row.engine,
            'prompt_question': f'Historical {row.prompt_id}', 'provider': 'provider', 'model': 'model',
            'ok': True, 'sample_mode': row.sample_mode, 'simulated': simulated, 'sampling_method': 'unprimed_json_v2',
            'analysis_status': 'completed', 'raw_text': row.raw_text, 'suggested_mentions_brand': mention, 'competitors': []})
    env.save(*rows, Run(id=run_id, tenant_id=101, status='completed', started_at=captured-timedelta(hours=1),
                       finished_at=captured+timedelta(hours=1), items=cells))
    return rows


def all_paths(project=1):
    return ['/overview', '/visibility', '/questions', '/questions/1', '/answers', '/answers/1',
            '/content', '/content/1', '/content/1/variants', '/content/1/variants/1', '/content/1/articles/1', '/deliveries']


def test_all_twelve_routes_are_get_only_and_mounted_in_projects():
    from app.geo.project_routes import geo_projects_router
    for routes in (router.routes, [r for r in geo_projects_router.routes if r.path in CLIENT_TEMPLATES]):
        assert len(routes) == 12
        assert {r.path for r in routes} == CLIENT_TEMPLATES
        assert all(r.methods == {'GET'} for r in routes)


def test_all_gets_are_scoped_allowlisted_and_have_no_write_side_effects(env):
    add_answers(env)
    before = {m.__name__: [dict(r) for r in env.session.execute(select(m.__table__)).mappings()]
              for m in (Task, Article, Variant, Publication, Answer, Run)}
    for suffix in all_paths():
        response = get(env, suffix)
        assert response.status_code == 200, (suffix, response.text)
        body = response.json()
        assert set(body) == {'schema_version', 'tenant_id', 'project_id', 'evaluated_at', 'read_only', 'scope', 'basis', 'data'}
        assert body['tenant_id'] == 101 and body['project_id'] == 1 and body['read_only']
        assert body['scope']['question_count'] == 3
        assert 'SYNTHETIC_PRIVATE' not in response.text
        assert 'private-key-' not in response.text
        for forbidden in ('account_id', 'delivery_key', 'recovery_history', 'generation_meta', 'adapt_meta', 'body_html', 'reviewed_by'):
            assert f'"{forbidden}"' not in response.text
    after = {m.__name__: [dict(r) for r in env.session.execute(select(m.__table__)).mappings()]
             for m in (Task, Article, Variant, Publication, Answer, Run)}
    assert before == after
    assert not env.session.new and not env.session.dirty and not env.session.deleted
    assert env.statements and all('geo_channel_accounts' not in s for s in env.statements)


@pytest.mark.parametrize('suffix', all_paths())
def test_cross_tenant_and_other_project_details_never_leak(env, suffix):
    add_answers(env)
    assert get(env, suffix, tenant=202, project=3).status_code == 403
    assert get(env, suffix, project=3).status_code == 404
    if suffix.count('/') > 1:
        assert get(env, suffix, project=2).status_code == 404
    else:
        response = get(env, suffix, project=2)
        assert response.status_code == 200
        if 'items' in response.json()['data']:
            items = response.json()['data']['items']
            if suffix in {'/questions', '/content'}:
                assert [r['id'] for r in items] == [4]
            elif suffix == '/answers':
                assert items == []


def test_empty_binding_has_no_tenant_fallback(env):
    add_answers(env)
    for suffix in ('/questions', '/answers', '/content', '/deliveries', '/visibility', '/overview'):
        response = get(env, suffix, project=4)
        assert response.status_code == 200, response.text
        body = response.json()
        assert body['scope']['binding_state'] == 'unbound'
        assert body['scope']['question_count'] == body['scope']['business_count'] == 0
        if 'items' in body['data']:
            assert body['data']['items'] == []
        else:
            weekly = body['data'].get('weekly') or body['data']['current']
            assert all(m['value'] is None for m in weekly['metrics'])
    assert get(env, '/content/1', project=4).status_code == 404


@pytest.mark.parametrize('field,value,code', [('status', 'paused', 409), ('tenant_module_id', 999, 403)])
def test_inactive_and_module_binding_fail_closed(env, field, value, code):
    project = env.session.get(GeoProject, 1)
    setattr(project, field, value)
    env.save(project)
    for suffix in all_paths():
        assert get(env, suffix).status_code == code


@pytest.mark.parametrize('scope', [None, [], 'broken', {'business_ids': [11, 999]}, {'business_ids': [11, 11]},
                                   {'business_ids': [True]}, {'business_ids': [11], 'revision': 'bad'}])
def test_binding_validation(env, scope):
    project = env.session.get(GeoProject, 1)
    project.project_settings = {'geo_business_scope': scope}
    env.save(project)
    response = get(env, '/questions')
    assert response.status_code == (200 if scope is None else 409), response.text


@pytest.mark.parametrize('role', ['customer', 'advisor', 'admin'])
def test_roles_use_explicit_project_scope_for_all_routes(env, role):
    add_answers(env)
    if role == 'advisor':
        env.ctx.advisor_scope = AdvisorScope(frozenset({101}), 101, 1)
        env.monkeypatch.setattr('app.security.advisor_write_reads.assigned_scope', AsyncMock(return_value=({1}, {11})))
    if role == 'admin':
        env.ctx.is_superadmin = True
        env.ctx.tenant_id = None
    for suffix in all_paths():
        assert get(env, suffix).status_code == 200
    if role == 'advisor':
        assert get(env, '/overview', project=2).status_code == 404
        env.monkeypatch.setattr('app.security.advisor_write_reads.assigned_scope', AsyncMock(return_value=(set(), set())))
        assert get(env, '/overview').status_code == 404
    if role == 'admin':
        assert get(env, '/overview', project=3, tenant=202).status_code == 200


@pytest.mark.parametrize('missing', ['geo.assets', 'geo.content'])
def test_both_view_permissions_required_on_every_route(env, missing):
    env.ctx.permissions.pop(missing)
    for suffix in all_paths():
        assert get(env, suffix).status_code == 403


def test_module_revocation_and_demo_are_checked_per_request(env):
    assert get(env, '/overview').status_code == 200
    env.monkeypatch.setattr(store, 'ensure_geo_entitlement', AsyncMock(side_effect=HTTPException(403, 'unavailable')))
    response = get(env, '/overview')
    assert response.status_code == 403 and response.json()['detail']['code'] == 'GEO_CLIENT_MODULE_UNAVAILABLE'
    env.monkeypatch.setattr(store, 'ensure_geo_entitlement', AsyncMock(return_value=NS(is_demo=True)))
    response = get(env, '/overview')
    assert response.status_code == 403 and response.json()['detail']['code'] == 'GEO_CLIENT_DEMO_UNSUPPORTED'


@pytest.mark.parametrize('count,engines,questions,ready', [(0, 2, 3, False), (7, 2, 3, False),
    (8, 1, 3, False), (8, 2, 2, False), (8, 2, 3, True)])
def test_coverage_thresholds_and_true_zero(env, count, engines, questions, ready):
    add_answers(env, count, mention=False, engines=engines, questions=questions)
    current = get(env, '/visibility').json()['data']['current']
    assert current['sample_status'] == ('ready' if ready else 'insufficient')
    assert all(m['value'] == (0 if ready else None) for m in current['metrics'])
    assert get(env, '/overview').json()['data']['weekly'] == current


def test_only_simulated_samples_never_become_effectiveness(env):
    add_answers(env, simulated=True)
    body = get(env, '/visibility').json()
    assert body['basis']['source_counts'] == {'real': 0, 'manual': 0, 'simulated': 8, 'unknown': 0}
    assert body['data']['current']['qualified_counts']['samples'] == 0
    assert all(m['value'] is None for m in body['data']['current']['metrics'])
    question = get(env, '/questions/1').json()['data']['question']
    assert question['observation']['total'] == 0


def test_project_domains_and_missing_domain_only_disable_score(env):
    add_answers(env)
    result = get(env, '/visibility').json()['data']['current']
    assert result['own_domains'] == ['docs.p1.example.com', 'p1.example.com']
    project = env.session.get(GeoProject, 1)
    project.canonical_domain = 'missing.example.com'
    env.save(project)
    current = get(env, '/visibility').json()['data']['current']
    assert [m['status'] for m in current['metrics']] == ['available', 'available', 'unavailable']
    assert current['metrics'][2]['value'] is None


@pytest.mark.parametrize('change,reason', [('question', 'question_changed'), ('model', 'model_distribution_changed'),
    ('missing_model', 'model_metadata_missing'), ('engine', 'cohort_changed'), ('distribution', 'sample_distribution_changed')])
def test_comparison_uses_historical_metadata_and_full_distributions(env, change, reason):
    add_answers(env)
    rows = add_answers(env, previous=True)
    assert get(env, '/visibility').json()['data']['comparison']['comparable']
    run = env.session.get(Run, 100)
    cells = deepcopy(run.items)
    if change == 'question': cells[0]['prompt_question'] = 'Edited historical question'
    if change == 'model': cells[0]['model'] = 'other'
    if change == 'missing_model': cells[0].pop('model')
    if change == 'engine':
        rows[0].engine = cells[0]['engine'] = 'different'
    if change == 'distribution':
        rows[0].prompt_id = cells[0]['prompt_id'] = 2
        cells[0]['prompt_question'] = 'Historical 2'
    run.items = cells
    env.save(run, *rows)
    result = get(env, '/visibility').json()['data']
    assert not result['comparison']['comparable'] and reason in result['comparison']['reason_codes']
    assert all(m['trend_7d'] is None for m in result['current']['metrics'])


@pytest.mark.parametrize('mention', [True, False])
def test_single_question_observations_and_attention_are_consistent(env, mention):
    add_answers(env, 1, mention=mention)
    detail = get(env, '/questions/1').json()['data']
    assert detail['question']['observation']['display_text'] == f'观测中提及 {int(mention)}/1 次'
    assert detail['question']['observation']['official_question_rate'] is None
    overview = get(env, '/overview').json()['data']['monitoring']
    attention = get(env, '/questions', attention='needs_attention').json()['data']['items']
    assert overview['attention_question_count'] == len(attention) == (2 if mention else 3)
    assert overview['no_real_observation_question_count'] == 2
    assert overview['some_nonmention_question_count'] == int(not mention)


@pytest.mark.parametrize('resource', ['questions', 'answers', 'content', 'variants', 'deliveries'])
def test_keyset_pages_watermarks_and_cursor_scope(env, resource):
    answers = add_answers(env)
    if resource == 'answers':
        answers[0].captured_at = NOW + timedelta(microseconds=1)
        env.save(answers[0])
    suffix = '/content/1/variants' if resource == 'variants' else '/' + resource
    if resource == 'variants':
        env.save(*[Variant(id=10+i, task_id=1, article_version_id=1, title='v', channel='website', body_markdown='full') for i in range(3)])
    response = get(env, suffix, limit=1)
    assert response.status_code == 200, response.text
    data = response.json()['data']
    if resource == 'answers':
        assert data['items'][0]['id'] == 1  # +1 microsecond sorts before whole seconds.
    total, cursor = data['pagination']['total_count'], data['pagination']['next_cursor']
    assert cursor and data['pagination']['has_more']
    seen = [json.dumps(data['items'][0], sort_keys=True)]
    assert get(env, suffix, project=2, limit=1, cursor=cursor).status_code == 400
    assert get(env, suffix, limit=2, cursor=cursor).status_code == 400
    assert get(env, suffix, limit=1, cursor=cursor[:-1]+'!').status_code == 400
    if resource == 'variants':
        assert get(env, '/content/2/variants', limit=1, cursor=cursor).status_code == 400
    while cursor:
        response = get(env, suffix, limit=1, cursor=cursor)
        assert response.status_code == 200, response.text
        data = response.json()['data']
        assert data['pagination']['total_count'] == total
        seen.extend(json.dumps(r, sort_keys=True) for r in data['items'])
        cursor = data['pagination']['next_cursor']
    assert len(seen) == len(set(seen)) == total
    assert not data['pagination']['has_more'] and not data['pagination']['truncated']


def test_cursor_detects_binding_chain_change_and_preserves_week(env):
    add_answers(env)
    cursor = get(env, '/answers', limit=1).json()['data']['pagination']['next_cursor']
    response = env.http.get('/api/v1/geo/projects/1/client/answers', params={'tenant_id': 101, 'limit': 1, 'cursor': cursor})
    assert response.status_code == 200 and response.json()['basis']['period']['week_end'] == WEEK
    assert get(env, '/answers', limit=1, cursor=cursor, week_end='2026-10-12').status_code == 400
    unit = env.session.get(Unit, 11)
    unit.business_id = 22
    env.save(unit)
    response = get(env, '/answers', limit=1, cursor=cursor)
    assert response.status_code == 409 and response.json()['detail']['code'] == 'GEO_CLIENT_SCOPE_CHANGED'
    assert get(env, '/answers/1').status_code == 404


def test_new_records_do_not_enter_pagination_watermark_or_change_metrics(env):
    add_answers(env)
    initial = get(env, '/questions', limit=1).json()['data']
    cursor = initial['pagination']['next_cursor']
    env.save(Prompt(id=99, tenant_id=101, unit_id=11, question='New question'))
    # A newly assigned prompt changes the ownership chain and requires a refresh.
    assert get(env, '/questions', limit=1, cursor=cursor).status_code == 409
    initial = get(env, '/content', limit=1).json()['data']
    env.save(Task(id=99, tenant_id=101, prompt_id=1, title='New task'))
    response = get(env, '/content', limit=1, cursor=initial['pagination']['next_cursor'])
    assert response.status_code == 200 and response.json()['data']['pagination']['total_count'] == 3
    assert get(env, '/visibility').json()['data']['current']['qualified_counts']['samples'] == 8


def test_unknown_times_and_historical_details_are_not_put_in_week(env):
    rows = add_answers(env, 3)
    rows[0].captured_at = None
    rows[1].captured_at = datetime(2020, 1, 1)
    rows[2].sample_mode = 'manual'
    env.save(*rows)
    listing = get(env, '/answers').json()
    assert listing['data']['pagination']['total_count'] == 1
    assert listing['basis']['unknown_time_count'] == 1
    assert get(env, '/answers/1').json()['data']['item']['source']['kind'] == 'real'
    old = get(env, '/answers/2').json()
    assert not old['data']['item']['week_membership']['within_window']
    assert 'outside_selected_week' in old['data']['item']['week_membership']['reason_codes']
    assert old['basis']['source_counts'] == {'real': 0, 'manual': 0, 'simulated': 0, 'unknown': 0}
    assert get(env, '/answers', source_kind='manual').json()['basis']['unknown_time_count'] == 0


def test_review_receipt_publication_and_verification_remain_distinct(env):
    env.save(Article(id=10, task_id=1, version_no=2, kind='master', title='New master', body_markdown='Full new master',
                     created_at=NOW+timedelta(days=1)))
    task = get(env, '/content/1').json()['data']
    assert task['task']['review']['status'] == 'approved'
    assert not task['task']['review']['covers_current_master']
    assert task['receipt_summary']['succeeded'] == 1
    assert task['master']['id'] == 10
    expected_time = view.iso(NOW+timedelta(days=1))
    assert get(env, '/content/1').json()['basis']['last_data_at'] == expected_time
    assert get(env, '/content', question_id=1).json()['basis']['last_data_at'] == expected_time
    delivery = get(env, '/deliveries', task_id=1).json()['data']
    assert delivery['counts'] == {'publication_records': 1, 'receipt_records': 1, 'published_records': 1, 'stored_verified_publications': 0}
    assert delivery['items'][0]['verification']['reason_codes'] == ['historical_article']
    assert get(env, '/content/1/articles/1').json()['data']['is_current_master'] is False
    assert get(env, '/content/1/articles/4').status_code == 404
    assert get(env, '/content/1/variants/4').status_code == 404


def test_verification_uses_saved_fingerprint_and_timestamp(env):
    from app.geo.acceptance_readiness import _variant_fingerprint
    variant = env.session.get(Variant, 1)
    variant.adapt_meta = {**variant.adapt_meta, 'publication_monitor': {'1': {
        'state': 'healthy', 'expected_fingerprint': _variant_fingerprint(variant), 'article_id': 1,
        'checked_at': '2026-10-15T10:00:00Z'}}}
    env.save(variant)
    publication = env.session.get(Publication, 1)
    publication.updated_at = NOW+timedelta(days=1)
    env.save(publication)
    rows = get(env, '/deliveries', task_id=1).json()['data']
    assert rows['counts']['stored_verified_publications'] == 1
    assert rows['items'][0]['verification']['evidence_valid']
    assert get(env, '/deliveries', task_id=1).json()['basis']['last_data_at'] == view.iso(publication.updated_at)
    state = deepcopy(variant.adapt_meta)
    state['publication_monitor']['1']['article_id'] = 4
    variant.adapt_meta = state
    env.save(variant)
    result = get(env, '/deliveries', task_id=1).json()['data']['items'][0]
    assert not result['verification']['evidence_valid']
    assert 'article_version_mismatch' in result['verification']['reason_codes']


@pytest.mark.parametrize('suffix,query', [('/questions', {'status': 'bad'}), ('/content', {'q': '  '}),
    ('/answers', {'engine_key': 'bad/key'}), ('/content', {'include_archived': '1'}),
    ('/answers', {'limit': 101}), ('/questions', {'business_id': 22}), ('/answers', {'question_id': 0}),
    ('/questions', {'limit': 0}), ('/deliveries', {'record_type': 'external'}), ('/overview', {'q': 'x'})])
def test_query_contract_is_strict(env, suffix, query):
    assert get(env, suffix, **query).status_code == 422


def test_duplicate_body_invalid_ids_and_non_get_are_rejected(env):
    base = '/api/v1/geo/projects/1/client/questions'
    assert env.http.get(base+'?tenant_id=101&tenant_id=101').status_code == 422
    assert env.http.request('GET', base+'?tenant_id=101', json={}).status_code == 422
    assert env.http.get('/api/v1/geo/projects/0/client/questions?tenant_id=101').status_code == 422
    assert env.http.get('/api/v1/geo/projects/1/client/questions?tenant_id=9007199254740992').status_code == 422
    for suffix in all_paths():
        for method in ('POST', 'PUT', 'PATCH', 'DELETE'):
            assert env.http.request(method, '/api/v1/geo/projects/1/client'+suffix, params={'tenant_id': 101}).status_code == 405


@pytest.mark.parametrize('week', ['2026-10-20', '9999-12-27', '0001-01-01', '20261019', 'garbage'])
def test_only_closed_shanghai_weeks_are_accepted(env, week):
    assert get(env, '/visibility', week_end=week).status_code == 400


@pytest.mark.parametrize('url,state', [('https://example.com/a#x', 'available'), ('javascript:x', 'invalid'),
    ('https://user:pass@example.com/a', 'suppressed'), ('https://example.com/a?x=1', 'available'),
    ('http://127.0.0.1/a', 'suppressed'), ('https://foo.internal/x', 'suppressed'),
    ('http://2130706433/a', 'suppressed'), ('https://example.com\\@localhost/', 'invalid')])
def test_public_links_never_expose_auth_or_private_targets(url, state):
    safe, actual = safe_url(url)
    assert actual == state
    assert (safe is not None) == (state == 'available')


def test_read_budget_is_an_error_not_a_silent_partial_aggregate(env, monkeypatch):
    monkeypatch.setattr(store, 'ROW_BUDGET', 2)
    response = get(env, '/overview')
    assert response.status_code == 503
    assert response.json()['detail']['code'] == 'GEO_CLIENT_READ_UNAVAILABLE'


def test_read_transaction_sets_database_guard_and_always_rolls_back():
    class Context:
        async def __aenter__(self): return session
        async def __aexit__(self, *args): pass
    session = Mock(execute=AsyncMock(), rollback=AsyncMock())
    async def consume():
        async for value in store.client_read_session():
            assert value is session
    with patch.object(store, 'async_session_factory', return_value=Context()) as factory:
        asyncio.run(consume())
    factory.assert_called_once_with(autoflush=False)
    assert [str(call.args[0]) for call in session.execute.call_args_list] == [
        'SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY', "SET LOCAL statement_timeout = '5000ms'"]
    session.rollback.assert_awaited_once()
    session.add.assert_not_called()
    session.flush.assert_not_called()
    session.commit.assert_not_called()


@pytest.mark.parametrize('mutation,reason', [('manual', 'manual_sample'), ('unknown', 'unknown_source'),
    ('legacy', 'unsupported_sampling_method'), ('analysis', 'analysis_incomplete'),
    ('citation', 'citation_inaccurate'), ('probe', 'brand_probe'), ('missing_run', 'missing_server_evidence'),
    ('unfinished', 'patrol_not_completed'), ('outside_patrol', 'capture_outside_patrol'),
    ('mismatch', 'snapshot_patrol_mismatch'), ('foreign_run', 'missing_server_evidence')])
def test_sample_exclusions_are_shared_by_metrics_lists_and_details(env, mutation, reason):
    rows = add_answers(env, 1)
    row = rows[0]
    run = env.session.get(Run, 99)
    prompt = env.session.get(Prompt, 1)
    if mutation == 'manual': row.sample_mode = 'manual'
    if mutation == 'unknown': row.sample_mode = 'unknown'
    if mutation == 'legacy': row.note = 'method=legacy analysis=completed'
    if mutation == 'analysis': row.note = 'method=unprimed_json_v2 analysis=needs_review'
    if mutation == 'citation': row.citation_accuracy = 'inaccurate'
    if mutation == 'probe': prompt.is_brand_probe = True
    if mutation == 'missing_run': row.patrol_run_id = None
    if mutation == 'unfinished': run.status = 'running'
    if mutation == 'outside_patrol': run.finished_at = NOW-timedelta(hours=1)
    if mutation == 'mismatch': row.raw_text = 'Tampered answer'
    if mutation == 'foreign_run': run.tenant_id = 202
    env.save(row, run, prompt)
    detail = get(env, '/answers/1').json()['data']['item']
    assert not detail['sample_eligibility']['eligible']
    assert reason in detail['sample_eligibility']['reason_codes']
    assert all(a['status'] == 'excluded' for a in detail['metric_adoption'])
    assert get(env, '/answers', eligibility='qualified').json()['data']['items'] == []
    assert len(get(env, '/answers', eligibility='excluded').json()['data']['items']) == 1
    assert get(env, '/overview').json()['data']['monitoring']['qualified_answer_count'] == 0


def test_shanghai_window_boundaries_are_half_open_and_current_status_is_not_historical_qualification(env):
    rows = add_answers(env, 3)
    rows[0].captured_at = datetime(2026, 10, 11, 16)
    rows[1].captured_at = datetime(2026, 10, 18, 15, 59, 59)
    rows[2].captured_at = datetime(2026, 10, 18, 16)
    run = env.session.get(Run, 99)
    run.started_at, run.finished_at = datetime(2026, 10, 11), datetime(2026, 10, 19)
    prompt = env.session.get(Prompt, 1)
    prompt.status = 'archived'
    env.save(*rows, run, prompt)
    result = get(env, '/answers').json()
    assert {r['id'] for r in result['data']['items']} == {1, 2}
    assert result['basis']['source_counts']['real'] == 2
    assert get(env, '/questions/1').json()['data']['question']['qualified_sample_count'] == 1
    assert get(env, '/answers/3').json()['data']['item']['week_membership']['within_window'] is False


def test_domain_citations_use_exact_or_subdomain_and_safe_link_projection(env):
    rows = add_answers(env)
    run = env.session.get(Run, 99)
    cells = deepcopy(run.items)
    for i, row in enumerate(rows):
        url = 'https://docs.p1.example.com/a' if i == 0 else 'https://evil-p1.example.com/a'
        row.raw_text = f'Saved answer {url}'
        row.cited_urls = [url]
        cells[i]['raw_text'] = row.raw_text
    run.items = cells
    env.save(*rows, run)
    result = get(env, '/visibility').json()['data']['current']
    assert result['qualified_own_domain_citation_count'] == 1
    assert result['metrics'][2]['value'] == 56.25
    assert get(env, '/answers/1').json()['data']['citations'][0]['is_own_domain']
    assert not get(env, '/answers/2').json()['data']['citations'][0]['is_own_domain']
    rows[0].cited_urls += ['https://p1.example.com/a?signature=synthetic', 'http://127.0.0.1/a', 'javascript:x']
    env.save(rows[0])
    result = get(env, '/answers/1').json()['data']
    assert [r['url_state'] for r in result['citations']] == ['available', 'suppressed', 'suppressed', 'invalid']
    assert all(r['url'] is None for r in result['citations'][1:])
    assert result['citations'][1]['is_own_domain'] is True
    assert result['citations'][2]['is_own_domain'] is False


def test_content_filters_are_literal_and_do_not_guess_unknown_review(env):
    task = env.session.get(Task, 1)
    task.review_status = 'future_state'
    task.title = 'Literal 100%_ title'
    env.save(task)
    assert [t['id'] for t in get(env, '/content', q='%_').json()['data']['items']] == [1]
    assert [t['id'] for t in get(env, '/content', review_status='unknown').json()['data']['items']] == [1]
    assert get(env, '/content', question_id=4).status_code == 404
    task.status = 'archived'
    env.save(task)
    assert len(get(env, '/content').json()['data']['items']) == 2
    assert len(get(env, '/content', include_archived='true').json()['data']['items']) == 3
    assert get(env, '/content/1').status_code == 200


def test_receipt_invalid_article_and_delivery_filters_have_same_count_scope(env):
    variant = env.session.get(Variant, 1)
    variant.adapt_meta = {'push_deliveries': {'private-native-key': {'article_id': 4, 'state': 'succeeded',
        'result': {'account_id': 'SYNTHETIC_PRIVATE'}}}}
    env.save(variant)
    receipt = get(env, '/deliveries', task_id=1, record_type='receipt').json()['data']
    assert receipt['counts'] == {'publication_records': 0, 'receipt_records': 1, 'published_records': 0, 'stored_verified_publications': 0}
    assert receipt['items'][0]['article_id'] is None
    assert receipt['items'][0]['reason_code'] == 'article_reference_invalid'
    publication = get(env, '/deliveries', task_id=1, record_type='publication').json()['data']
    assert publication['counts']['receipt_records'] == 0
    assert publication['pagination']['total_count'] == 1
    assert get(env, '/deliveries', task_id=4).status_code == 404


def test_live_advisor_assignment_checks_actual_project_plan(env):
    project = env.session.get(GeoProject, 1)
    project.project_settings = {**project.project_settings, 'geo_service_plan': {'advisor_user_id': 9}}
    env.save(project)
    env.ctx.advisor_scope = AdvisorScope(frozenset({101}), 101, 1)
    assert get(env, '/overview').status_code == 200
    assert get(env, '/overview', project=2).status_code == 404
    project.project_settings = {**project.project_settings, 'geo_service_plan': {'advisor_user_id': 10}}
    env.save(project)
    assert get(env, '/overview').status_code == 404


def test_advisor_auth_guard_accepts_exact_new_routes_then_uses_read_only_parent_authorization(env):
    from app.security.geo_advisor import guard_request
    from app.security.geo_advisor_routes import READ_ROUTES
    from starlette.requests import Request
    env.ctx.advisor_scope = AdvisorScope(frozenset({101}), 101, 1)
    claims = {'scope_kind': 'advisor_tenant', 'exp': 9999999999}
    for route in router.routes:
        assert route.path in READ_ROUTES
        scope = {'type': 'http', 'method': 'GET', 'path': route.path.format(project_id=1, question_id=1,
                 answer_id=1, task_id=1, variant_id=1, article_id=1), 'headers': [],
                 'query_string': b'tenant_id=101', 'route': route}
        request = Request(scope)
        asyncio.run(guard_request(Mock(), env.ctx, request, claims))
        assert scope['geo_advisor_delivery'][0] == 9
    unknown = Request({'type': 'http', 'method': 'GET', 'path': '/api/v1/geo/projects/1/client/settings',
                       'headers': [], 'query_string': b'tenant_id=101'})
    with pytest.raises(HTTPException) as error:
        asyncio.run(guard_request(Mock(), env.ctx, unknown, claims))
    assert error.value.status_code == 403


def test_anonymous_request_is_rejected_without_database_query(env):
    env.http.app.dependency_overrides.pop(require_scoped_auth)
    response = get(env, '/overview')
    assert response.status_code == 401
    assert env.statements == []


def test_read_source_failure_is_sanitized_and_rolled_back():
    from sqlalchemy.exc import SQLAlchemyError
    class Context:
        async def __aenter__(self): return session
        async def __aexit__(self, *args): pass
    session = Mock(execute=AsyncMock(side_effect=SQLAlchemyError('SYNTHETIC_PRIVATE')), rollback=AsyncMock())
    async def consume():
        async for _ in store.client_read_session(): pass
    with patch.object(store, 'async_session_factory', return_value=Context()), pytest.raises(HTTPException) as error:
        asyncio.run(consume())
    assert error.value.status_code == 503
    assert 'SYNTHETIC_PRIVATE' not in str(error.value.detail)
    session.rollback.assert_awaited_once()


@pytest.mark.parametrize('url,expected', [
    ('https://example.com/a?utm_source=fixture&utm_medium=test#part', 'https://example.com/a'),
    ('https://example.com/a?id=123&utm_source=fixture&gclid=tracking', 'https://example.com/a?id=123'),
    ('https://example.com/a?id=123', 'https://example.com/a?id=123'),
    ('http://example.com/a?id=1&id=2&empty=', 'http://example.com/a?id=1&id=2&empty='),
    ('https://example.com/a?UTM_Source=x&FBCLID=y&MSCLKID=z&spm=a&dclid=b&yclid=c&_ga=d&_gl=e', 'https://example.com/a'),
    ('https://example.com/a?%75tm_source=x&id=123', 'https://example.com/a?id=123'),
    ('https://example.com/a?monkey=1&keyboard=2&zipcode=3', 'https://example.com/a?monkey=1&keyboard=2&zipcode=3'),
])
def test_public_link_query_keeps_document_parameters_and_removes_tracking(url, expected):
    assert safe_url(url) == (expected, 'available')


@pytest.mark.parametrize('key', ['token', 'access_token', 'key', 'apikey', 'secret', 'password',
    'sig', 'signature', 'auth', 'session', 'code', 'ToKeN', '%74oken', 'api_key', 'X-Amz-Signature',
    'client_secret', 'refresh_token', 'session[id]', 'utm_token', 'authorization', 'accessToken'])
def test_credential_query_suppresses_the_whole_link_even_with_tracking(key):
    assert safe_url(f'https://example.com/a?id=123&utm_source=fixture&{key}=SYNTHETIC_URL_CREDENTIAL') == (None, 'suppressed')
    assert safe_url(f'https://example.com/a?{key}') == (None, 'suppressed')


@pytest.mark.parametrize('url', ['data:text/html,fixture', 'file:///fixture', 'https://@example.com/a',
    'http://[::1]/', 'http://0x7f000001/', 'http://0177.0.0.1/', 'http://0x7f.0.0.1/',
    'http://host.localdomain/', 'http://host.corp/', 'http://host.lan/', 'http://host.home/',
    'http://host.test/', 'http://host.invalid/', 'https://example.com:8443/a', 'http://intranet/'])
def test_query_support_does_not_open_unsafe_targets(url):
    assert safe_url(url)[0] is None


def test_citation_and_publication_query_projection_exposes_only_public_domain_when_suppressed(env):
    row = add_answers(env, 1)[0]
    row.cited_urls = ['https://p1.example.com/a?utm_source=fixture&id=123',
        'https://p1.example.com/a?token=SYNTHETIC_URL_CREDENTIAL',
        'https://synthetic:fixture@p1.example.com/a', 'http://127.0.0.1/a']
    env.save(row)
    citations = get(env, '/answers/1').json()['data']['citations']
    assert citations[0] == {'url': 'https://p1.example.com/a?id=123', 'domain': 'p1.example.com',
                            'url_state': 'available', 'is_own_domain': True}
    assert citations[1] == {'url': None, 'domain': 'p1.example.com', 'url_state': 'suppressed', 'is_own_domain': True}
    assert citations[2] == citations[1]
    assert citations[3]['domain'] is None
    assert 'SYNTHETIC_URL_CREDENTIAL' not in json.dumps(citations)
    publication = env.session.get(Publication, 1)
    publication.published_url = 'https://p1.example.com/post?id=123&utm_source=fixture'
    env.save(publication)
    result = get(env, '/deliveries', task_id=1).json()['data']
    assert result['items'][0]['published_url'] == 'https://p1.example.com/post?id=123'
    assert result['counts']['published_records'] == 1
    publication.published_url = 'https://p1.example.com/post?token=SYNTHETIC_URL_CREDENTIAL'
    env.save(publication)
    result = get(env, '/deliveries', task_id=1).json()['data']
    assert result['items'][0]['published_url'] is None
    assert result['items'][0]['domain'] == 'p1.example.com'
    assert result['items'][0]['url_state'] == 'suppressed'
    assert result['counts']['published_records'] == 0
    assert 'SYNTHETIC_URL_CREDENTIAL' not in json.dumps(result)
