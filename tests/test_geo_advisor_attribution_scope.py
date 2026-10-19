"""Capture the actual publication query without opening any database."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.dialects.postgresql import dialect

from app import models as m
from app.geo.content.attribution import load_tenant_publications
from app.security.advisor_read_scope import predicates


@pytest.mark.parametrize('businesses', ((10,), (10, 11), ()))
def test_publication_projection_has_explicit_task_ownership_without_orm_events(businesses):
    conditions = predicates(SimpleNamespace(tenant_id=10, user_id=1), (10,), businesses)
    session = SimpleNamespace(info={'advisor_read_scope': (None, frozenset({10}),
        frozenset(businesses), conditions)}, execute=AsyncMock(return_value=SimpleNamespace(all=lambda: [])))
    assert asyncio.run(load_tenant_publications(session, 10)) == []
    sql = str(session.execute.call_args.args[0].compile(dialect=dialect(),
        compile_kwargs={'literal_binds': True}))
    assert 'geo_content_tasks.prompt_id IN (SELECT geo_prompts.id' in sql
    assert 'geo_optimization_units.business_id IN' in sql
    assert 'geo_content_tasks.business_id IS NULL OR geo_content_tasks.business_id IN' in sql
    if not businesses:
        assert '1 != 1' in sql


def test_missing_bound_task_predicate_fails_closed():
    session = SimpleNamespace(info={'advisor_read_scope': (None, (), (), {})},
        execute=AsyncMock(return_value=SimpleNamespace(all=lambda: [])))
    asyncio.run(load_tenant_publications(session, 10))
    sql = str(session.execute.call_args.args[0].compile(dialect=dialect()))
    assert 'WHERE false' in sql


def test_non_advisor_publication_loading_keeps_tenant_filter():
    session = SimpleNamespace(info={}, execute=AsyncMock(return_value=SimpleNamespace(all=lambda: [])))
    asyncio.run(load_tenant_publications(session, 10))
    sql = str(session.execute.call_args.args[0].compile(dialect=dialect(),
        compile_kwargs={'literal_binds': True}))
    assert 'geo_content_tasks.tenant_id = 10' in sql
    assert 'geo_content_tasks.prompt_id IN' not in sql
