"""Project client A–L: authenticated, saved-record GETs, without write helpers."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response

from app.geo import project_client_view as view
from app.geo import project_statistics as statistics
from app.geo.project_client_protocol import (
    PREFIX, QUERY, ROUTES, WEEKLY, fail, paginate, parameters,
)
from app.geo.project_client_store import (
    authorize, client_read_session, load_answers, load_content, load_open_week_progress,
    load_recommendations, require_object,
)
from app.security.auth import AuthContext, require_scoped_auth

router = APIRouter(tags=['GEO 客户项目只读'])


def filters_for(resource, params):
    return {k: params.get(k) for k in sorted(QUERY.get(resource, set()))}


async def project_response(resource, request, ctx, session):
    params, decoded, context = await parameters(request, resource)
    records = await authorize(session, ctx, params, request)
    for key, collection in (('business_id', records.businesses), ('unit_id', records.units)):
        if params.get(key) is not None:
            require_object(collection, params[key])
    if decoded and decoded['scope'] != records.fingerprint:
        fail(409, 'SCOPE_CHANGED', '项目归属已改变，请刷新列表')
    end = params.get('week_end')
    if params.get('question_id') is not None:
        require_object(records.prompts, params['question_id'])
    if resource in WEEKLY:
        await load_answers(session, records, params, answer_id=params.get('answer_id'))
    if resource in {'overview', 'visibility', 'summary', 'questions', 'question'}:
        await load_open_week_progress(session, records, params)
    if resource in {'overview', 'content', 'task', 'variants', 'variant', 'article', 'deliveries',
                    'article_citations', 'report_pdf', 'report_xlsx'}:
        await load_content(session, records, params)
    if resource in {'recommendations', 'report_pdf', 'report_xlsx'}:
        await load_recommendations(session, records, params)
    if params.get('task_id') is not None:
        require_object(records.tasks, params['task_id'])
    if resource in {'variant', 'article'}:
        collection = records.variants if resource == 'variant' else records.articles
        item = require_object(collection, params[resource + '_id'])
        if item.task_id != params['task_id']:
            fail(404, 'NOT_FOUND', '项目或记录不存在')
    if resource == 'answer':
        require_object({r.id: r for r in records.answers}, params['answer_id'])
    weekly = view.weekly_data(records, end) if resource in {'overview', 'visibility', 'answers', 'answer'} else None
    rows = view.week_rows(records.answers, end) if end else []
    unknown = [r for r in records.answers if r.captured_at is None]
    resource_basis = view.basis(records, end=end, rows=rows, unknown_rows=unknown)

    def page(items, key, watermarks):
        return paginate(items, key, params=params, decoded=decoded, context=context,
                        scope=records.fingerprint, watermarks=watermarks)

    def watermarks(**fresh):
        if not decoded:
            return fresh
        saved = decoded['watermarks']
        if set(saved) != set(fresh):
            fail(400, 'INVALID_CURSOR', '分页游标无效，请重新查询')
        return saved

    if resource in {'report_pdf', 'report_xlsx'}:
        from app.geo.report_export import build_project_xlsx, build_project_report_html
        from app.geo.report_pdf import render_report_pdf
        from urllib.parse import quote
        payload = {'project': {'id': records.project.id, 'name': records.project.name or ''},
                   'summary': statistics.summary(records, end),
                   'questions': [dict(view.question_row(p, records, end, rows),
                       by_engine=statistics.question_cells(p.id, records, end)) for p in records.prompts.values()],
                   'citations': statistics.article_citations(records, end),
                   'recommendations': statistics.recommendations(records), 'basis': resource_basis}
        if resource == 'report_xlsx':
            try:
                content = build_project_xlsx(payload)
            except ValueError:
                fail(413, 'READ_UNAVAILABLE', '报告超过导出预算，请缩小项目范围')
            media = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
            extension = 'xlsx'
        else:
            content = await render_report_pdf(build_project_report_html(payload))
            media, extension = 'application/pdf', 'pdf'
        filename = quote(f'GEO-项目{records.project.id}-{end}.{extension}')
        return Response(content, media_type=media, headers={'Cache-Control': 'private, no-store',
            'Content-Disposition': f"attachment; filename*=UTF-8''{filename}"})
    if resource == 'summary':
        data = statistics.summary(records, end)
    elif resource == 'article_citations':
        citations = statistics.article_citations(records, end)
        mark = watermarks(publication=max((r['id'] for r in citations['items']), default=0))
        data = {**citations, **page([r for r in citations['items'] if r['id'] <= mark['publication']], lambda r: (r['id'],), mark)}
    elif resource == 'recommendations':
        items = statistics.recommendations(records)
        mark = watermarks(task=max((r['id'] for r in items), default=0))
        data = {**page([r for r in items if r['id'] <= mark['task']], lambda r: (r['id'],), mark),
                'structure_scan_status': 'unverified_project_ownership'}
    elif resource == 'visibility':
        data = weekly
    elif resource in {'questions', 'question'}:
        selected = list(records.prompts.values())
        if resource == 'question':
            selected = [require_object(records.prompts, params['question_id'])]
        else:
            mark = watermarks(question=max(records.prompts, default=0))
            selected = [p for p in selected if p.id <= mark['question']]
        projected = [view.question_row(p, records, end, rows) for p in selected]
        qualified = statistics.cohort(records, end)
        for item in projected:
            item['by_engine'] = statistics.question_cells(item['id'], records, end, qualified)
        if resource == 'questions':
            f = filters_for(resource, params)
            projected = [p for p in projected if (f['status'] == 'all' or p['status'] == f['status'])
                         and (f['is_brand_probe'] is None or p['is_brand_probe'] == f['is_brand_probe'])
                         and (f['attention'] == 'all' or p['attention_reason_codes'])
                         and (f['business_id'] is None or p['business']['id'] == f['business_id'])
                         and (f['unit_id'] is None or p['unit']['id'] == f['unit_id'])
                         and (f['q'] is None or f['q'].casefold() in p['question'].casefold())]
            data = {**page(projected, lambda p: (p['id'],), mark), 'filters': f, 'options': statistics.options(records)}
        else:
            question = projected[0]
            selected_rows = [r for r in rows if r.prompt_id == params['question_id']]
            data = {'question': question, 'by_engine': view.engine_groups(selected_rows, records),
                    'evidence': {'answer_count': len(selected_rows),
                                 'excluded_answer_count': sum(bool(view.qualification(r, records)) for r in selected_rows),
                                 'unknown_time_count': sum(r.prompt_id == params['question_id'] for r in unknown),
                                 'unknown_time_scope': 'current_project_history'},
                    'answers_path': view.link(records, '/answers', end=end, question_id=params['question_id']),
                    'content_path': view.link(records, '/content', question_id=params['question_id'])}
        ids = {p['id'] for p in projected}
        resource_basis = view.basis(records, end=end, rows=[r for r in rows if r.prompt_id in ids],
                                    unknown_rows=[r for r in unknown if r.prompt_id in ids])
    elif resource in {'answers', 'answer'}:
        if resource == 'answer':
            row = require_object({r.id: r for r in records.answers}, params['answer_id'])
            _, data = view.answer_row(row, records, end, weekly)
            resource_basis = view.basis(records, end=end, rows=view.week_rows([row], end), unknown_rows=[row], single=True)
            resource_basis['last_data_at'] = view.iso(row.captured_at)
        else:
            f = filters_for(resource, params)
            mark = watermarks(answer=max((r.id for r in records.answers), default=0))

            def matches(row, eligibility=True):
                qualified = not view.qualification(row, records)
                return (row.id <= mark['answer'] and (f['question_id'] is None or row.prompt_id == f['question_id'])
                        and (f['engine_key'] is None or row.engine == f['engine_key'])
                        and (f['source_kind'] is None or view.sample_provenance(row)['sample_kind'] == f['source_kind'])
                        and (not eligibility or f['eligibility'] == 'all' or qualified == (f['eligibility'] == 'qualified')))
            selected = [r for r in rows if matches(r)]
            items = [view.answer_row(r, records, end, weekly)[0] for r in selected]
            data = {**page(items, lambda a: (view.timestamp_order(a['captured_at']), a['id']), mark), 'filters': f}
            resource_basis = view.basis(records, end=end, rows=selected, unknown_rows=[r for r in unknown if matches(r, False)])
    elif resource == 'content':
        mark = watermarks(task=max(records.tasks, default=0))
        f = filters_for(resource, params)
        items = [view.task_row(t, records) for t in records.tasks.values() if t.id <= mark['task']]
        items = [t for t in items if (f['question_id'] is None or t['question_id'] == f['question_id'])
                 and (f['include_archived'] or t['stored_status'] not in {'archived', 'cancelled'})
                 and (f['review_status'] is None or t['review']['status'] == f['review_status'])
                 and (f['q'] is None or f['q'].casefold() in t['title'].casefold())]
        data = {**page(items, lambda t: (t['id'],), mark), 'filters': f}
        ids = {i['id'] for i in items}
        resource_basis = view.basis(records, last_data_at=view.latest_time(
            [at for t in records.tasks.values() if t.id in ids for at in (t.updated_at, t.created_at)]
            + [view.current_master(records, ident).created_at for ident in ids if view.current_master(records, ident)]))
    elif resource == 'task':
        task = records.tasks[params['task_id']]
        master = view.current_master(records, task.id)
        variants = [v for v in records.variants.values() if v.task_id == task.id]
        summary = dict.fromkeys(('succeeded', 'failed', 'unknown', 'sending', 'other'), 0)
        for variant in variants:
            for _, entry in view.delivery_entries(variant):
                state = entry.get('state')
                summary[state if isinstance(state, str) and state in summary and state != 'other' else 'other'] += 1
        data = {'task': view.task_row(task, records), 'master': view.article_row(master) if master else None,
                'variants_path': view.link(records, f'/content/{task.id}/variants'),
                'deliveries_path': view.link(records, '/deliveries', task_id=task.id), 'receipt_summary': summary}
        resource_basis = view.basis(records, last_data_at=view.latest_time(
            [task.updated_at, task.created_at, master.created_at if master else None]))
    elif resource in {'variants', 'variant', 'article'}:
        task_id = params['task_id']
        if resource == 'article':
            article = records.articles[params['article_id']]
            master = view.current_master(records, task_id)
            data = {'article': view.article_row(article), 'is_current_master': bool(master and master.id == article.id)}
            times = [article.created_at]
        elif resource == 'variant':
            variant = records.variants[params['variant_id']]
            data = {'variant': view.variant_row(variant, records), 'body_markdown': variant.body_markdown or '',
                    'article_path': view.link(records, f'/content/{task_id}/articles/{variant.article_version_id}'),
                    'deliveries_path': view.link(records, '/deliveries', task_id=task_id)}
            times = [variant.updated_at, variant.created_at]
        else:
            selected = [v for v in records.variants.values() if v.task_id == task_id]
            mark = watermarks(variant=max((v.id for v in selected), default=0))
            selected = [v for v in selected if v.id <= mark['variant']]
            data = page([view.variant_row(v, records) for v in selected], lambda v: (v['id'],), mark)
            times = [at for v in selected for at in (v.updated_at, v.created_at)]
        resource_basis = view.basis(records, last_data_at=view.latest_time(times))
    elif resource == 'deliveries':
        f = filters_for(resource, params)
        variants = [v for v in records.variants.values() if f['task_id'] is None or v.task_id == f['task_id']]
        vids = {v.id for v in variants}
        publications = [p for p in records.publications if p.variant_id in vids]
        mark = watermarks(publication=max((p.id for p in publications), default=0), variant=max(vids, default=0))
        variants = [v for v in variants if v.id <= mark['variant']]
        vids = {v.id for v in variants}
        publications = [p for p in publications if p.id <= mark['publication'] and p.variant_id in vids]
        pub_rows = view.publication_rows(records, publications) if f['record_type'] != 'receipt' else []
        receipts = view.receipt_rows(records, variants) if f['record_type'] != 'publication' else []
        items = pub_rows + receipts
        def delivery_key(row):
            return (1, row['id'], '') if row['record_type'] == 'publication' else (0, row['variant_id'], row['receipt_id'])
        data = {**page(items, delivery_key, mark), 'filters': f,
                'counts': {'publication_records': len(pub_rows), 'receipt_records': len(receipts),
                           'published_records': sum(p['stored_status'] == 'published' and p['url_state'] == 'available' for p in pub_rows),
                           'stored_verified_publications': sum(p['stored_status'] == 'published' and p['url_state'] == 'available'
                                                              and p['verification']['evidence_valid'] for p in pub_rows)}}
        times = [view.parsed_time(r.get(field)) for r in items for field in ('published_at', 'updated_at')]
        resource_basis = view.basis(records, last_data_at=view.latest_time(times))
    elif resource == 'overview':
        tasks = [view.task_row(t, records) for t in records.tasks.values() if t.status not in {'archived', 'cancelled'}]
        questions = [view.question_row(p, records, end, rows) for p in records.prompts.values()
                     if p.status == 'active' and not p.is_brand_probe]
        data = {'project': {'id': records.project.id, 'name': records.project.name or '', 'brand_name': records.project.brand_name,
                            'canonical_domain': records.project.canonical_domain or ''},
                'content': {'time_basis': 'current_inventory', 'active_task_count': len(tasks),
                            'pending_review_count': sum(t['review']['status'] == 'pending' for t in tasks),
                            'approved_current_master_count': sum(t['review']['covers_current_master'] for t in tasks),
                            'task_count_with_master': sum(t['latest_master'] is not None for t in tasks),
                            'variant_count': sum(t['variant_count'] for t in tasks),
                            'native_published_record_count': sum(t['published_record_count'] for t in tasks)},
                'monitoring': {'time_basis': 'closed_week', 'active_nonbrand_question_count': len(questions),
                               'attention_question_count': sum(bool(q['attention_reason_codes']) for q in questions),
                               'no_real_observation_question_count': sum('no_real_observations' in q['attention_reason_codes'] for q in questions),
                               'some_nonmention_question_count': sum('not_mentioned_in_some_observations' in q['attention_reason_codes'] for q in questions),
                               'observed_question_count': sum(q['observation']['total'] > 0 for q in questions),
                               'saved_answer_count': len(rows),
                               'qualified_answer_count': sum(not view.qualification(r, records) for r in rows),
                               'latest_answer_at': view.latest_time(r.captured_at for r in rows)},
                'weekly': weekly['current'],
                'links': {'pending_content_path': view.link(records, '/content', review_status='pending'),
                          'questions_path': view.link(records, '/questions', end=end),
                          'attention_questions_path': view.link(records, '/questions', end=end, attention='needs_attention'),
                          'visibility_path': view.link(records, '/visibility', end=end),
                          'deliveries_path': view.link(records, '/deliveries'),
                          'executions_path': f"/api/v1/geo/projects/{records.project.id}/executions?tenant_id={records.project.tenant_id}"}}
    if resource in {'overview', 'visibility', 'summary', 'questions', 'question'}:
        data['open_week_progress'] = records.open_week_progress
    return view.envelope(records, params, data, resource_basis)


def endpoint(resource):
    async def read(request: Request, response: Response, ctx: AuthContext = Depends(require_scoped_auth),
                   session=Depends(client_read_session)):
        response.headers['Cache-Control'] = 'private, no-store'
        return await project_response(resource, request, ctx, session)
    read.__name__ = 'client_project_' + resource
    return read


for resource, suffix in ROUTES.items():
    router.add_api_route(PREFIX + suffix, endpoint(resource), methods=['GET'], name='client_project_' + resource)
