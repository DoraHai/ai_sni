import asyncio
import os
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import MetaData, select, text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.api import seo_qa as api
from app.models.module_workspace import SeoSite
from app.models.seo import SeoContentAsset, SeoSerpResult, SeoContentReviewEvent
from app.models.seo_cockpit import SeoTask
from app.models.seo_qa import SeoQuestion, SeoQaFact, SeoQaAnswer, SeoQaPlacement
from app.security.auth import AuthContext
from app.seo_qa import fingerprint, parse_questions_csv, platform_url, observe_answer, answer_checks


def test_dedup_import_and_url_boundaries():
    assert fingerprint('如何选型？') == fingerprint('如何 选型?')
    assert fingerprint('A/B 的区别') == fingerprint('Ａ/Ｂ的区别')
    assert fingerprint('1.5 kW 如何选型') != fingerprint('15 kW 如何选型')
    assert fingerprint('A/B') != fingerprint('AB')
    assert parse_questions_csv('\ufefftitle,source_name\n如何选型,手册')[0]['source']['name'] == '手册'
    for value in ['name\nwrong', 'title\n', 'title\n' + '\n'.join(['问题']*201)]:
        with pytest.raises(ValueError):
            parse_questions_csv(value)
    with pytest.raises(ValidationError):
        api.ImportQuestions(tenant_id=1, site_id=1, items=[{'title': '??'}])
    assert platform_url('zhihu', 'https://www.zhihu.com/question/12/answer/34', answer=True,
                        question_url='https://www.zhihu.com/question/12').endswith('/answer/34')
    for value in ['https://www.zhihu.com/question/13/answer/34', 'https://zhuanlan.zhihu.com/p/12',
                  'https://www.zhihu.com.evil.example/question/12/answer/34', 'http://127.0.0.1/question/12']:
        with pytest.raises(ValueError):
            platform_url('zhihu', value, answer=True, question_url='https://www.zhihu.com/question/12')
    with pytest.raises(ValueError):
        platform_url('website', 'https://evil.example/faq', domain='brand.example', answer=True)


def test_observation_never_turns_blocked_or_redirected_pages_into_success():
    url = 'https://www.zhihu.com/question/12/answer/34'
    body = '应先确认设备型号与运行条件，再根据技术手册确认参数和适用范围。'
    def result(html, **kwargs):
        return SimpleNamespace(body=html, status_code=200, error_type=None, final_url=url, **kwargs)
    assert observe_answer(result(f'<p>{body}</p>'), body, url)['state'] == 'content_observed'
    assert observe_answer(result('<title>登录</title>'), body, url)['state'] == 'unavailable'
    assert observe_answer(result('<h1>只有问题标题</h1>'), body, url)['state'] == 'not_observed'
    r = result(f'<p>{body}</p>'); r.final_url = 'https://www.zhihu.com/signin'
    assert observe_answer(r, body, url)['state'] == 'unavailable'
    assert observe_answer(result('<p>是的</p>'), '是的', url)['state'] == 'unavailable'
    assert observe_answer(result('<p>额定功率为15kW，应先确认运行条件。</p>'), '额定功率为1.5kW，应先确认运行条件。', url)['state'] == 'not_observed'
    assert answer_checks('未给出处', [{'id': 1}])
    assert answer_checks('错误引用[F2]', [{'id': 1}])
    assert answer_checks('待补充[F1]', [{'id': 1}])
    assert not answer_checks('先确认型号[F1]', [{'id': 1}])


def database(scenario):
    url = os.environ.get('SEO_USAGE_TEST_DATABASE_URL')
    if not url:
        pytest.skip('requires PostgreSQL')
    async def run():
        schema = 'qa_' + uuid4().hex
        engine = create_async_engine(url, connect_args={'server_settings': {'search_path': schema}})
        try:
            async with engine.begin() as conn:
                await conn.execute(text(f'CREATE SCHEMA "{schema}"'))
                for model in [SeoSite, SeoContentAsset, SeoContentReviewEvent, SeoTask, SeoSerpResult, SeoQuestion, SeoQaFact, SeoQaAnswer, SeoQaPlacement]:
                    table = model.__table__.to_metadata(MetaData())
                    for fk in list(table.foreign_key_constraints):
                        table.constraints.remove(fk)
                    await conn.run_sync(lambda sync: table.create(sync))
            sessions = async_sessionmaker(engine, expire_on_commit=False)
            async with sessions() as db:
                db.add_all([SeoSite(id=i, tenant_id=i, tenant_module_id=i, name='brand', domain=f'brand{i}.example',
                                   canonical_domain=f'brand{i}.example', status='active') for i in [1, 2]])
                await db.commit()
            await scenario(sessions)
        finally:
            async with engine.begin() as conn:
                await conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
            await engine.dispose()
    asyncio.run(run())


CTX = AuthContext(7, 'qa-test', 'operator', 1, {'seo.content': 'edit', 'seo.keywords': 'view'})


def test_database_full_question_answer_evidence_and_placement_lifecycle():
    async def scenario(sessions):
        async with sessions() as db:
            req = api.ImportQuestions(tenant_id=1, site_id=1, items=[{'title': '如何选型？'}])
            first = await api.import_questions(req, CTX, db)
            assert first['created'] == 1
            assert (await api.import_questions(req, CTX, db))['merged'] == 1
            question_id = first['ids'][0]
            fact = await api.create_fact(api.FactInput(tenant_id=1, site_id=1, title='选型要求',
                statement='先确认设备型号与运行条件，再根据技术手册确认参数和适用范围。', source_name='产品手册 v1'), CTX, db)
            body = fact['statement'] + f'[F{fact["id"]}]'
            answer = await api.create_answer(api.AnswerInput(tenant_id=1, site_id=1, question_id=question_id,
                body=body, fact_ids=[fact['id']]), CTX, db)
            replay = await api.create_answer(api.AnswerInput(tenant_id=1, site_id=1, question_id=question_id,
                body=body, fact_ids=[fact['id']]), CTX, db)
            assert replay['id'] == answer['id']
            content = await db.get(SeoContentAsset, answer['content_id'])
            assert await api.require_answer_evidence(db, content)
            with pytest.raises(HTTPException, match='审核'):
                await api.prepare_placement(api.PlacementInput(tenant_id=1, site_id=1, answer_id=answer['id'], platform='zhihu',
                    question_url='https://www.zhihu.com/question/12'), CTX, db)
            from app.api.seo import submit_content_review, decide_content_review, ContentReviewSubmit, ContentReviewDecision
            with patch('app.api.seo_cockpit.metric_values', new=AsyncMock(return_value={'seo.content.published_7d_count': 0})):
                submitted = await submit_content_review(content.id, 1, ContentReviewSubmit(), db, CTX)
            assert submitted['status'] == 'review'
            approved = await decide_content_review(content.id, 1, ContentReviewDecision(decision='approve'), db, CTX)
            assert approved['status'] == 'ready'
            task = await db.scalar(select(SeoTask))
            assert task.status == 'in_progress' and task.completion_evidence is None
            req = api.PlacementInput(tenant_id=1, site_id=1, answer_id=answer['id'], platform='zhihu',
                                     question_url='https://www.zhihu.com/question/12')
            placement = await api.prepare_placement(req, CTX, db)
            duplicate = await api.prepare_placement(req, CTX, db)
            assert duplicate['id'] == placement['id'] and placement['status'] == 'prepared'
            assert (await api.publication_draft(placement['id'], 1, 1, CTX, db))['body'] == fact['statement']
            with pytest.raises(HTTPException):
                await api.receipt(placement['id'], api.ReceiptInput(tenant_id=1, site_id=1, version=1,
                    answer_url='https://www.zhihu.com/question/13/answer/14'), CTX, db)
            url = 'https://www.zhihu.com/question/12/answer/14'
            receipt = await api.receipt(placement['id'], api.ReceiptInput(tenant_id=1, site_id=1, version=1, answer_url=url), CTX, db)
            assert receipt['status'] == 'reported' and receipt['observations'] == []
            page = SimpleNamespace(body=f'<p>{fact["statement"]}</p>', final_url=url, status_code=200, error_type=None)
            with patch('app.seo_backlinks.fetch_backlink_page', new=AsyncMock(return_value=page)):
                observed = await api.verify(placement['id'], api.Scoped(tenant_id=1, site_id=1), CTX, db)
            assert observed['status'] == 'content_observed' and content.status == 'ready'
            assert '不证明账号归属' in observed['observations'][0]['meaning']
            with pytest.raises(HTTPException) as rate:
                await api.verify(placement['id'], api.Scoped(tenant_id=1, site_id=1), CTX, db)
            assert rate.value.status_code == 429
            await db.rollback()
            await api.edit_fact(fact['id'], api.FactEdit(tenant_id=1, site_id=1, version=1,
                title='新手册', statement='资料已经更新', source_name='v2'), CTX, db)
            content = await db.get(SeoContentAsset, answer['content_id'])
            with pytest.raises(HTTPException, match='更新'):
                await api.require_answer_evidence(db, content)
            issues = await api.maintenance(1, 1, CTX, db)
            assert issues['items'][0]['answer_id'] == answer['id']
            stale = await api.placements(1, 1, CTX, db)
            assert not stale[0]['publishable']
            with pytest.raises(HTTPException):
                await api.publication_draft(placement['id'], 1, 1, CTX, db)
    database(scenario)


def test_database_scope_expiry_and_stale_edits_fail_closed():
    async def scenario(sessions):
        async with sessions() as db:
            with pytest.raises(HTTPException) as cross:
                await api.import_questions(api.ImportQuestions(tenant_id=2, site_id=2, items=[{'title': '其他客户'}]), CTX, db)
            assert cross.value.status_code == 403
            view = AuthContext(8, 'viewer', 'view', 1, {'seo.content': 'view'})
            with pytest.raises(HTTPException):
                await api.create_fact(api.FactInput(tenant_id=1, site_id=1, title='资料', statement='原文', source_name='手册'), view, db)
            db.add(SeoQaFact(id=100, tenant_id=2, site_id=2, title='外部客户', statement='不应泄露', source_name='资料'))
            db.add(SeoQaFact(id=101, tenant_id=1, site_id=1, title='已过期', statement='旧资料', source_name='资料', expires_at=datetime.now(timezone.utc)-timedelta(days=1)))
            await db.commit()
            for fact_id in [100, 101]:
                with pytest.raises(HTTPException):
                    await api.fact_snapshots(db, 1, 1, [fact_id])
            imported = await api.import_questions(api.ImportQuestions(tenant_id=1, site_id=1, items=[{'title': '如何排障'}]), CTX, db)
            req = api.QuestionEdit(tenant_id=1, site_id=1, version=1, topic='测试', intent='learn', relevance=5, status='selected')
            await api.edit_question(imported['ids'][0], req, CTX, db)
            with pytest.raises(HTTPException) as stale:
                await api.edit_question(imported['ids'][0], req, CTX, db)
            assert stale.value.status_code == 409
    database(scenario)


def test_database_domestic_discovery_is_scoped_and_not_fake_heat():
    async def scenario(sessions):
        async with sessions() as db:
            for i, (tenant, engine, title) in enumerate([(1, 'baidu', '如何选型？'), (2, 'baidu', '如何泄露？'),
                                                       (1, 'google', '如何优化？'), (1, 'baidu', '普通文章标题')], 1):
                db.add(SeoSerpResult(tenant_id=tenant, site_id=tenant, keyword_id=i, engine=engine, device='desktop',
                    rank=1, title=title, result_url=f'https://brand{tenant}.example/{i}', captured_at=datetime.utcnow()))
            await db.commit()
            result = await api.discover_questions(api.Scoped(tenant_id=1, site_id=1), CTX, db)
            assert result['created'] == 1
            rows = await api.questions(1, 1, '', None, 1, 30, CTX, db)
            assert rows['total'] == 1 and rows['items'][0]['heat'] is None
            assert rows['items'][0]['sources'][0]['kind'] == 'serp'
    database(scenario)


def test_qa_prompt_does_not_reward_length_or_keyword_stuffing():
    from app.api.seo import SeoContentAssistRequest, _seo_ai_prompt
    req = SeoContentAssistRequest(tenant_id=1, site_id=1, action='generate', mode='qa')
    system, user = _seo_ai_prompt(req, SimpleNamespace(name='品牌', industry=None, business_desc=None, brand_terms=[]), [])
    assert '[F编号]' in system and '不得编造' in system
    assert '必须逐字' not in system and '不强制逐字' in user
