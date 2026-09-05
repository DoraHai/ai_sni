"""Verify an actual public page against the current content version."""
import hashlib
import re
from datetime import datetime

from bs4 import BeautifulSoup
from fastapi import HTTPException
from sqlalchemy import select

from app.models import GeoContentTask, GeoArticleVersion, GeoChannelVariant, GeoPublication
from app.geo.audit import safe_fetch, GeoAuditError
from app.geo.content.md_to_html import markdown_to_publish_html


def visible_text(html):
    soup = BeautifulSoup(html or '', 'html.parser')
    for tag in soup(['script', 'style', 'noscript', 'template']) + soup.select('[hidden], [aria-hidden="true"]'):
        tag.decompose()
    for tag in soup.select('[style]'):
        if tag.attrs is not None and re.search(r'(?:display\s*:\s*none|visibility\s*:\s*hidden)', tag.get('style', ''), re.I):
            tag.decompose()
    return re.sub(r'\s+', '', soup.get_text(' ', strip=True)).casefold()


def match_publication(title, markdown, html):
    expected = visible_text(markdown_to_publish_html(markdown, wrap_article=False))
    actual = visible_text(html)
    title_text = re.sub(r'\s+', '', title or '').casefold()
    # Check the whole content in small passages, not just a matching title.
    passages = list(dict.fromkeys(expected[i:i + 80] for i in range(0, len(expected), 80) if len(expected[i:i + 80]) >= 30))
    matched = sum(p in actual for p in passages)
    if not title_text or title_text not in actual or len(passages) < 3 or len(actual) < len(expected) * .8 or matched / len(passages) < .8:
        raise HTTPException(409, '发布页正文尚未匹配当前稿件，不能生成发布证据')
    return {'matched_passages': matched, 'total_passages': len(passages),
            'expected_sha256': hashlib.sha256(expected.encode()).hexdigest(),
            'observed_sha256': hashlib.sha256(actual.encode()).hexdigest()}


async def verify_publication(session, task, publication_id):
    content_id = (task.progress_first or {}).get('params', {}).get('content_task_id')
    content = await session.scalar(select(GeoContentTask).where(
        GeoContentTask.id == content_id, GeoContentTask.tenant_id == task.tenant_id).with_for_update())
    if content is None:
        raise HTTPException(409, '缺少当前客户的内容任务关联')
    article = await session.scalar(select(GeoArticleVersion).where(GeoArticleVersion.task_id == content.id)
                                   .order_by(GeoArticleVersion.version_no.desc()).limit(1))
    result = (await session.execute(select(GeoPublication, GeoChannelVariant).join(
        GeoChannelVariant, GeoChannelVariant.id == GeoPublication.variant_id).join(
        GeoContentTask, GeoContentTask.id == GeoChannelVariant.task_id).where(
        GeoPublication.id == publication_id, GeoContentTask.tenant_id == task.tenant_id,
        GeoChannelVariant.task_id == content.id).with_for_update(of=[GeoPublication, GeoChannelVariant]))).first()
    if not result or article is None:
        raise HTTPException(404, '当前稿件的发布记录不存在')
    pub, variant = result
    if (pub.status != 'published' or not pub.published_url
            or variant.article_version_id != article.id):
        raise HTTPException(409, '需当前版本的真实发布记录')
    try:
        document = await safe_fetch(pub.published_url)
    except GeoAuditError as exc:
        raise HTTPException(409, '发布页抓取失败，尚不能核实上线') from exc
    evidence = match_publication(variant.title, variant.body_markdown, document.html)
    latest = await session.scalar(select(GeoArticleVersion.id).where(GeoArticleVersion.task_id == content.id)
                                  .order_by(GeoArticleVersion.version_no.desc()).limit(1))
    if latest != article.id:
        raise HTTPException(409, '核验期间正文版本变化，请重新核验')
    old = (task.progress or {}).get('publication_evidence') or {}
    now = datetime.utcnow().isoformat() + 'Z'
    unchanged = (old.get('publication_id') == pub.id and old.get('article_id') == article.id
                 and old.get('expected_sha256') == evidence['expected_sha256']
                 and old.get('url') == document.final_url)
    return {**evidence, 'publication_id': pub.id, 'article_id': article.id, 'variant_id': variant.id,
            'url': document.final_url, 'verified_at': now,
            'first_verified_at': old.get('first_verified_at', now) if unchanged else now}
