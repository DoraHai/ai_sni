"""Exact review admission and evidence from the version actually being saved."""
import hashlib
import json
from sqlalchemy import select

REVIEWS = (
    ('POST', '/content-assets/{content_id}/submit-review', 'note version_count', 'seo.content'),
    ('POST', '/content-assets/{content_id}/review', 'decision note version_count', 'seo.content'),
    ('POST', '/workbench/content-assets/{content_id}/confirmations', 'version_count payload_hash decision actor_mode note', 'seo.content'),
    ('POST', '/qa/batches/{batch_id}/answers/{answer_id}/review', 'tenant_id site_id content_version question_version action note', 'seo.content'),
    ('POST', '/content-distribution/variants/{variant_id}/review', 'tenant_id site_id decision note', 'seo.content'),
    ('POST', '/site/pages/{page_id}/ai-tdk/{suggestion_id}/review', 'tenant_id site_id fields links', 'seo.site seo.content'),
)


def review_rules(rule_type):
    return [rule_type(method, '/api/v1/seo' + path, frozenset(fields.split()),
                      frozenset(), tuple(permissions.split()), 'site', True)
            for method, path, fields, permissions in REVIEWS]


def content_evidence(row):
    from app.api.seo import _content_confirmation_hash
    return {'content_id': row.id, 'version': row.version_count or 1,
            'content_hash': _content_confirmation_hash(row)}


async def prepare_review_evidence(session, ctx, pending):
    scope = getattr(ctx, 'advisor_write_scope', None)
    if scope is None:
        return {}
    request, body, rule = scope
    review = rule.template in {r.template for r in review_rules(type(rule))}
    variant_write = rule.template in {'/api/v1/seo/content-distribution/variants',
                                     '/api/v1/seo/content-distribution/variants/generate'}
    if not (review or variant_write):
        return {}
    from app.models.seo import SeoContentAsset, SeoDistributionVariant
    from app.models.seo_qa import SeoQaAnswer
    await session.flush()
    ids = set()
    if request.path_params.get('content_id'):
        ids.add(request.path_params['content_id'])
    if request.path_params.get('answer_id'):
        answer = await session.get(SeoQaAnswer, request.path_params['answer_id'])
        if answer:
            ids.add(answer.content_id)
    variants = [row for row in pending if isinstance(row, SeoDistributionVariant)]
    if request.path_params.get('variant_id'):
        variant = await session.get(SeoDistributionVariant, request.path_params['variant_id'])
        if variant and variant not in variants:
            variants.append(variant)
    ids.update(row.content_asset_id for row in variants)
    rows = list(await session.scalars(select(SeoContentAsset).where(
        SeoContentAsset.tenant_id == ctx.tenant_id, SeoContentAsset.id.in_(ids)))) if ids else []
    evidence = {'reviewed_versions': [content_evidence(row) for row in rows],
                'review_action': body.get('decision') or body.get('action') or body.get('status') or 'submit'}
    if variants:
        evidence['variant_versions'] = [{'variant_id': row.id, 'source_version': row.source_version,
            'revision': row.revision_number, 'content_hash': hashlib.sha256(json.dumps(
                [row.title, row.content], ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()}
            for row in variants]
    if rule.template.endswith('/confirmations'):
        evidence.update(actor_mode='advisor_proxy', consent_note=body.get('note'))
    request.state.seo_advisor_evidence = {**getattr(request.state, 'seo_advisor_evidence', {}), **evidence}
    return evidence
