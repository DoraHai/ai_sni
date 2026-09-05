"""Question workbench. Reuses SEO content review; publishing is explicitly assisted."""
from datetime import datetime, timezone, timedelta
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, PositiveInt, field_validator, model_validator
from sqlalchemy import select, func
from sqlalchemy.dialects.postgresql import insert
from app.database import get_session
from app.security.auth import require_scoped_auth
from app.api.seo_cockpit import scope
from app.models.seo import SeoContentAsset, SeoSerpResult
from app.models.seo_qa import SeoQuestion, SeoQaFact, SeoQaAnswer, SeoQaPlacement
from app.seo_qa import (PLATFORMS, fingerprint, public_url, platform_url, parse_questions_csv,
                        fact_is_current, body_hash, answer_checks, observe_answer)

router = APIRouter(prefix='/qa', tags=['SEO questions'])
Auth = Depends(require_scoped_auth)
Db = Depends(get_session)


class Scoped(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    tenant_id: PositiveInt
    site_id: PositiveInt


class Source(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    kind: Literal['manual', 'customer', 'import', 'suggestion'] = 'manual'
    name: str = Field(default='人工录入', min_length=1, max_length=240)
    url: str | None = Field(None, max_length=2000)

    @field_validator('url')
    @classmethod
    def safe_url(cls, value):
        return public_url(value) if value else None


class QuestionItem(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    title: str = Field(min_length=2, max_length=300)
    topic: str = Field(default='未分类', min_length=1, max_length=120)
    source: Source = Field(default_factory=Source)

    @field_validator('title')
    @classmethod
    def valid_title(cls, value):
        fingerprint(value)
        return value


class ImportQuestions(Scoped):
    items: list[QuestionItem] = Field(default_factory=list, max_length=200)
    csv: str | None = Field(None, max_length=500_000)

    @model_validator(mode='after')
    def import_input(self):
        if self.csv is not None:
            if self.items:
                raise ValueError('CSV 与列表不能同时提交')
            self.items = [QuestionItem(**item) for item in parse_questions_csv(self.csv)]
        if not self.items:
            raise ValueError('请填写需要导入的问题')
        return self


class QuestionEdit(Scoped):
    version: PositiveInt
    topic: str = Field(min_length=1, max_length=120)
    intent: Literal['learn', 'compare', 'buy', 'troubleshoot']
    relevance: int = Field(ge=0, le=5)
    status: Literal['open', 'selected', 'archived']
    owner: str | None = Field(None, max_length=120)


class FactInput(Scoped):
    title: str = Field(min_length=1, max_length=240)
    statement: str = Field(min_length=1, max_length=10000)
    source_name: str = Field(min_length=1, max_length=240)
    source_url: str | None = Field(None, max_length=2000)
    expires_at: datetime | None = None
    status: Literal['active', 'retired'] = 'active'

    @field_validator('source_url')
    @classmethod
    def safe_url(cls, value):
        return public_url(value) if value else None

    @field_validator('expires_at')
    @classmethod
    def aware_expiry(cls, value):
        if value is not None and value.tzinfo is None:
            raise ValueError('过期时间必须包含时区')
        return value


class FactEdit(FactInput):
    version: PositiveInt


class AnswerInput(Scoped):
    question_id: PositiveInt
    format: Literal['short', 'detailed', 'steps', 'comparison', 'faq'] = 'short'
    body: str = Field(min_length=1, max_length=80000)
    fact_ids: list[PositiveInt] = Field(default_factory=list, max_length=20)
    content_version: PositiveInt | None = None


class PlacementInput(Scoped):
    answer_id: PositiveInt
    platform: Literal['website', 'zhihu', 'baidu_zhidao', 'csdn_qa']
    question_url: str | None = Field(None, max_length=2000)
    scheduled_at: datetime | None = None

    @field_validator('scheduled_at')
    @classmethod
    def aware_schedule(cls, value):
        if value is not None and value.tzinfo is None:
            raise ValueError('计划时间必须包含时区')
        return value


class ReceiptInput(Scoped):
    version: PositiveInt
    answer_url: str = Field(min_length=1, max_length=2000)


class MetricsInput(Scoped):
    version: PositiveInt
    views: int | None = Field(None, ge=0)
    likes: int | None = Field(None, ge=0)
    comments: int | None = Field(None, ge=0)
    source_url: str = Field(min_length=1, max_length=2000)
    as_of: datetime

    @field_validator('source_url')
    @classmethod
    def safe_url(cls, value):
        return public_url(value)

    @field_validator('as_of')
    @classmethod
    def actual_time(cls, value):
        if value.tzinfo is None or value > datetime.now(timezone.utc) + timedelta(minutes=5):
            raise ValueError('观测时间必须包含时区且不能晚于当前时间')
        return value


async def access(db, ctx, tenant_id, site_id, write=False):
    return await scope(db, ctx, tenant_id, site_id, 'seo.content', write)


async def record(db, model, row_id, tenant_id, site_id, lock=False):
    query = select(model).where(model.id == row_id, model.tenant_id == tenant_id, model.site_id == site_id)
    row = await db.scalar(query.with_for_update() if lock else query)
    if row is None:
        raise HTTPException(404, '当前网站下未找到此记录')
    return row


def data(row):
    return {column.name: getattr(row, column.name) for column in row.__table__.columns}


def check_version(row, expected):
    if row.version != expected:
        raise HTTPException(409, '记录已更新，请刷新后重试')


async def add_question(db, tenant_id, site_id, title, topic, source):
    key = fingerprint(title)
    row_id = await db.scalar(insert(SeoQuestion).values(tenant_id=tenant_id, site_id=site_id,
        title=title, fingerprint=key, topic=topic, sources=[source], intent='learn', status='open', relevance=3, version=1)
        .on_conflict_do_nothing(constraint='uq_seo_question_scope').returning(SeoQuestion.id))
    if row_id:
        return row_id, True
    row = await db.scalar(select(SeoQuestion).where(SeoQuestion.tenant_id == tenant_id, SeoQuestion.site_id == site_id,
                                                   SeoQuestion.fingerprint == key).with_for_update())
    identity = (source['kind'], source.get('url'), source.get('name'))
    if not any((s['kind'], s.get('url'), s.get('name')) == identity for s in row.sources):
        if len(row.sources) >= 50:
            raise HTTPException(422, '单个问题最多保留 50 个来源')
        row.sources = [*row.sources, source]
        row.version += 1
    return row.id, False


@router.get('/capabilities')
async def capabilities(tenant_id: PositiveInt, site_id: PositiveInt, ctx=Auth, session=Db):
    await access(session, ctx, tenant_id, site_id)
    return {'platforms': PLATFORMS, 'sources': ['人工/客服问题', 'CSV', '已采集的国内搜索结果'],
            'automatic_platform_publish': False, 'heat_source': None}


@router.post('/questions/import')
async def import_questions(req: ImportQuestions, ctx=Auth, session=Db):
    await access(session, ctx, req.tenant_id, req.site_id, True)
    ids, created = [], 0
    # Deterministic lock order avoids deadlock across concurrent overlapping imports.
    for item in sorted(req.items, key=lambda x: fingerprint(x.title)):
        source = {**item.source.model_dump(), 'captured_at': datetime.now(timezone.utc).isoformat()}
        row_id, new = await add_question(session, req.tenant_id, req.site_id, item.title, item.topic, source)
        ids.append(row_id)
        created += int(new)
    await session.commit()
    return {'created': created, 'merged': len(ids) - created, 'ids': ids}


@router.post('/questions/discover')
async def discover_questions(req: Scoped, ctx=Auth, session=Db):
    await access(session, ctx, req.tenant_id, req.site_id, True)
    if not ctx.can_view('seo.keywords'):
        raise HTTPException(403, '需要关键词查看权限才能读取搜索结果')
    results = list(await session.scalars(select(SeoSerpResult).where(SeoSerpResult.tenant_id == req.tenant_id,
        SeoSerpResult.site_id == req.site_id, SeoSerpResult.engine.in_(['baidu', 'sogou', '360']),
        SeoSerpResult.captured_at >= datetime.utcnow() - timedelta(days=30)).order_by(SeoSerpResult.captured_at.desc()).limit(500)))
    import re
    candidates = [row for row in results if row.title and re.search(r'如何|怎么|为什么|是否|哪些|多少|怎么办|[?？]', row.title)]
    created = 0
    for row in sorted(candidates[:200], key=lambda x: fingerprint(x.title)):
        try:
            url = public_url(row.result_url)
        except ValueError:
            continue
        _, new = await add_question(session, req.tenant_id, req.site_id, row.title[:300], '搜索问题',
            {'kind': 'serp', 'name': f'{row.engine} / {row.provider}', 'url': url, 'serp_id': row.id,
             'captured_at': row.captured_at.replace(tzinfo=timezone.utc).isoformat()})
        created += int(new)
    await session.commit()
    return {'created': created, 'examined': len(results), 'candidates': len(candidates),
            'message': '仅从近 30 天已采集的国内搜索结果提取疑问标题，不代表平台热度或全网问题量'}


@router.get('/questions')
async def questions(tenant_id: PositiveInt, site_id: PositiveInt, q: str = Query('', max_length=300),
                    status: Literal['open', 'selected', 'archived'] | None = None,
                    page: int = Query(1, ge=1), page_size: int = Query(30, ge=1, le=100), ctx=Auth, session=Db):
    await access(session, ctx, tenant_id, site_id)
    query = select(SeoQuestion).where(SeoQuestion.tenant_id == tenant_id, SeoQuestion.site_id == site_id)
    if q:
        query = query.where(SeoQuestion.title.contains(q, autoescape=True) | SeoQuestion.topic.contains(q, autoescape=True))
    if status:
        query = query.where(SeoQuestion.status == status)
    total = await session.scalar(select(func.count()).select_from(query.subquery()))
    rows = list(await session.scalars(query.order_by(SeoQuestion.relevance.desc(), SeoQuestion.id.desc()).offset((page - 1)*page_size).limit(page_size)))
    counts = dict((await session.execute(select(SeoQaAnswer.question_id, func.count()).where(
        SeoQaAnswer.tenant_id == tenant_id, SeoQaAnswer.site_id == site_id,
        SeoQaAnswer.question_id.in_([row.id for row in rows])).group_by(SeoQaAnswer.question_id))).all())
    return {'total': total, 'items': [{**data(row), 'answer_count': counts.get(row.id, 0), 'heat': None,
        'priority_reason': f'人工业务相关性 {row.relevance}/5；热度未知'} for row in rows]}


@router.patch('/questions/{question_id}')
async def edit_question(question_id: int, req: QuestionEdit, ctx=Auth, session=Db):
    await access(session, ctx, req.tenant_id, req.site_id, True)
    row = await record(session, SeoQuestion, question_id, req.tenant_id, req.site_id, True)
    check_version(row, req.version)
    for key, value in req.model_dump(exclude={'tenant_id', 'site_id', 'version'}).items():
        setattr(row, key, value)
    row.version += 1
    await session.commit()
    await session.refresh(row)
    return data(row)


@router.get('/facts')
async def facts(tenant_id: PositiveInt, site_id: PositiveInt, ctx=Auth, session=Db):
    await access(session, ctx, tenant_id, site_id)
    rows = await session.scalars(select(SeoQaFact).where(SeoQaFact.tenant_id == tenant_id,
        SeoQaFact.site_id == site_id).order_by(SeoQaFact.id.desc()).limit(500))
    return [{**data(row), 'current': fact_is_current(row)} for row in rows]


@router.post('/facts')
async def create_fact(req: FactInput, ctx=Auth, session=Db):
    await access(session, ctx, req.tenant_id, req.site_id, True)
    row = SeoQaFact(**req.model_dump())
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return {**data(row), 'current': fact_is_current(row)}


@router.patch('/facts/{fact_id}')
async def edit_fact(fact_id: int, req: FactEdit, ctx=Auth, session=Db):
    await access(session, ctx, req.tenant_id, req.site_id, True)
    row = await record(session, SeoQaFact, fact_id, req.tenant_id, req.site_id, True)
    check_version(row, req.version)
    for key, value in req.model_dump(exclude={'tenant_id', 'site_id', 'version'}).items():
        setattr(row, key, value)
    row.version += 1
    await session.commit()
    await session.refresh(row)
    return {**data(row), 'current': fact_is_current(row)}


async def fact_snapshots(session, tenant_id, site_id, fact_ids):
    snapshots = []
    for fact_id in sorted(set(fact_ids)):
        row = await record(session, SeoQaFact, fact_id, tenant_id, site_id)
        if not fact_is_current(row):
            raise HTTPException(409, f'事实 F{fact_id} 已过期或停用，请先更新资料')
        snapshots.append({'id': row.id, 'version': row.version, 'title': row.title, 'statement': row.statement,
                          'source_name': row.source_name, 'source_url': row.source_url})
    return snapshots


async def evidence_problems(session, answer, content):
    body = content.humanized_content or content.draft or ''
    problems = answer_checks(body, answer.fact_snapshots)
    if body_hash(body) != answer.evidence_hash:
        problems.append('正文已在其他编辑器更新，请回到问答工作台重新确认事实关联')
    for snapshot in answer.fact_snapshots:
        row = await session.get(SeoQaFact, snapshot['id'])
        if row is None or row.tenant_id != answer.tenant_id or row.site_id != answer.site_id or not fact_is_current(row) or row.version != snapshot['version']:
            problems.append(f'事实 F{snapshot["id"]} 已更新、过期或停用')
    return problems


async def require_answer_evidence(session, content):
    if content.content_type not in {'qa', 'faq'}:
        return False
    answer = await session.scalar(select(SeoQaAnswer).where(SeoQaAnswer.content_id == content.id))
    if answer:
        problems = await evidence_problems(session, answer, content)
        if problems:
            raise HTTPException(409, '；'.join(problems))
    return answer is not None


@router.get('/answers')
async def answers(tenant_id: PositiveInt, site_id: PositiveInt, question_id: PositiveInt,
                  ctx=Auth, session=Db):
    await access(session, ctx, tenant_id, site_id)
    await record(session, SeoQuestion, question_id, tenant_id, site_id)
    rows = await session.execute(select(SeoQaAnswer, SeoContentAsset).join(SeoContentAsset, SeoContentAsset.id == SeoQaAnswer.content_id)
        .where(SeoQaAnswer.tenant_id == tenant_id, SeoQaAnswer.site_id == site_id, SeoQaAnswer.question_id == question_id)
        .order_by(SeoQaAnswer.id.desc()).limit(100))
    return [{**data(row), 'body': content.humanized_content or content.draft or '', 'status': content.status,
             'content_version': content.version_count, 'review_note': content.review_note,
             'problems': await evidence_problems(session, row, content)} for row, content in rows]


async def save_answer(req, session, ctx, answer_id=None):
    await access(session, ctx, req.tenant_id, req.site_id, True)
    question = await record(session, SeoQuestion, req.question_id, req.tenant_id, req.site_id, answer_id is None)
    if question.status == 'archived':
        raise HTTPException(409, '归档问题请先恢复')
    snapshots = await fact_snapshots(session, req.tenant_id, req.site_id, req.fact_ids)
    if answer_id is None:
        match = (await session.execute(select(SeoQaAnswer, SeoContentAsset)
            .join(SeoContentAsset, SeoContentAsset.id == SeoQaAnswer.content_id)
            .where(SeoQaAnswer.question_id == question.id,
            SeoQaAnswer.tenant_id == req.tenant_id, SeoQaAnswer.site_id == req.site_id,
            SeoQaAnswer.evidence_hash == body_hash(req.body), SeoQaAnswer.format == req.format,
            SeoQaAnswer.fact_snapshots == snapshots,
            SeoContentAsset.tenant_id == req.tenant_id, SeoContentAsset.site_id == req.site_id,
            func.coalesce(func.nullif(SeoContentAsset.humanized_content, ''), SeoContentAsset.draft, '') == req.body)
            .order_by(SeoQaAnswer.id).limit(1).with_for_update(of=SeoContentAsset)
            .execution_options(populate_existing=True))).first()
        if match:
            existing, content = match
            await session.commit()
            return {**data(existing), 'content_version': content.version_count, 'problems': answer_checks(req.body, snapshots)}
        content = SeoContentAsset(tenant_id=req.tenant_id, site_id=req.site_id, title=question.title,
            content_type='faq' if req.format == 'faq' else 'qa', draft=req.body, status='drafting', created_by=ctx.user_id)
        session.add(content)
        await session.flush()
        row = SeoQaAnswer(tenant_id=req.tenant_id, site_id=req.site_id, question_id=question.id, content_id=content.id)
        session.add(row)
    else:
        # Match the generic editor/reviewer lock order: content before answer.
        row = await record(session, SeoQaAnswer, answer_id, req.tenant_id, req.site_id)
        if row.question_id != req.question_id:
            raise HTTPException(422, '回答不能移到另一个问题')
        content = await session.get(SeoContentAsset, row.content_id, with_for_update=True)
        if req.content_version != content.version_count:
            raise HTTPException(409, '回答已更新，请刷新后重试')
        if content.status == 'review':
            raise HTTPException(409, '审核中的回答需要退回后才能修改')
        content.draft, content.humanized_content = req.body, None
        content.status = 'drafting'
        content.version_count += 1
        content.reviewed_at = content.reviewed_by = content.review_submitted_at = content.review_submitted_by = None
        content.review_note = None
    row.format, row.fact_snapshots, row.evidence_hash = req.format, snapshots, body_hash(req.body)
    await session.commit()
    await session.refresh(row)
    return {**data(row), 'content_version': content.version_count, 'problems': answer_checks(req.body, snapshots)}


@router.post('/answers')
async def create_answer(req: AnswerInput, ctx=Auth, session=Db):
    return await save_answer(req, session, ctx)


@router.patch('/answers/{answer_id}')
async def edit_answer(answer_id: int, req: AnswerInput, ctx=Auth, session=Db):
    return await save_answer(req, session, ctx, answer_id)


@router.post('/placements')
async def prepare_placement(req: PlacementInput, ctx=Auth, session=Db):
    site = await access(session, ctx, req.tenant_id, req.site_id, True)
    answer = await record(session, SeoQaAnswer, req.answer_id, req.tenant_id, req.site_id)
    content = await session.get(SeoContentAsset, answer.content_id, with_for_update=True)
    if content.status not in {'ready', 'published'}:
        raise HTTPException(409, '请先完成回答审核')
    await require_answer_evidence(session, content)
    try:
        question_url = platform_url(req.platform, req.question_url, domain=site.canonical_domain) if req.question_url else None
        if req.platform != 'website' and not question_url:
            raise ValueError('必须填写指定问题的网址')
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    row = await session.scalar(select(SeoQaPlacement).where(SeoQaPlacement.answer_id == answer.id,
        SeoQaPlacement.platform == req.platform, SeoQaPlacement.content_version == content.version_count))
    if row is not None:
        if row.question_url != question_url:
            raise HTTPException(409, '本版回答已有不同问题的发布记录，请核对原记录')
        return data(row)
    import re
    body = re.sub(r'\[F\d+\]', '', content.humanized_content or content.draft or '').strip()
    row = SeoQaPlacement(tenant_id=req.tenant_id, site_id=req.site_id, answer_id=answer.id, platform=req.platform,
        question_url=question_url, scheduled_at=req.scheduled_at, content_version=content.version_count, body=body)
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return data(row)


@router.get('/placements')
async def placements(tenant_id: PositiveInt, site_id: PositiveInt, ctx=Auth, session=Db):
    await access(session, ctx, tenant_id, site_id)
    rows = await session.execute(select(SeoQaPlacement, SeoQaAnswer, SeoContentAsset)
        .join(SeoQaAnswer, SeoQaAnswer.id == SeoQaPlacement.answer_id)
        .join(SeoContentAsset, SeoContentAsset.id == SeoQaAnswer.content_id)
        .where(SeoQaPlacement.tenant_id == tenant_id, SeoQaPlacement.site_id == site_id)
        .order_by(SeoQaPlacement.id.desc()).limit(200))
    result = []
    for row, answer, content in rows:
        problems = await evidence_problems(session, answer, content)
        if content.status not in {'ready', 'published'} or content.version_count != row.content_version:
            problems.append('该审核稿已被新版本替代或正在重新审核')
        result.append({**data(row), 'publishable': not problems, 'problems': problems})
    return result


@router.post('/placements/{placement_id}/receipt')
async def receipt(placement_id: int, req: ReceiptInput, ctx=Auth, session=Db):
    site = await access(session, ctx, req.tenant_id, req.site_id, True)
    row = await record(session, SeoQaPlacement, placement_id, req.tenant_id, req.site_id, True)
    check_version(row, req.version)
    try:
        url = platform_url(row.platform, req.answer_url, answer=True, question_url=row.question_url, domain=site.canonical_domain)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    if row.answer_url != url:
        row.answer_url, row.status = url, 'reported'
        row.observations = []
        row.reported_metrics = None
        row.version += 1
    await session.commit()
    await session.refresh(row)
    return data(row)


@router.get('/placements/{placement_id}/draft')
async def publication_draft(placement_id: int, tenant_id: PositiveInt, site_id: PositiveInt, ctx=Auth, session=Db):
    await access(session, ctx, tenant_id, site_id)
    row = await record(session, SeoQaPlacement, placement_id, tenant_id, site_id)
    answer = await record(session, SeoQaAnswer, row.answer_id, tenant_id, site_id)
    content = await session.get(SeoContentAsset, answer.content_id)
    if content.status not in {'ready', 'published'} or content.version_count != row.content_version:
        raise HTTPException(409, '审核稿版本已失效，请重新审核并准备分发')
    await require_answer_evidence(session, content)
    return {'id': row.id, 'body': row.body, 'content_version': row.content_version}


@router.post('/placements/{placement_id}/verify')
async def verify(placement_id: int, req: Scoped, ctx=Auth, session=Db):
    await access(session, ctx, req.tenant_id, req.site_id, True)
    row = await record(session, SeoQaPlacement, placement_id, req.tenant_id, req.site_id, True)
    if not row.answer_url:
        raise HTTPException(409, '请先回填回答网址')
    last = row.observations[-1] if row.observations else None
    if last and datetime.fromisoformat(last['checked_at']) > datetime.now(timezone.utc) - timedelta(minutes=1):
        raise HTTPException(429, '请稍后再核验，单条回答每分钟最多一次')
    from app.seo_backlinks import fetch_backlink_page
    result = await fetch_backlink_page(row.answer_url)
    observation = observe_answer(result, row.body, row.answer_url)
    row.observations = [*row.observations[-29:], observation]
    row.status = observation['state']
    row.version += 1
    await session.commit()
    await session.refresh(row)
    return data(row)


@router.post('/placements/{placement_id}/metrics')
async def report_metrics(placement_id: int, req: MetricsInput, ctx=Auth, session=Db):
    await access(session, ctx, req.tenant_id, req.site_id, True)
    row = await record(session, SeoQaPlacement, placement_id, req.tenant_id, req.site_id, True)
    check_version(row, req.version)
    row.reported_metrics = {**req.model_dump(mode='json', exclude={'tenant_id', 'site_id', 'version'}),
                            'source': 'user_reported', 'actor': ctx.user_id}
    row.version += 1
    await session.commit()
    return {'saved': True, 'source': 'user_reported'}


@router.get('/maintenance')
async def maintenance(tenant_id: PositiveInt, site_id: PositiveInt, ctx=Auth, session=Db):
    await access(session, ctx, tenant_id, site_id)
    rows = await session.execute(select(SeoQaAnswer, SeoContentAsset).join(SeoContentAsset, SeoContentAsset.id == SeoQaAnswer.content_id)
        .where(SeoQaAnswer.tenant_id == tenant_id, SeoQaAnswer.site_id == site_id).order_by(SeoQaAnswer.updated_at.desc()).limit(200))
    items = []
    for answer, content in rows:
        problems = await evidence_problems(session, answer, content)
        if problems:
            items.append({'answer_id': answer.id, 'question_id': answer.question_id, 'title': content.title, 'problems': problems})
    return {'items': items, 'scope': '最近更新的 200 个回答；检查事实过期、版本变化和正文证据关联'}
