"""Report refresh must not discard cached prose or generate AI in read-only mode."""
import asyncio
from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app.ai import monthly_report as reports


@pytest.mark.parametrize('kind', ['analysis', 'monthly'])
@pytest.mark.parametrize('force', [False, True])
@pytest.mark.parametrize('has_cache', [False, True])
def test_read_only_reports_keep_available_cache_and_never_generate(monkeypatch, kind, force, has_cache):
    generated_at = datetime(2026, 10, 18, 6, 0)
    cached = SimpleNamespace(summary='已审核的缓存摘要', narrative={
        'module_comments': {'overview': '缓存点评'},
        'next_period_plan': ['区间计划'], 'next_month_plan': ['月度计划'],
    }, generated_at=generated_at) if has_cache else None
    session = SimpleNamespace(scalar=AsyncMock(return_value=cached), add=Mock(), commit=AsyncMock())
    generate = AsyncMock(side_effect=AssertionError('Read-only reports must not call the AI provider'))
    monkeypatch.setattr(reports, 'gather_report_data', AsyncMock(return_value={'period': {}}))
    monkeypatch.setattr(reports, 'is_enabled', lambda: True)
    monkeypatch.setattr(reports, 'generate_narrative', generate)
    tenant = SimpleNamespace(id=1)
    call = reports.get_analysis_report(session, tenant, date(2026, 10, 1), date(2026, 10, 18), force=force, read_only=True) if kind == 'analysis' else reports.get_monthly_report(session, tenant, 2026, 10, force=force, read_only=True)
    result = asyncio.run(call)
    assert result['narrative'] == ({
        'summary': '已审核的缓存摘要', 'module_comments': {'overview': '缓存点评'},
        'next_period_plan': ['区间计划'] if kind == 'analysis' else ['月度计划'],
    } if has_cache else None)
    assert result['generated_at'] == (generated_at.isoformat() if has_cache else None)
    generate.assert_not_awaited()
    session.add.assert_not_called()
    session.commit.assert_not_awaited()


@pytest.mark.parametrize('kind', ['analysis', 'monthly'])
def test_writable_force_refresh_still_regenerates(monkeypatch, kind):
    cached = SimpleNamespace(summary='旧摘要', narrative={}, generated_at=datetime(2026, 10, 1))
    session = SimpleNamespace(scalar=AsyncMock(return_value=cached), add=Mock(), commit=AsyncMock())
    narrative = {'summary': '新摘要', 'module_comments': {}, 'next_period_plan': []}
    generate = AsyncMock(return_value=narrative)
    monkeypatch.setattr(reports, 'gather_report_data', AsyncMock(return_value={'period': {}}))
    monkeypatch.setattr(reports, 'is_enabled', lambda: True)
    monkeypatch.setattr(reports, 'generate_narrative', generate)
    tenant = SimpleNamespace(id=1)
    call = reports.get_analysis_report(session, tenant, date(2026, 10, 1), date(2026, 10, 18), force=True) if kind == 'analysis' else reports.get_monthly_report(session, tenant, 2026, 10, force=True)
    result = asyncio.run(call)
    assert result['narrative'] == narrative
    assert cached.summary == '新摘要'
    generate.assert_awaited_once()
    session.commit.assert_awaited_once()
