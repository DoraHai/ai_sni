"""Entirely synthetic fixtures, including SELECT-only HTTP integration."""
from copy import deepcopy
from datetime import datetime, timedelta
from types import SimpleNamespace as NS

import pytest
from sqlalchemy.dialects import postgresql

from app.geo.project_demo import (TOKEN, TOKEN_PATTERN, ENGINES, START, UNITS,
                                  project_batch, load_demo_batch)
from app.geo.project_client_store import ProjectRecords
from app.geo.content.sample_provenance import sample_provenance
from test_geo_project_client import env, get
from app.models import GeoProject, GeoOptimizationBusiness as Business, GeoOptimizationUnit as Unit
from app.models import GeoPrompt as Prompt, GeoAnswerSnapshot as Answer


@pytest.fixture
def batch():
    records = ProjectRecords(project=NS(id=3, tenant_id=15, canonical_domain=''), revision=1,
        businesses={16: NS(id=16)}, units={uid: NS(id=uid, business_id=16) for uid in (19, 20)},
        prompts={qid: NS(id=qid, unit_id=uid, is_brand_probe=qid == 85, question=f'Synthetic question {qid}')
                 for qid, uid in UNITS.items()})
    rows = [NS(id=10000+i, tenant_id=15, prompt_id=qid, engine=engine,
        captured_at=datetime(2026, 10, 19, 16) + timedelta(days=day), simulated=True,
        sample_mode='mock_persona', patrol_run_id=None, note=f'模拟演示 · {TOKEN}',
        mentions_brand=(i % 4 == 0))
        for i, (qid, engine, day) in enumerate((q, e, d) for q in UNITS for e in ENGINES for d in range(30))]
    return records, rows


def test_counts_are_from_saved_rows_and_brand_85_is_separate(batch):
    records, rows = batch
    data = project_batch(records, rows)
    assert data['saved_sample_count'] == len(rows) == 1680
    assert data['ordinary']['sample_count'] == 1440
    assert data['brand_probe']['sample_count'] == 240
    assert {q['id'] for q in data['ordinary']['questions']} == set(UNITS) - {85}
    assert data['ordinary']['mentioned_count'] == sum(r.mentions_brand for r in rows if r.prompt_id != 85)
    assert data['engine_keys'] == list(ENGINES)
    assert data['period'] == {'start_date': '2026-10-20', 'end_date': '2026-11-18', 'timezone': 'Asia/Shanghai'}
    assert data['visibility_score'] is None and data['citations'] == []  # no project domain
    changed = deepcopy(rows)
    changed[0].mentions_brand = not changed[0].mentions_brand
    other = project_batch(records, changed)
    assert other['ordinary']['mention_rate'] != data['ordinary']['mention_rate']
    assert other['basis']['fingerprint'] != data['basis']['fingerprint']
    assert data['ordinary']['questions'][0]['by_engine'][0]['samples'][0]['snapshot_id'] == rows[0].id


@pytest.mark.parametrize('field,value', [('tenant_id', 16), ('prompt_id', 90), ('simulated', False),
    ('sample_mode', 'openai_compat'), ('patrol_run_id', 77), ('note', TOKEN),
    ('note', '模拟演示 ' + TOKEN + '-suffix'), ('note', '模拟演示 prefix-' + TOKEN),
    ('engine', 'openai'), ('captured_at', None), ('captured_at', datetime(2026, 11, 18, 16))])
def test_invalid_tagged_row_fails_closed(batch, field, value):
    records, rows = batch
    setattr(rows[0], field, value)
    assert project_batch(records, rows)['status'] == 'unavailable'


def test_missing_duplicate_and_changed_binding(batch):
    records, rows = batch
    assert project_batch(records, [])['reason_code'] == 'batch_missing'
    assert project_batch(records, rows[:-1])['reason_code'] == 'batch_incomplete_or_duplicate'
    assert project_batch(records, rows + [rows[0]])['status'] == 'unavailable'
    records.units.pop(20)
    assert project_batch(records, rows)['reason_code'] == 'binding_changed'


@pytest.mark.parametrize('qid', [83, 85])
def test_probe_conflict_stops_only_affected_group(batch, qid):
    records, rows = batch
    records.prompts[qid].is_brand_probe = not records.prompts[qid].is_brand_probe
    data = project_batch(records, rows)
    affected = 'brand_probe' if qid == 85 else 'ordinary'
    assert data[affected] == {'status': 'unavailable', 'reason_code': 'brand_probe_conflict'}
    assert data['ordinary' if qid == 85 else 'brand_probe']['status'] == 'available'


def test_non_target_does_not_query_and_simulation_wins_over_api_note(batch):
    import asyncio
    records, rows = batch
    rows[0].note += ' 真采样 openai_compat method=unprimed_json_v2 analysis=completed'
    assert sample_provenance(rows[0])['sample_kind'] == 'simulated'
    for tid, pid in ((16, 3), (15, 4)):
        records.project.tenant_id, records.project.id = tid, pid
        assert asyncio.run(load_demo_batch(None, records)) is None


def test_sql_selector_is_exact_note_token_and_reads_no_answer_body(batch):
    import asyncio
    records, _ = batch
    class Session:
        async def scalars(self, stmt):
            sql = str(stmt.compile(dialect=postgresql.dialect()))
            assert 'geo_answer_snapshots.note ~ ' in sql
            assert 'raw_text' not in sql and 'cited_urls' not in sql
            assert TOKEN_PATTERN in stmt.compile().params.values()
            return []
    assert asyncio.run(load_demo_batch(Session(), records))['reason_code'] == 'batch_missing'


def test_http_scoped_batch_and_formal_path_are_independent(env, batch):
    records, rows = batch
    project = env.session.get(GeoProject, 3)
    project.tenant_id, project.tenant_module_id, project.canonical_domain = 15, 15, ''
    project.project_settings = {'geo_business_scope': {'revision': 1, 'business_ids': [16]}}
    env.ctx.tenant_id = 15
    objects = [project, Business(id=16, tenant_id=15, name='Synthetic')]
    objects += [Unit(id=uid, tenant_id=15, business_id=16, name=f'Synthetic {uid}') for uid in (19, 20)]
    objects += [Prompt(id=qid, tenant_id=15, unit_id=uid, question=f'Synthetic question {qid}',
                       is_brand_probe=qid == 85) for qid, uid in UNITS.items()]
    objects += [Answer(**vars(r), raw_text='SYNTHETIC BODY NOT IN DEMO', cited_urls=[]) for r in rows]
    # Adjacent tokens, matching text without a note token and foreign tenants are excluded.
    for i, note, tid in ((1, '模拟演示 ' + TOKEN + '-suffix', 15), (2, '模拟演示', 15),
                         (3, '模拟演示 ' + TOKEN, 16)):
        objects.append(Answer(id=20000+i, tenant_id=tid, prompt_id=83, engine='doubao', note=note,
            captured_at=datetime(2026, 11, 10), simulated=True, sample_mode='mock_persona', raw_text=TOKEN))
    env.save(*objects)
    response = get(env, '/overview', project=3, tenant=15, week_end='2026-11-16')
    assert response.status_code == 200, response.text
    data = response.json()['data']
    assert data['demo_batch']['saved_sample_count'] == len(rows)
    assert 'SYNTHETIC BODY NOT IN DEMO' not in response.text
    assert data['weekly']['qualified_counts']['samples'] == 0
    assert data['open_week_progress']['detected_answer_count'] == 0
    assert get(env, '/overview', project=3, tenant=16).status_code == 403
    assert 'demo_batch' not in get(env, '/visibility', project=3, tenant=15, week_end='2026-11-16').json()['data']
