import asyncio
from unittest.mock import AsyncMock

from app.ai.deepseek import DeepSeekError
from app.geo.content.probe import run_probe_draft


def probe(chat, question='推荐工业刀具供应商'):
    return asyncio.run(run_probe_draft(
        question=question, brand='Acme', brand_names=['Acme'], engine='deepseek',
        llm=dict(api_key='test', base_url='https://example.invalid', model='test'),
        chat_json=chat,
    ))


def test_brand_is_only_sent_to_independent_analysis():
    raw = '可以了解竞品甲的规格。'
    chat = AsyncMock(side_effect=[
        {'raw_text': raw, 'suggested_mentions_brand': True},
        {'raw_text': '不能替换原文', 'suggested_mentions_brand': False, 'citation_accuracy': 'accurate'},
    ])
    result = probe(chat)
    first, second = chat.await_args_list
    assert 'Acme' not in ''.join(first.args)
    assert first.args[1] == '推荐工业刀具供应商'
    assert 'Acme' in ''.join(second.args)
    assert raw in second.args[1]
    assert result['raw_text'] == raw
    assert result['suggested_mentions_brand'] is False
    assert result['suggested_citation_accuracy'] == 'unknown'
    assert result['sampling_method'] == 'unprimed_json_v2'


def test_analysis_failure_preserves_answer_for_review():
    chat = AsyncMock(side_effect=[{'raw_text': 'Acme 提供工业刀具。'}, DeepSeekError('timeout')])
    result = probe(chat)
    assert result['raw_text'] == 'Acme 提供工业刀具。'
    assert result['analysis_status'] == 'needs_review'
    assert result['source'] == 'heuristic'
    assert result['suggested_sentiment'] == 'unknown'


def test_explicit_brand_question_is_preserved():
    chat = AsyncMock(return_value={'raw_text': 'Acme 的信息需要查证。', 'suggested_mentions_brand': True})
    probe(chat, question='Acme 的刀具怎么样？')
    assert chat.await_args_list[0].args[1] == 'Acme 的刀具怎么样？'


def test_confirming_probe_preserves_sampling_source():
    from types import SimpleNamespace
    from unittest.mock import MagicMock, patch
    from app.geo.content import routes
    from app.geo.content.schemas import AnswerSnapshotCreate

    async def scenario():
        for mode in ('manual', 'mock_persona', 'openai_compat'):
            session = SimpleNamespace(add=MagicMock(), commit=AsyncMock(), refresh=AsyncMock())
            ctx = SimpleNamespace(ensure_tenant=MagicMock(), user_id=1)
            req = AnswerSnapshotCreate(tenant_id=1, prompt_id=2, raw_text='工业刀具回答。', sample_mode=mode)
            with (
                patch.object(routes, '_ensure_tenant_exists', new=AsyncMock()),
                patch.object(routes, '_get_prompt', new=AsyncMock(return_value=SimpleNamespace(id=2, question='刀具'))),
                patch.object(routes, 'resolve_matched_publication_ids', new=AsyncMock(return_value=[])),
                patch.object(routes, '_apply_brand_mention_side_effect', new=AsyncMock()),
                patch.object(routes, '_snapshot_payload', return_value={}),
                patch('app.geo.content.daily_metrics.safe_rebuild_for_captured_at', new=AsyncMock()),
            ):
                await routes.create_answer_snapshot(req, ctx, session)
            row = session.add.call_args.args[0]
            assert row.sample_mode == mode
            assert row.simulated == (mode == 'mock_persona')
    asyncio.run(scenario())
