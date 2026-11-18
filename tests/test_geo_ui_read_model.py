"""Synthetic saved evidence: no application startup, providers or external database."""
import asyncio
from datetime import datetime, timedelta
from types import SimpleNamespace as NS
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session

from app.geo.content.customer_readiness import check_current_master
from app.geo.content.observation_view import model_state, observation_page, safe_alias
from app.models import GeoAnswerSnapshot as Answer, GeoPrompt as Prompt, GeoTrackingEngine as Engine
from app.security.auth import AuthContext


@compiles(JSONB, 'sqlite')
def sqlite_jsonb(element, compiler, **kw):
    return 'JSON'


def test_master_check_is_version_and_time_bound():
    now = datetime(2026, 1, 5)
    master = NS(id=7, created_at=now)
    assert check_current_master(None, {}) == 'no_master'
    assert check_current_master(master, {'ready': True}) == 'current_check_missing'
    for article_id, at in ((6, now), ('7', now), (True, now), (7, now-timedelta(seconds=1))):
        assert check_current_master(master, {'article_id': article_id, 'checked_at': at.isoformat(),
                                            'ready': True}) == 'current_check_missing'
    assert check_current_master(master, {'article_id': 7, 'checked_at': now.isoformat(), 'ready': False}) == 'not_ready'
    assert check_current_master(master, {'article_id': 7, 'checked_at': now.isoformat(), 'ready': True}) == 'ready'


def test_no_attempt_failure_and_saved_unscored_are_distinct():
    def state(saved=0, evaluated=0, configured=True, attempt=None):
        return model_state(saved=saved, evaluated=evaluated, configured=configured, attempt=attempt)
    assert state(configured=False) == 'not_configured'
    assert state() == 'not_attempted'
    assert state(attempt={'ok': False}) == 'failed'
    assert state(attempt={'ok': True}) == 'attempted_unsaved'
    assert state(attempt={'skipped_reason': 'skipped:real_only_no_platform_key'}) == 'not_configured'
    assert state(saved=4, attempt={'ok': False}) == 'saved_unscored'
    assert state(saved=4, evaluated=1) == 'evaluated'
    for value in ('https://upstream.invalid/error?secret=example', 'upstream\nerror', '<script>'):
        assert safe_alias(value) is None
    assert safe_alias('provider/model-v2') == 'provider/model-v2'


def test_scoped_summary_and_keyset_pages_preserve_unscored_answers():
    engine = create_engine('sqlite://')
    for model in (Prompt, Answer, Engine):
        model.__table__.create(engine)
    with Session(engine) as db:
        db.add_all([Prompt(id=1, tenant_id=101, question='Synthetic prompt', status='active'),
                    Prompt(id=2, tenant_id=101, question='Unassigned prompt', status='active'),
                    Prompt(id=3, tenant_id=202, question='Foreign prompt', status='active'),
                    Engine(id=1, tenant_id=101, engine_key='doubao', display_name='D', enabled=True),
                    Engine(id=2, tenant_id=101, engine_key='kimi', display_name='K', enabled=True)])
        for i in range(1, 24):
            db.add(Answer(id=i, tenant_id=101, prompt_id=1, engine='doubao', raw_text=f'Synthetic {i}',
                captured_at=datetime(2026, 1, 5), mentions_brand=i < 4,
                sentiment='positive' if i < 5 else 'unknown'))
        db.add(Answer(id=100, tenant_id=101, prompt_id=2, engine='doubao', raw_text='Unassigned',
                      captured_at=datetime(2026, 1, 5)))
        db.commit()
        statements = []
        class ReadOnly:
            async def scalar(self, stmt):
                assert stmt.is_select
                statements.append(str(stmt))
                if 'FROM geo_visibility_patrol_settings' in str(stmt):
                    return NS(engine_keys=['doubao', 'kimi'], enabled=False)
                if 'FROM geo_visibility_patrol_runs' in str(stmt):
                    return None
                return db.scalar(stmt)
            async def execute(self, stmt):
                assert stmt.is_select
                return db.execute(stmt)
            async def scalars(self, stmt):
                assert stmt.is_select
                statements.append(str(stmt))
                return db.scalars(stmt)
        ctx = AuthContext(9, 'synthetic', 'reader', 101, {'geo.content': 'view'})
        async def assigned(session, ctx, stmt, model):
            return stmt.where(Prompt.id == 1)
        async def run():
            with patch('app.geo.content.observation_view.filter_query', assigned):
                first = await observation_page(ReadOnly(), ctx, 101, 1, page_size=10)
                assert first['summary']['saved'] == 23
                assert first['summary']['evaluated'] == 3  # Unmentioned sentiment is not brand evaluation.
                assert [r.id for r in first['rows']] == list(range(23, 13, -1))
                assert first['pagination']['total_count'] == 23
                assert first['models'][0]['state'] == 'evaluated'
                assert next(m for m in first['models'] if m['engine'] == 'kimi')['state'] == 'not_attempted'
                db.add(Answer(id=101, tenant_id=101, prompt_id=1, engine='doubao', raw_text='New arrival',
                              captured_at=datetime(2026, 1, 5)))
                db.commit()
                second = await observation_page(ReadOnly(), ctx, 101, 1, page_size=10,
                    before_id=first['pagination']['next_before_id'], watermark=first['pagination']['watermark'])
                assert second['summary']['saved'] == 23
                assert not set(r.id for r in first['rows']) & set(r.id for r in second['rows'])
                third = await observation_page(ReadOnly(), ctx, 101, 1, page_size=10,
                    before_id=second['pagination']['next_before_id'], watermark=first['pagination']['watermark'])
                assert len(third['rows']) == 3 and third['pagination']['has_more'] is False
                for pid in (2, 3):
                    with pytest.raises(HTTPException) as exc:
                        await observation_page(ReadOnly(), ctx, 101, pid)
                    assert exc.value.status_code == 404
        asyncio.run(run())
        assert any('LIMIT' in s and 'geo_answer_snapshots.id <' in s for s in statements)
    engine.dispose()
