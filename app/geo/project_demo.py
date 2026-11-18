"""A saved, verified simulation batch, separate from every formal metric.

No fallback, sampling, writes, patrol inference, visibility score or citations.
Called only after project authorization, inside the existing read transaction.
"""
from collections import Counter
from datetime import date, timedelta
import re

from sqlalchemy import select
from sqlalchemy.orm import load_only

from app.geo.content.time_windows import shanghai_day_of_utc_naive
from app.geo.project_client_protocol import digest
from app.models import GeoAnswerSnapshot as Answer

TOKEN = 'geo-demo-t15-p3-20261118-v1'
TOKEN_PATTERN = r'(^|[^\w-])' + TOKEN + r'($|[^\w-])'
ENGINES = ('deepseek', 'doubao', 'qwen', 'hunyuan', 'wenxin', 'kimi', 'perplexity', 'other')
START, STOP = date(2026, 10, 20), date(2026, 11, 19)
# QD0's verified current chain; a later reassignment fails closed.
UNITS = {83: 20, 84: 20, 85: 19, 86: 19, 87: 19, 88: 19, 89: 19}
DISCLAIMER = '演示数据，不代表真实引擎检测或实际效果'


def target(records):
    return records.project.tenant_id == 15 and records.project.id == 3


def unavailable(reason):
    return {'batch_token': TOKEN, 'status': 'unavailable', 'reason_code': reason,
            'disclaimer': DISCLAIMER}


def project_batch(records, rows):
    """Pure validation/aggregation. Fixtures are never a production fallback."""
    if not target(records):
        return None
    for qid, uid in UNITS.items():
        prompt, unit = records.prompts.get(qid), records.units.get(uid)
        if not prompt or prompt.unit_id != uid or not unit or unit.business_id != 16 or 16 not in records.businesses:
            return unavailable('binding_changed')
    if not rows:
        return unavailable('batch_missing')
    grid = Counter()
    for row in rows:
        day = shanghai_day_of_utc_naive(row.captured_at)
        if (row.tenant_id != 15 or row.prompt_id not in UNITS
                or row.simulated is not True or row.sample_mode != 'mock_persona'
                or row.patrol_run_id is not None or not re.search(TOKEN_PATTERN, row.note or '')
                or '模拟演示' not in (row.note or '') or day is None or not START <= day < STOP
                or row.engine not in ENGINES):
            return unavailable('batch_invalid')
        grid[(row.prompt_id, row.engine, day)] += 1
    expected = {(qid, engine, START + timedelta(days=i)) for qid in UNITS
                for engine in ENGINES for i in range((STOP - START).days)}
    if set(grid) != expected or any(n != 1 for n in grid.values()) or len({r.id for r in rows}) != len(rows):
        return unavailable('batch_incomplete_or_duplicate')

    def counts(selected):
        total = len(selected)
        mentioned = sum(r.mentions_brand is True for r in selected)
        return {'sample_count': total, 'mentioned_count': mentioned,
                'unknown_mention_count': sum(r.mentions_brand is None for r in selected),
                'mention_rate': round(100 * mentioned / total, 4) if total else None}

    def group(probe):
        ids = [qid for qid in UNITS if (qid == 85) == probe]
        if any(records.prompts[qid].is_brand_probe is not probe for qid in ids):
            return {'status': 'unavailable', 'reason_code': 'brand_probe_conflict'}
        selected = [r for r in rows if r.prompt_id in ids]
        questions = []
        for qid in ids:
            prompt = records.prompts[qid]
            cells = []
            for engine in ENGINES:
                samples = sorted((r for r in selected if r.prompt_id == qid and r.engine == engine),
                                 key=lambda r: (r.captured_at, r.id))
                cells.append({'engine_key': engine, **counts(samples), 'samples': [
                    {'snapshot_id': r.id, 'captured_at': r.captured_at.isoformat() + ('Z' if r.captured_at.tzinfo is None else ''),
                     'mentioned': r.mentions_brand} for r in samples]})
            questions.append({'id': qid, 'question': prompt.question, 'unit_id': prompt.unit_id,
                              'is_brand_probe': probe, 'by_engine': cells})
        return {'status': 'available', **counts(selected), 'questions': questions}

    days = [shanghai_day_of_utc_naive(r.captured_at) for r in rows]
    return {'batch_token': TOKEN, 'status': 'available', 'disclaimer': DISCLAIMER,
            'source_kind': 'simulated', 'sample_mode': 'mock_persona',
            'period': {'start_date': str(min(days)), 'end_date': str(max(days)), 'timezone': 'Asia/Shanghai'},
            'saved_sample_count': len(rows), 'engine_keys': list(ENGINES),
            'ordinary': group(False), 'brand_probe': group(True),
            'basis': {'kind': 'saved_batch_records', 'ownership': 'current_project_binding',
                      'selection': 'note_independent_token', 'daily_grid_complete': True,
                      'simulated': True, 'sample_mode': 'mock_persona', 'patrol_linked': False,
                      'fingerprint': digest(sorted((r.id, r.prompt_id, r.engine, r.captured_at.isoformat(),
                                                   r.mentions_brand) for r in rows))},
            'visibility_score': None, 'visibility_reason': 'demo_not_formal_visibility',
            'citations': []}


async def load_demo_batch(session, records):
    if not target(records):
        return None
    # Read only metadata for the exact tenant + independent note token, including
    # invalid tagged rows so they cannot silently disappear from validation.
    fields = ('id', 'tenant_id', 'prompt_id', 'engine', 'captured_at', 'simulated',
              'sample_mode', 'patrol_run_id', 'note', 'mentions_brand')
    stmt = select(Answer).where(Answer.tenant_id == 15, Answer.note.regexp_match(TOKEN_PATTERN)).options(
        load_only(*(getattr(Answer, f) for f in fields), raiseload=True)).limit(10001)
    rows = list(await session.scalars(stmt))
    return unavailable('batch_over_budget') if len(rows) > 10000 else project_batch(records, rows)
