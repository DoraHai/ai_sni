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
from app.models.seo import SeoContentAsset, SeoSerpResult, SeoContentReviewEvent, SeoBacklink, SeoAiOperation
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
                for model in [SeoAiOperation, SeoBacklink, SeoSite, SeoContentAsset, SeoContentReviewEvent, SeoTask, SeoSerpResult, SeoQuestion, SeoQaFact, SeoQaAnswer, SeoQaPlacement]:
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
            assert (await api.question_detail(question_id,1,1,CTX,db))['coverage']['state']=='unanswered'
            fact = await api.create_fact(api.FactInput(tenant_id=1, site_id=1, title='选型要求',
                statement='先确认设备型号与运行条件，再根据技术手册确认参数和适用范围。', source_name='产品手册 v1'), CTX, db)
            body = fact['statement'] + f'[F{fact["id"]}]'
            answer = await api.create_answer(api.AnswerInput(tenant_id=1, site_id=1, question_id=question_id,
                body=body, fact_ids=[fact['id']]), CTX, db)
            replay = await api.create_answer(api.AnswerInput(tenant_id=1, site_id=1, question_id=question_id,
                body=body, fact_ids=[fact['id']]), CTX, db)
            assert replay['id'] == answer['id']
            assert (await api.question_detail(question_id,1,1,CTX,db))['coverage']['state']=='draft_only'
            assert (await api.planning(1,1,CTX,db))['coverage_gap_count']==1
            with pytest.raises(HTTPException):
                await api.question_detail(question_id,2,2,CTX,db)
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
            assert (await api.question_detail(question_id,1,1,CTX,db))['coverage']['state']=='reviewed_current'
            assert (await api.planning(1,1,CTX,db))['valid_covered_count']==1
            checked=(await api.answers(1,1,question_id,CTX,db))[0]['quality']
            assert checked['method']=='rules' and checked['blocking_issues']==[]
            task = await db.scalar(select(SeoTask))
            assert task.status == 'in_progress' and task.completion_evidence is None
            req = api.PlacementInput(tenant_id=1, site_id=1, answer_id=answer['id'], platform='zhihu',
                                     question_url='https://www.zhihu.com/question/12')
            placement = await api.prepare_placement(req, CTX, db)
            duplicate = await api.prepare_placement(req, CTX, db)
            assert duplicate['id'] == placement['id'] and placement['status'] == 'prepared'
            assert (await api.publication_draft(placement['id'], 1, 1, CTX, db))['body'] == fact['statement']
            exported=await api.assistant_task(placement['id'],1,1,CTX,db)
            assert exported['body']==fact['statement'] and exported['platform']=='zhihu'
            viewer=AuthContext(8,'viewer','view',1,{'seo.content':'view'})
            with pytest.raises(HTTPException) as denied:
                await api.assistant_task(placement['id'],1,1,viewer,db)
            assert denied.value.status_code==403
            with pytest.raises(HTTPException):
                await api.assistant_task(placement['id'],2,2,CTX,db)
            assert exported['kind']=='seo_qa_assist' and exported['content_version']==content.version_count
            with pytest.raises(HTTPException):
                await api.receipt(placement['id'], api.ReceiptInput(tenant_id=1, site_id=1, version=1,
                    answer_url='https://www.zhihu.com/question/13/answer/14'), CTX, db)
            url = 'https://www.zhihu.com/question/12/answer/14'
            payload={key:exported[key] for key in ['tenant_id','site_id','placement_id','version','content_version','platform','question_url']}
            payload.update(kind='seo_qa_receipt',schema_version=1,answer_url=url)
            for changed in [{'placement_id':999},{'content_version':999},{'version':999},
                            {'question_url':'https://www.zhihu.com/question/999'},
                            {'answer_url':'https://www.zhihu.com/question/999/answer/14'}]:
                with pytest.raises(HTTPException):
                    await api.assistant_receipt(placement['id'],api.AssistantReceiptInput(**{**payload,**changed}),CTX,db)
            with pytest.raises(HTTPException) as denied:
                await api.assistant_receipt(placement['id'],api.AssistantReceiptInput(**payload),viewer,db)
            assert denied.value.status_code==403
            with pytest.raises(HTTPException):
                await api.assistant_receipt(placement['id'],api.AssistantReceiptInput(**{**payload,'tenant_id':2,'site_id':2}),CTX,db)
            receipt = await api.assistant_receipt(placement['id'],api.AssistantReceiptInput(**payload),CTX,db)
            with pytest.raises(HTTPException) as stale_receipt:
                await api.assistant_receipt(placement['id'],api.AssistantReceiptInput(**payload),CTX,db)
            assert stale_receipt.value.status_code==409
            assert receipt['status'] == 'reported' and receipt['observations'] == []
            page = SimpleNamespace(body=f'<p>{fact["statement"]}</p>', final_url=url, status_code=200, error_type=None)
            with patch('app.seo_backlinks.fetch_backlink_page', new=AsyncMock(return_value=page)):
                observed = await api.verify(placement['id'], api.Scoped(tenant_id=1, site_id=1), CTX, db)
            assert observed['status'] == 'content_observed' and content.status == 'ready'
            detail=await api.question_detail(question_id,1,1,CTX,db)
            assert detail['coverage']['state']=='observed' and detail['placement_total']==1
            assert (await api.planning(1,1,CTX,db))['observed_question_count']==1
            assert (await api.question_detail(question_id,1,1,viewer,db))['coverage']['observed_answer_count']==1
            stored=await db.get(SeoQaPlacement,placement['id']);original=list(stored.observations)
            stored.observations=original+[{'state':'unavailable','checked_at':datetime.now(timezone.utc).isoformat()}]
            await db.flush()
            assert (await api.question_detail(question_id,1,1,CTX,db))['coverage']['state']=='reviewed_current'
            stored.observations=original;stored.content_version+=1;await db.flush()
            assert (await api.question_detail(question_id,1,1,CTX,db))['coverage']['observed_answer_count']==0
            stored.content_version-=1;await db.flush()

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
            detail=await api.question_detail(question_id,1,1,CTX,db)
            assert detail['coverage']['state']=='needs_update' and detail['coverage']['observed_answer_count']==0
            plan=await api.planning(1,1,CTX,db)
            assert plan['valid_covered_count']==0 and plan['coverage_gap_count']==1
            assert (await api.answers(1,1,question_id,CTX,db))[0]['quality']['blocking_issues']
            with pytest.raises(HTTPException):
                await api.publication_draft(placement['id'], 1, 1, CTX, db)
            with pytest.raises(HTTPException):
                await api.assistant_task(placement['id'],1,1,CTX,db)
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
                                                       (1, 'google', '如何优化？'), (1, 'baidu', '普通文章标题'), (1, 'baidu', '？？？')], 1):
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


def test_database_replay_checks_current_body_and_finds_later_valid_answer():
    async def scenario(sessions):
        async with sessions() as db:
            imported = await api.import_questions(api.ImportQuestions(tenant_id=1, site_id=1,
                items=[{'title': '如何确认设备运行条件？'}]), CTX, db)
            req = api.AnswerInput(tenant_id=1, site_id=1, question_id=imported['ids'][0], body='原始回答正文')
            first = await api.create_answer(req, CTX, db)
            content = await db.get(SeoContentAsset, first['content_id'])
            # The shared content editor may change the effective body without
            # changing the QA evidence snapshot. It must not satisfy a retry.
            content.humanized_content = '其他编辑器已经修改的正文'
            content.version_count += 1
            await db.commit()
            second = await api.create_answer(req, CTX, db)
            assert second['id'] != first['id']
            assert (await db.get(SeoContentAsset, first['content_id'])).humanized_content == '其他编辑器已经修改的正文'
            assert (await db.get(SeoContentAsset, second['content_id'])).draft == req.body
            replay = await api.create_answer(req, CTX, db)
            assert replay['id'] == second['id']
            assert len(list(await db.scalars(select(SeoQaAnswer)))) == 2
    database(scenario)


def test_question_tree_and_conservative_similarity_candidates():
    from app.seo_qa import question_plan
    rows = [{'id': i, 'title': title, 'topic': '设备选型', 'intent': 'learn', 'answer_count': int(i == 1),
             'reviewed_answer_count': 0} for i, title in enumerate([
                 '减速机选型需要确认哪些运行条件？', '减速机选型需要确认什么运行条件？',
                 '1.5kW 减速机选型需要确认哪些运行条件？', '15kW 减速机选型需要确认哪些运行条件？'], 1)]
    result = question_plan(rows)
    assert result['groups'][0]['question_count'] == 4
    assert result['unanswered_count'] == 3 and result['reviewed_count'] == 0
    assert [(pair['left_id'], pair['right_id']) for pair in result['similar_pairs']] == [(1, 2)]
    assert len(rows) == 4  # Suggestions do not remove or merge original questions.


def test_database_planning_scope_coverage_and_atomic_batch_updates():
    async def scenario(sessions):
        async with sessions() as db:
            imported = await api.import_questions(api.ImportQuestions(tenant_id=1, site_id=1,
                items=[{'title': '如何选择减速机'}, {'title': '如何选择电机'}]), CTX, db)
            ids = sorted(imported['ids'])
            db.add(SeoQuestion(id=1000, tenant_id=2, site_id=2, title='其他租户资料', fingerprint='foreign', topic='隐藏'))
            db.add(SeoQuestion(id=1001, tenant_id=1, site_id=1, title='归档资料', fingerprint='archived', status='archived'))
            await db.commit()
            plan = await api.planning(1, 1, CTX, db)
            assert plan['total'] == 2 and plan['included'] == 2 and not plan['truncated']
            assert plan['unanswered_count'] == 2
            answer = await api.create_answer(api.AnswerInput(tenant_id=1, site_id=1, question_id=ids[0], body='待审核草稿'), CTX, db)
            plan = await api.planning(1, 1, CTX, db)
            assert plan['unanswered_count'] == 1 and plan['reviewed_count'] == 0
            content = await db.get(SeoContentAsset, answer['content_id'])
            content.status = 'ready'
            await db.commit()
            plan = await api.planning(1, 1, CTX, db)
            assert plan['reviewed_count'] == 1
            refs = [{'id': i, 'version': 1} for i in ids]
            with pytest.raises(HTTPException) as stale:
                await api.batch_questions(api.BatchQuestions(tenant_id=1, site_id=1,
                    items=[refs[0], {'id': ids[1], 'version': 99}], changes={'topic': '错误分类'}), CTX, db)
            assert stale.value.status_code == 409
            assert (await db.get(SeoQuestion, ids[0])).topic == '未分类'
            with pytest.raises(HTTPException) as cross:
                await api.batch_questions(api.BatchQuestions(tenant_id=1, site_id=1,
                    items=[refs[0], {'id': 1000, 'version': 1}], changes={'owner': '不应写入'}), CTX, db)
            assert cross.value.status_code == 404
            assert (await db.get(SeoQuestion, ids[0])).owner is None
            view = AuthContext(8, 'viewer', 'view', 1, {'seo.content': 'view'})
            with pytest.raises(HTTPException) as readonly:
                await api.batch_questions(api.BatchQuestions(tenant_id=1, site_id=1, items=refs, changes={'topic': '设备'}), view, db)
            assert readonly.value.status_code == 403
            changed = await api.batch_questions(api.BatchQuestions(tenant_id=1, site_id=1, items=refs,
                changes={'topic': '设备选型', 'owner': '技术支持', 'status': 'selected'}), CTX, db)
            assert changed['updated'] == 2
            for question_id in ids:
                row = await db.get(SeoQuestion, question_id)
                assert row.topic == '设备选型' and row.version == 2 and row.sources
            plan = await api.planning(1, 1, CTX, db)
            assert len(plan['groups']) == 1
            assert plan['groups'][0]['topic'] == '设备选型'
    database(scenario)


def test_batch_contract_rejects_empty_duplicate_and_null_changes():
    for changes in [{}, {'topic': None}, {'status': None}]:
        with pytest.raises(ValidationError):
            api.BatchQuestions(tenant_id=1, site_id=1, items=[{'id': 1, 'version': 1}], changes=changes)
    with pytest.raises(ValidationError):
        api.BatchQuestions(tenant_id=1, site_id=1, items=[{'id': 1, 'version': 1}]*2, changes={'owner': None})
    assert api.PlanningChanges(owner=None).model_dump(exclude_unset=True) == {'owner': None}


@pytest.mark.parametrize('mode', ['link', 'absent', 'internal', 'blocked', 'missing_body', 'permission', 'failure'])
def test_qa_backlink_return_uses_one_fetch_and_preserves_observation(mode):
    async def scenario(sessions):
        async with sessions() as db:
            body = '应先确认设备型号与运行条件，再根据技术手册确认参数和适用范围。'
            url = 'https://brand1.example/faq' if mode == 'internal' else 'https://www.zhihu.com/question/12/answer/34'
            row = SeoQaPlacement(tenant_id=1, site_id=1, answer_id=1, platform='zhihu',
                answer_url=url, content_version=1, body=body)
            db.add(row)
            await db.commit()
            html = f'<p>{body}</p><a href="https://brand1.example/product" rel="nofollow ugc">官网</a>'
            if mode == 'absent': html = f'<p>{body}</p>brand1.example'
            if mode == 'blocked': html = '<title>登录</title>'
            if mode == 'missing_body': html = '<p>另一个回答</p><a href="https://brand1.example/product">官网</a>'
            fetched = SimpleNamespace(body=html, status_code=200, error_type=None, final_url=url)
            ctx = CTX if mode == 'permission' else AuthContext(7, 'qa-test', 'operator', 1, {'seo.content':'edit', 'seo.links':'edit'})
            async def fail(*args, **kwargs):
                # A real SQL error verifies that the savepoint repairs the session.
                await db.execute(text('SELECT * FROM nonexistent_qa_backlink_table'))
            from contextlib import nullcontext
            failure = patch('app.seo_backlinks.discover_backlinks', new=fail) if mode == 'failure' else nullcontext()
            with patch('app.seo_backlinks.fetch_backlink_page', new=AsyncMock(return_value=fetched)) as fetch, failure:
                result = await api.verify(row.id, api.Scoped(tenant_id=1, site_id=1), ctx, db)
                fetch.assert_awaited_once_with(url)
            evidence = result['observations'][-1]['backlink_discovery']
            expected = {'link':'readable', 'absent':'readable', 'internal':'internal', 'blocked':'not_checked',
                        'missing_body':'not_checked', 'permission':'permission_required', 'failure':'unavailable'}
            assert evidence['state'] == expected[mode]
            links = list((await db.scalars(select(SeoBacklink))).all())
            assert len(links) == (1 if mode == 'link' else 0)
            if mode == 'link':
                assert links[0].tenant_id == 1 and links[0].site_id == 1
                assert 'nofollow' in links[0].verification['rel']
                assert evidence['found'] == evidence['created'] == 1
                row.observations = []
                await db.commit()
                with patch('app.seo_backlinks.fetch_backlink_page', new=AsyncMock(return_value=fetched)):
                    replay = await api.verify(row.id, api.Scoped(tenant_id=1, site_id=1), ctx, db)
                assert replay['observations'][-1]['backlink_discovery']['created'] == 0
            if mode == 'failure':
                assert result['status'] == 'content_observed'
                await db.refresh(row)
                assert row.observations[-1]['backlink_discovery']['state'] == 'unavailable'
    database(scenario)


@pytest.mark.parametrize('case', ['missing_url', 'first', 'fresh', 'due', 'invalid_time', 'unavailable', 'body_changed', 'target_changed', 'unchanged'])
def test_placement_followup_distinguishes_evidence_and_unknown(case):
    from app.seo_qa import placement_followup
    now = datetime(2026, 9, 6, tzinfo=timezone.utc)
    url = 'https://www.zhihu.com/question/12/answer/34'
    old = {'state':'content_observed', 'checked_at':now.isoformat(),
           'backlink_discovery':{'state':'readable', 'links':[{'target_url':'https://brand.example/a'}]}}
    last = {**old}
    history = [old, last]
    if case == 'missing_url': url = None
    if case == 'first': history = []
    if case == 'due': last['checked_at'] = (now-timedelta(days=7)).isoformat()
    if case == 'invalid_time': last['checked_at'] = 'invalid'
    if case == 'unavailable': last.update(state='unavailable', backlink_discovery={'state':'not_checked'})
    if case == 'body_changed': last.update(state='not_observed', backlink_discovery={'state':'not_checked'})
    if case == 'target_changed': last['backlink_discovery'] = {'state':'readable','links':[{'target_url':'https://brand.example/b'}]}
    result = placement_followup(url, history, now=now)
    assert result['needed'] == (case not in {'fresh','unchanged'})
    reasons = ' '.join(result['reasons'])
    if case == 'unavailable':
        assert '不代表回答已删除' in reasons and '链接发生变化' not in reasons
    if case == 'body_changed': assert '此前正文匹配' in reasons
    if case == 'target_changed': assert '新增 1 条，未再发现 1 条' in reasons


@pytest.mark.parametrize('mode', ['normal', 'fetch_failure', 'no_entitlement', 'locked'])
def test_scheduled_qa_is_bounded_scoped_and_does_not_retry_fresh_receipts(mode):
    from app import seo_monitoring_jobs as jobs
    async def scenario(sessions):
        body = '应先确认设备型号与运行条件，再根据技术手册确认参数和适用范围。'
        old = (datetime.now(timezone.utc)-timedelta(days=8)).isoformat()
        async with sessions() as db:
            for i in range(1, 25):
                db.add(SeoQaPlacement(id=i, tenant_id=1, site_id=1, answer_id=i, platform='zhihu',
                    content_version=1, body=body, answer_url=f'https://www.zhihu.com/question/12/answer/{i}',
                    observations=[{'state':'content_observed','checked_at':old}]))
            db.add(SeoQaPlacement(id=25, tenant_id=2, site_id=2, answer_id=25, platform='zhihu',
                content_version=1, body=body, answer_url='https://www.zhihu.com/question/12/answer/25',
                observations=[{'state':'content_observed','checked_at':old}]))
            db.add(SeoQaPlacement(id=26, tenant_id=1, site_id=1, answer_id=26, platform='zhihu',
                content_version=1, body=body, answer_url='https://www.zhihu.com/question/12/answer/26', observations=[]))
            await db.commit()
        async def fetch(url):
            if mode == 'fetch_failure' and url.endswith('/1'): raise RuntimeError('temporary fetch error')
            return SimpleNamespace(body=f'<p>{body}</p>',final_url=url,status_code=200,error_type=None)
        async with sessions() as lock_session:
            if mode == 'locked':
                await lock_session.scalar(select(SeoQaPlacement).where(SeoQaPlacement.id == 1).with_for_update())
            with patch.object(jobs, 'async_session_factory', sessions), \
                 patch.object(jobs, 'list_active_module_tenants', new=AsyncMock(return_value=[] if mode=='no_entitlement' else [SimpleNamespace(id=1)])), \
                 patch('app.seo_backlinks.fetch_backlink_page', new=AsyncMock(side_effect=fetch)) as mocked:
                first = await jobs.verify_scheduled_qa()
                assert first['checked'] == (0 if mode=='no_entitlement' else 19 if mode=='locked' else 20)
                assert first['skipped'] == (1 if mode=='locked' else 0)
                await jobs.verify_scheduled_qa()
                assert mocked.await_count == (0 if mode=='no_entitlement' else 23 if mode=='locked' else 24)
                assert (await jobs.verify_scheduled_qa())['checked'] == 0
            await lock_session.rollback()
        async with sessions() as db:
            assert (await db.get(SeoQaPlacement,25)).version == 1
            assert not (await db.get(SeoQaPlacement,26)).observations
            row = await db.get(SeoQaPlacement,1)
            if mode == 'fetch_failure':
                assert row.status == 'unavailable' and row.observations[-1]['source'] == 'scheduled'
            if mode == 'normal': assert row.status == 'content_observed' and row.version == 2
    database(scenario)


def test_body_only_recheck_preserves_last_link_change_or_failure():
    from app.seo_qa import placement_followup
    now = datetime.now(timezone.utc)
    def observation(discovery):
        return {'state':'content_observed','checked_at':now.isoformat(),'backlink_discovery':discovery}
    before = observation({'state':'readable','links':[{'target_url':'https://brand.example/a'}]})
    after = observation({'state':'readable','links':[]})
    body_only = observation({'state':'not_checked'})
    result = placement_followup('https://public.example/answer', [before,after,body_only], now=now)
    assert any('未再发现 1 条' in reason for reason in result['reasons'])
    failed = observation({'state':'unavailable'})
    result = placement_followup('https://public.example/answer', [before,failed,body_only], now=now)
    assert any('外链暂时无法核验' in reason for reason in result['reasons'])
    # A subsequent successful link check supersedes the old failure.
    result = placement_followup('https://public.example/answer', [before,failed,body_only,before], now=now)
    assert not result['needed']


@pytest.mark.parametrize('mode', ['success', 'invalid', 'foreign', 'stale'])
def test_semantic_analysis_is_scoped_validated_and_refunds_invalid_output(mode):
    async def scenario(sessions):
        async with sessions() as db:
            result = await api.import_questions(api.ImportQuestions(tenant_id=1,site_id=1,
                items=[{'title':'设备为何无法启动？'},{'title':'机器开不了机怎么办？'}]), CTX, db)
            ids = result['ids']
            req = api.SemanticQuestions(tenant_id=2 if mode=='foreign' else 1,site_id=1,
                request_id='semantic-test-123',items=[{'id':i,'version':99 if mode=='stale' else 1} for i in ids])
            async def generate(*args, **kwargs):
                kwargs['usage_receipt'].update(operation_id='op-test',date='2026-09-06')
                return {'pairs':[{'left_id':ids[0],'right_id':99999 if mode=='invalid' else ids[1],'reason':'同样询问无法启动的排查方法'}]}
            async def settle(*args, **kwargs): return kwargs['result']
            with patch('app.ai.deepseek.is_enabled', return_value=True), \
                 patch('app.api.seo._limited_seo_chat_json', new=AsyncMock(side_effect=generate)) as ai, \
                 patch('app.api.seo._refund_failed_seo_ai_request', new=AsyncMock()) as refund, \
                 patch('app.seo_ai_operations.settle_seo_ai_operation', new=AsyncMock(side_effect=settle)):
                if mode=='success':
                    response=await api.semantic_questions(req,CTX,db)
                    assert len(response['pairs'])==1
                    assert response['pairs'][0]['left_title']==(await db.get(SeoQuestion,ids[0])).title
                    refund.assert_not_awaited()
                else:
                    with pytest.raises(HTTPException) as error:
                        await api.semantic_questions(req,CTX,db)
                    if mode=='invalid':
                        assert error.value.status_code==502
                        refund.assert_awaited_once()
                    else:
                        ai.assert_not_awaited()
                for i in ids:
                    assert (await db.get(SeoQuestion,i)).version==1
    database(scenario)


def test_semantic_result_rejects_coerced_ids_and_deduplicates_pairs():
    from app.seo_qa import validated_semantic_pairs
    questions=[{'id':1,'title':'问题一'},{'id':2,'title':'问题二'}]
    pair={'left_id':1,'right_id':2,'reason':'相同需求'}
    assert len(validated_semantic_pairs({'pairs':[pair,{**pair,'left_id':2,'right_id':1}]},questions))==1
    for bad in [True,'1',1.0,3]:
        with pytest.raises(ValueError):
            validated_semantic_pairs({'pairs':[{**pair,'left_id':bad}]},questions)



def test_semantic_history_recovery_is_actor_site_scoped_and_read_only():
    async def scenario(sessions):
        async with sessions() as db:
            now=datetime.now(timezone.utc).replace(tzinfo=None)
            for i, actor, site, kind, status, age in [(1,'7',1,'qa_semantic','succeeded',0),
                (2,'8',1,'qa_semantic','succeeded',0),(3,'7',2,'qa_semantic','succeeded',0),
                (4,'7',1,'content_assist','succeeded',0),(5,'7',1,'qa_semantic','running',0),
                (6,'7',1,'qa_semantic','succeeded',31)]:
                db.add(SeoAiOperation(id=str(i),tenant_id=1,site_id=site,actor=actor,kind=kind,status=status,
                    request_key=str(i),request_hash='a'*64,charged_on='2026-09-06',expires_at=now,
                    completed_at=now-timedelta(days=age),result={'pairs':[],'questions':[]}))
            await db.commit()
            history=await api.semantic_history(1,1,CTX,db)
            assert {r['id'] for r in history['items']}=={'1','5','6'}
            assert {r['id'] for r in history['items'] if r['has_result']}=={'1'}
            recovered=await api.semantic_result('1',1,1,CTX,db)
            assert recovered['action']=='qa_semantic'
            for i in ['2','3','4','5','6']:
                with pytest.raises(HTTPException): await api.semantic_result(i,1,1,CTX,db)
            assert (await db.get(SeoAiOperation,'1')).status=='succeeded'
    database(scenario)


def test_demand_csv_preserves_zero_and_requires_complete_compatible_window():
    csv='title,source_kind,source_name,count,metric,period_start,period_end,definition\n如何排查,site_search,站内搜索,0,searches,2026-01-01,2026-01-07,按搜索事件计数'
    req=api.ImportQuestions(tenant_id=1,site_id=1,csv=csv)
    assert req.items[0].source.count==0
    for invalid in [csv.replace(',0,',',1.5,'),csv.replace(',searches,',',clicks,'),csv.replace('2026-01-07','2025-01-01'),csv.replace(',按搜索事件计数',''),csv.replace('2026-01-07','2099-01-01')]:
        with pytest.raises((ValidationError,ValueError)): api.ImportQuestions(tenant_id=1,site_id=1,csv=invalid)


def test_demand_import_replay_correction_and_separate_periods():
    async def scenario(sessions):
        async with sessions() as db:
            source={'kind':'customer','name':'工单导出','count':12,'metric':'inquiries',
                    'period_start':'2026-01-01','period_end':'2026-01-07','definition':'有效工单去重'}
            async def import_source(value):
                return await api.import_questions(api.ImportQuestions(tenant_id=1,site_id=1,
                    items=[{'title':'无法启动如何排查','source':value}]),CTX,db)
            first=await import_source(source);row=await db.get(SeoQuestion,first['ids'][0])
            assert row.sources[0]['count']==12
            await import_source(source);await db.refresh(row)
            assert row.version==1 and len(row.sources)==1
            await import_source({**source,'count':15});await db.refresh(row)
            assert row.sources[0]['count']==15 and row.version==2
            await import_source({**source,'period_start':'2026-01-08','period_end':'2026-01-14'});await db.refresh(row)
            assert len(row.sources)==2 and row.version==3
    database(scenario)



def test_import_preview_is_read_only_and_stale_token_cannot_overwrite():
    async def scenario(sessions):
        async with sessions() as db:
            source={'kind':'customer','name':'工单','count':12,'metric':'inquiries',
                'period_start':'2026-01-01','period_end':'2026-01-07','definition':'有效工单计数'}
            def req(count, token=None):
                return api.ImportQuestions(tenant_id=1,site_id=1,items=[{'title':'如何排查故障','source':{**source,'count':count}}],preview_token=token)
            preview=await api.preview_questions(req(12),CTX,db)
            assert preview['summary']['new_question']==1
            assert await db.scalar(select(SeoQuestion)) is None
            imported=await api.import_questions(req(12,preview['preview_token']),CTX,db)
            row=await db.get(SeoQuestion,imported['ids'][0])
            correction=await api.preview_questions(req(15),CTX,db)
            assert correction['rows'][0]['previous_count']==12 and correction['summary']['correction']==1
            assert row.sources[0]['count']==12
            await api.import_questions(req(20),CTX,db)
            with pytest.raises(HTTPException) as error:
                await api.import_questions(req(15,correction['preview_token']),CTX,db)
            assert error.value.status_code==409
            await db.rollback();await db.refresh(row)
            assert row.sources[0]['count']==20
            duplicate=await api.preview_questions(req(20),CTX,db)
            assert duplicate['summary']['unchanged']==1
    database(scenario)


def test_import_rejects_duplicate_headers_uneven_rows_and_conflicting_window():
    for value in ['title,title\n如何处理,如何处理','title,topic\n如何处理','title\n如何处理,多余列']:
        with pytest.raises((ValueError,ValidationError)): api.ImportQuestions(tenant_id=1,site_id=1,csv=value)
    base='title,source_kind,source_name,count,metric,period_start,period_end,definition\n'
    row='如何排查,customer,工单,12,inquiries,2026-01-01,2026-01-07,按工单计数'
    with pytest.raises(ValidationError,match='冲突'):
        api.ImportQuestions(tenant_id=1,site_id=1,csv=base+row+'\n'+row.replace(',12,',',15,'))
    with pytest.raises(ValidationError,match='第 2 条记录'):
        api.ImportQuestions(tenant_id=1,site_id=1,csv=base+row.replace('2026-01-07','bad-date'))


def test_quality_hints_are_explainable_bounded_and_not_a_truth_score():
    from app.seo_qa import answer_quality
    report=answer_quality('价格为100元。\n保证永不损坏。\n额定功率15kW[F1]',[{'id':1}],[])
    assert [(h['code'],h['paragraph']) for h in report['hints']]==[('numeric_claim',1),('absolute_claim',2)]
    assert report['cited_fact_count']==1 and report['linked_fact_count']==1
    assert report['method']=='rules' and 'score' not in report and report['manual_review']
    limited=answer_quality('价格100元\n'*60,[],['缺少资料'])
    assert limited['hints_total']==60 and len(limited['hints'])==50 and limited['blocking_issues']==['缺少资料']
