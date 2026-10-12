"""Read-only SEO source snapshot for central distribution; no platform I/O."""
from datetime import date
import hashlib
import json
import re
from types import SimpleNamespace

from bs4 import BeautifulSoup
from fastapi import HTTPException
from sqlalchemy import and_, or_, select, func, literal_column, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import aliased

from app.models.user import User
from app.models.role import Role
from app.models.module_workspace import SeoSite, TenantModule
from app.models.seo import (SeoContentAsset, SeoDistributionVariant, SeoDistributionConnection,
    SeoContentConfirmation, SeoSiteAdvisorAssignment, SeoKeywordAsset)


# Central content types may have multiple native transports. Keep the exact
# native connection/variant code matched; aliases never authorize each other.
PLATFORMS = {'wechat-article': ('wechat_official', 'wechat_browser'),
             'xiaohongshu-image': ('xiaohongshu',)}


def denied(code, message, status=409):
    return HTTPException(status, {'code': 'seo_distribution_' + code, 'message': message})


def positive(value):
    return type(value) is int and 0 < value < 2**63


async def media_installed(session, platform):
    """Optional pure-text compatibility; partially installed storage fails closed."""
    with session.no_autoflush:
        row = (await session.execute(text("SELECT "
            "to_regclass(current_schema()||'.seo_distribution_media_sets') IS NOT NULL AS sets,"
            "to_regclass(current_schema()||'.seo_distribution_media_bytes') IS NOT NULL AS bytes,"
            "to_regclass(current_schema()||'.seo_distribution_media_reviews') IS NOT NULL AS reviews"))).mappings().one()
    if all(row.values()): return True
    if any(row.values()) or platform == 'xiaohongshu-image':
        raise denied('source_unavailable','素材存储结构尚未完整就绪',503)
    return False


def _check_scope(row, tenant):
    if row is None or not row['user_is_active'] or row['role_id'] is None or row['user_tenant_id'] not in (None,tenant):
        raise denied('identity_required', '账号状态或客户归属不允许读取发布来源', 403)
    permissions = row['role_permissions'] if isinstance(row['role_permissions'],dict) else {}
    if any(permissions.get(key)!='edit' for key in ('seo.content','seo.site')) or not row['assigned']:
        raise denied('advisor_required', '需要当前网站有效顾问分配及内容、网站编辑权限', 403)
    if row['site_id'] is None or row['site_tenant_id']!=tenant:
        raise denied('scope_not_found', '当前客户的网站不存在', 404)
    settings = row['site_site_settings'] if isinstance(row['site_site_settings'],dict) else {}
    plan = settings.get('seo_service_plan')
    if (row['module_id'] is None or row['module_tenant_id']!=tenant or row['module_module_code']!='seo'
            or row['module_status'] not in {'active','trial'}
            or row['module_expires_at'] and row['module_expires_at']<date.today()
            or row['site_status']!='active' or isinstance(plan,dict) and plan.get('status')=='paused'):
        raise denied('site_unavailable', 'SEO 模块或网站当前不可运营')


async def authorize_scope(session, actor_user_id: int, tenant_id: int, scope_id: int) -> None:
    """Authorize controls/listing before any content is selected; no writes."""
    if not all(positive(v) for v in (actor_user_id,tenant_id,scope_id)):
        raise denied('invalid_scope', '需要有效实名账号及客户、网站编号', 422)
    u,r,s,m=User,Role,SeoSite,TenantModule
    assigned=select(SeoSiteAdvisorAssignment.id).where(
        SeoSiteAdvisorAssignment.tenant_id==tenant_id,SeoSiteAdvisorAssignment.site_id==scope_id,
        SeoSiteAdvisorAssignment.advisor_user_id==actor_user_id,SeoSiteAdvisorAssignment.active.is_(True)).exists()
    fields={'user':(u,('tenant_id','is_active')),'role':(r,('id','permissions')),
        'site':(s,('id','tenant_id','status','site_settings')),
        'module':(m,('id','tenant_id','module_code','status','expires_at'))}
    columns=[getattr(model,name).label(prefix+'_'+name) for prefix,(model,names) in fields.items() for name in names]
    query=select(*columns,assigned.label('assigned')).select_from(u).outerjoin(r,r.id==u.role_id
        ).outerjoin(s,s.id==scope_id).outerjoin(m,m.id==s.tenant_module_id).where(u.id==actor_user_id)
    try:
        with session.no_autoflush:
            row=(await session.execute(query)).mappings().one_or_none()
        _check_scope(row,tenant_id)
    except (SQLAlchemyError, OSError, TimeoutError):
        raise denied('source_unavailable', '来源结构或数据库暂不可用，请稍后核对', 503) from None


async def load_source(session, actor_user_id: int, tenant_id: int, scope_id: int,
                      variant_id: int, platform: str) -> dict:
    """Return an exact reviewed snapshot, never accept caller content/review flags.

    Caller owns the transaction. Use a fresh short READ COMMITTED transaction at
    creation, dispatch and return, comparing the complete snapshot each time.
    No commit, flush, DDL, credential decrypt, network or provider call occurs.
    """
    if not all(positive(v) for v in (actor_user_id, tenant_id, scope_id, variant_id)):
        raise denied('invalid_scope', '需要有效实名账号及客户、网站、渠道稿编号', 422)
    if not isinstance(platform, str) or platform not in PLATFORMS:
        raise denied('platform_unsupported', '该平台尚未接入 SEO 来源', 422)
    await authorize_scope(session,actor_user_id,tenant_id,scope_id)
    try:
        # Select scalar columns, not ORM entities: identity-map caches and pending
        # in-memory edits cannot substitute for committed database source rows.
        with session.no_autoflush:
            return await _load(session, actor_user_id, tenant_id, scope_id, variant_id, platform)
    except (SQLAlchemyError, OSError, TimeoutError):
        raise denied('source_unavailable', '来源结构或数据库暂不可用，请稍后核对', 503) from None


async def load_publication_source(session, actor_user_id: int, tenant_id: int, scope_id: int,
                                  variant_id: int, platform: str) -> dict:
    """Fresh native source for an explicitly authorized publish intention only.

    No publish, commit or grant. Central/executor must call this for publication;
    load_source remains compatible with pure-text preflight/handoff.
    """
    snapshot = await load_source(session, actor_user_id, tenant_id, scope_id, variant_id, platform)
    if platform == 'wechat-article' and len(snapshot['content']['assets']) != 1:
        raise denied('cover_required','公众号正式发布须有一张当前独立审核冻结的封面')
    return snapshot


async def list_sources(session, actor_user_id: int, tenant_id: int, scope_id: int,
                       platform: str) -> list[dict]:
    """Return up to 50 candidate summaries passing the current source gates.

    The limit bounds candidates, not a total count. Scope/auth failures and DB
    errors fail the whole request, including after an empty candidate query.
    """
    await authorize_scope(session, actor_user_id, tenant_id, scope_id)
    if not isinstance(platform, str) or platform not in PLATFORMS:
        raise denied('platform_unsupported', '该平台尚未接入 SEO 来源', 422)
    v, c, connection = SeoDistributionVariant, SeoContentAsset, SeoDistributionConnection
    newer = aliased(v)
    latest = select(newer.id).where(newer.tenant_id == tenant_id,
        newer.content_asset_id == v.content_asset_id, newer.connection_id == v.connection_id
        ).order_by(newer.revision_number.desc(), newer.id.desc()).limit(1).correlate(v).scalar_subquery()
    query = select(v.id).join(c, c.id == v.content_asset_id).join(connection, connection.id == v.connection_id
        ).where(v.tenant_id == tenant_id, c.tenant_id == tenant_id, c.site_id == scope_id,
            connection.tenant_id == tenant_id, v.platform_code.in_(PLATFORMS[platform]),
            connection.platform_code == v.platform_code, c.content_type == 'article',
            v.id == latest, v.status == 'approved').order_by(v.updated_at.desc(), v.id.desc()).limit(50)
    skippable = {'seo_distribution_' + code for code in (
        'platform_mismatch', 'connection_unavailable', 'content_type_unsupported', 'source_stale',
        'review_required', 'confirmation_required', 'assets_unavailable', 'content_invalid', 'keywords_invalid')}
    try:
        with session.no_autoflush:
            candidates = (await session.execute(query)).scalars().all()
        result = []
        for variant_id in candidates:
            try:
                snapshot = await load_source(session, actor_user_id, tenant_id, scope_id, variant_id, platform)
            except HTTPException as exc:
                if exc.status_code == 409 and isinstance(exc.detail, dict) and exc.detail.get('code') in skippable:
                    continue
                raise
            result.append({'variant_id': snapshot['variant_id'], 'source_revision': snapshot['source_revision'],
                'title': snapshot['content']['title'], 'platform': platform})
        await authorize_scope(session, actor_user_id, tenant_id, scope_id)
        return result
    except (SQLAlchemyError, OSError, TimeoutError):
        raise denied('source_unavailable', '来源结构或数据库暂不可用，请稍后核对', 503) from None


async def list_intake_candidates(session, actor_user_id: int, tenant_id: int, scope_id: int,
                                 platform: str, *, after_variant_id=None, limit=50) -> dict:
    """Metadata only, including unfinished review; never a publishing grant.

    Use a short READ COMMITTED transaction. The caller owns that transaction;
    pending ORM edits are neither flushed nor used. Rescan from None after the
    last page to discover review changes on existing IDs. Database/identity
    failures abort the entire page. Concurrent source changes require a retry.
    """
    return await _intake_page(session, actor_user_id, tenant_id, scope_id, platform,
                              after_variant_id=after_variant_id, limit=limit)


async def load_intake_candidate(session, actor_user_id: int, tenant_id: int, scope_id: int,
                                variant_id: int, platform: str) -> dict | None:
    """Return current metadata or None for a noncandidate, never hide failures.

    A replaced, absent, foreign-scope/platform or unfinished ID is no longer an
    intake candidate. Pending approval/adaptation remains a candidate. The same
    session and scalar reads are used as listing; no extra connection is opened.
    """
    if not positive(variant_id):
        raise denied('invalid_scope', '需要有效渠道稿编号', 422)
    page = await _intake_page(session, actor_user_id, tenant_id, scope_id, platform,
                              limit=1, wanted_variant_id=variant_id)
    return page['items'][0] if page['items'] else None


async def _intake_page(session, actor_user_id, tenant_id, scope_id, platform, *,
                       after_variant_id=None, limit=50, wanted_variant_id=None):
    await authorize_scope(session, actor_user_id, tenant_id, scope_id)
    if not isinstance(platform, str) or platform not in PLATFORMS:
        raise denied('platform_unsupported', '该平台尚未接入 SEO 来源', 422)
    if type(limit) is not int or not 1 <= limit <= 50 or (
            after_variant_id is not None and not positive(after_variant_id)):
        raise denied('invalid_cursor', '游标须为正整数，分页数量须为 1 至 50 的整数', 422)

    v, c, account = SeoDistributionVariant, SeoContentAsset, SeoDistributionConnection
    newer = aliased(v)
    # Determine latest before filtering status: a generating newer revision
    # must not expose an older, previously approved revision as current.
    latest = select(newer.id).where(newer.tenant_id == tenant_id,
        newer.content_asset_id == v.content_asset_id, newer.connection_id == v.connection_id
        ).order_by(newer.revision_number.desc(), newer.id.desc()).limit(1).correlate(v).scalar_subquery()
    version_fields = {
        'variant': (v, ('id', 'source_version', 'revision_number', 'title', 'content', 'excerpt')),
        'content': (c, ('id', 'version_count', 'title', 'outline', 'draft', 'humanized_content', 'source_text')),
    }
    columns = [getattr(model, name).label(prefix + '_' + name)
        for prefix, (model, names) in version_fields.items() for name in names]
    version_keys = [column.key for column in columns]
    # These fields detect concurrent changes but deliberately do not affect
    # draft_version. Approval/connection changes must reuse the same queue item.
    columns += [v.status.label('status'), v.reviewed_by.label('reviewed_by'),
        v.reviewed_at.label('reviewed_at'), v.updated_at.label('updated_at')]
    has_media = await media_installed(session, platform)
    if has_media:
        columns.append(literal_column("""(SELECT jsonb_build_object(
            'id', b.id, 'manifest', b.manifest, 'draft_hash', b.draft_hash)
            FROM seo_distribution_media_sets b
            WHERE b.variant_id=seo_distribution_variants.id AND b.tenant_id=seo_distribution_variants.tenant_id
            ORDER BY b.created_at DESC,b.id DESC LIMIT 1)""").label('material'))
        version_keys.append('material')
    query = select(*columns).join(c, c.id == v.content_asset_id).join(account, account.id == v.connection_id
        ).where(v.tenant_id == tenant_id, c.tenant_id == tenant_id, c.site_id == scope_id,
            account.tenant_id == tenant_id, v.platform_code.in_(PLATFORMS[platform]),
            account.platform_code == v.platform_code, c.content_type == 'article', v.id == latest,
            v.status.in_(('draft', 'pending_review', 'approved', 'rejected', 'published')),
            v.id > (after_variant_id or 0)).order_by(v.id).limit(limit + 1)
    if wanted_variant_id is not None:
        query = query.where(v.id == wanted_variant_id)
    waits = {
        'review_required': 'awaiting-review', 'confirmation_required': 'awaiting-review',
        'connection_unavailable': 'awaiting-adaptation', 'source_stale': 'awaiting-adaptation',
        'assets_unavailable': 'awaiting-adaptation', 'content_invalid': 'awaiting-adaptation',
        'keywords_invalid': 'awaiting-adaptation',
    }
    try:
        with session.no_autoflush:
            rows = (await session.execute(query)).mappings().all()
            items = []
            for row in rows[:limit]:
                version = 'seo-draft-' + hashlib.sha256(json.dumps(
                    {key: row[key] for key in version_keys if key != 'material'
                     or platform == 'xiaohongshu-image' or row['material'] is not None}, ensure_ascii=False,
                    sort_keys=True, default=str).encode()).hexdigest()
                revision, readiness, reason = None, 'ready', 'ready'
                try:
                    snapshot = await load_source(session, actor_user_id, tenant_id, scope_id,
                                                 row['variant_id'], platform)
                    revision = snapshot['source_revision']
                    if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', revision):
                        raise denied('source_unavailable', '来源版本格式不兼容', 503)
                except HTTPException as exc:
                    code = exc.detail.get('code') if isinstance(exc.detail, dict) else None
                    short_code = code.removeprefix('seo_distribution_') if isinstance(code, str) else None
                    if exc.status_code != 409 or short_code not in waits:
                        raise
                    readiness, reason = waits[short_code], short_code
                items.append({'variant_id': row['variant_id'], 'draft_version': version,
                    'source_revision': revision, 'readiness': readiness, 'reason': reason})
            # Do not pair a version selected before an edit with a ready seal
            # loaded after it, or return a superseded latest revision.
            if rows != (await session.execute(query)).mappings().all():
                raise denied('source_changed', '读取期间来源发生变化，请重新读取本页')
            await authorize_scope(session, actor_user_id, tenant_id, scope_id)
            return {'items': items, 'next_cursor': items[-1]['variant_id'] if len(rows) > limit else None}
    except (SQLAlchemyError, OSError, TimeoutError):
        raise denied('source_unavailable', '来源结构或数据库暂不可用，请稍后核对', 503) from None


async def _load(session, actor, tenant, scope, variant_id, platform):
    from app.api.seo import _content_confirmation_hash, _prepare_distribution_variant
    from app.seo_distribution import SeoDistributionError

    u, r, s, m = User, Role, SeoSite, TenantModule
    v, c, connection, confirm = SeoDistributionVariant, SeoContentAsset, SeoDistributionConnection, SeoContentConfirmation
    newer = aliased(v)
    latest_variant = select(newer.id).where(newer.tenant_id == tenant,
        newer.content_asset_id == v.content_asset_id, newer.connection_id == v.connection_id
        ).order_by(newer.revision_number.desc(), newer.id.desc()).limit(1).correlate(v).scalar_subquery()
    latest_confirmation = select(confirm.id).where(confirm.tenant_id == tenant,
        confirm.content_asset_id == v.content_asset_id).order_by(confirm.created_at.desc(), confirm.id.desc()
        ).limit(1).correlate(v).scalar_subquery()
    assigned = select(SeoSiteAdvisorAssignment.id).where(
        SeoSiteAdvisorAssignment.tenant_id == tenant, SeoSiteAdvisorAssignment.site_id == scope,
        SeoSiteAdvisorAssignment.advisor_user_id == actor, SeoSiteAdvisorAssignment.active.is_(True)).exists()
    k = SeoKeywordAsset
    keywords = select(func.jsonb_agg(func.jsonb_build_object('id', k.id, 'tenant_id', k.tenant_id,
        'site_id', k.site_id, 'keyword', k.keyword))).where(or_(
            c.keyword_ids.contains(func.jsonb_build_array(k.id)),
            and_(c.keyword_ids.is_(None), k.id == c.keyword_id))).correlate(c).scalar_subquery()
    fields = {
        'user': (u, ('id','role_id','tenant_id','is_active')),
        'role': (r, ('id','permissions')),
        'site': (s, ('id','tenant_id','status','canonical_domain','site_settings')),
        'module': (m, ('id','tenant_id','module_code','status','expires_at')),
        'variant': (v, ('id','tenant_id','content_asset_id','connection_id','platform_code','source_version',
            'revision_number','status','title','content','reviewed_by','reviewed_at','updated_at')),
        'content': (c, ('id','tenant_id','site_id','content_type','title','outline','draft','humanized_content',
            'source_text','version_count','status','keyword_ids','keyword_id','reviewed_by','reviewed_at')),
        'connection': (connection, ('id','tenant_id','platform_code','enabled','mode','status')),
        'confirmation': (confirm, ('id','tenant_id','site_id','content_version','content_hash','decision',
            'actor_mode','actor_user_id','created_at')),
    }
    columns = [getattr(model, name).label(prefix+'_'+name)
        for prefix, (model, names) in fields.items() for name in names]
    has_media = await media_installed(session, platform)
    if has_media:
        columns.append(literal_column("""(SELECT jsonb_build_object(
            'id',b.id,'tenant_id',b.tenant_id,'site_id',b.site_id,'manifest',b.manifest,
            'draft_hash',b.draft_hash,'uploaded_by',b.uploaded_by,
            'reviewed_by',r.reviewed_by,'reviewed_at',r.reviewed_at,'variant_seal',r.variant_seal,
            'records',(SELECT jsonb_agg(jsonb_build_object('id',a.id,'sha256',a.sha256,
                'mediaType',a.media_type,'bytes',a.byte_count) ORDER BY a.position)
                FROM seo_distribution_media_bytes a WHERE a.set_id=b.id))
            FROM seo_distribution_media_sets b LEFT JOIN seo_distribution_media_reviews r ON r.set_id=b.id
            WHERE b.variant_id=seo_distribution_variants.id ORDER BY b.created_at DESC,b.id DESC LIMIT 1)""").label('media'))
        columns.append(v.created_by.label('variant_creator'))
    # One PostgreSQL statement gives identity, permissions, scope, versions,
    # latest confirmation and selected keywords the same MVCC snapshot.
    query = select(*columns, assigned.label('assigned'), latest_variant.label('latest_variant'),
        keywords.label('keywords')).select_from(u).outerjoin(r, r.id == u.role_id
        ).outerjoin(s, s.id == scope).outerjoin(m, m.id == s.tenant_module_id
        ).outerjoin(v, v.id == variant_id).outerjoin(c, c.id == v.content_asset_id
        ).outerjoin(connection, connection.id == v.connection_id
        ).outerjoin(confirm, confirm.id == latest_confirmation).where(u.id == actor)
    row = (await session.execute(query)).mappings().one_or_none()
    _check_scope(row,tenant)  # recheck in the same MVCC snapshot as the body
    data = {prefix: SimpleNamespace(**{name: row[prefix+'_'+name] for name in names})
        for prefix, (_, names) in fields.items()}
    variant, content, account, approval = (data[n] for n in ('variant','content','connection','confirmation'))
    if (variant.id is None or variant.tenant_id != tenant or content.tenant_id != tenant
            or content.site_id != scope or account.tenant_id != tenant):
        raise denied('source_not_found', '当前网站的渠道稿不存在', 404)
    if variant.platform_code not in PLATFORMS[platform] or account.platform_code != variant.platform_code:
        raise denied('platform_mismatch', '渠道稿与目标平台不一致')
    if not account.enabled or account.mode == 'api' and account.status != 'connected':
        raise denied('connection_unavailable', '来源渠道连接已停用或尚未完成核对')
    if content.content_type != 'article':
        raise denied('content_type_unsupported', '首期仅接入文章渠道稿，其他内容类型暂未接入')
    if (not positive(content.version_count) or not positive(variant.revision_number)
            or variant.source_version != content.version_count or row['latest_variant'] != variant.id):
        raise denied('source_stale', '母稿或渠道稿已有更新版本，请重新选择最新稿件')
    if (content.status not in {'ready','published'} or not positive(content.reviewed_by) or not content.reviewed_at
            or variant.status != 'approved' or not positive(variant.reviewed_by) or not variant.reviewed_at):
        raise denied('review_required', '母稿及最新渠道稿均须有人工审核通过记录')
    master_hash = _content_confirmation_hash(content)
    if (not approval.id or approval.site_id != scope or approval.decision != 'approve'
            or approval.content_version != content.version_count or approval.content_hash != master_hash
            or approval.actor_mode not in {'customer_direct','advisor_proxy'} or not positive(approval.actor_user_id)):
        raise denied('confirmation_required', '当前准确母稿版本尚未获得客户确认或顾问代确认')
    assets = []
    media = row['media'] if has_media else None
    if platform == 'xiaohongshu-image' or media is not None:
        from app.seo_distribution_media import draft_hash, variant_seal, MAX_TOTAL, MAX_IMAGES
        if (not media or media['tenant_id']!=tenant or media['site_id']!=scope
                or media['draft_hash']!=draft_hash(vars(variant)) or media['variant_seal']!=variant_seal(vars(variant))
                or media['reviewed_by']!=variant.reviewed_by or media['uploaded_by']==media['reviewed_by']
                or media['reviewed_by']==row['variant_creator']
                or not isinstance(media['manifest'],list) or not 1<=len(media['manifest'])<=(1 if platform=='wechat-article' else MAX_IMAGES)
                or media['manifest']!=media['records'] or sum(a['bytes'] for a in media['manifest'])>MAX_TOTAL):
            raise denied('assets_unavailable','图片尚未独立审核冻结或与当前稿件不符')
        assets = media['manifest']
    if not variant.title or not variant.content or len(variant.content) > 400000:
        raise denied('content_invalid', '渠道稿标题或正文缺失或超出允许范围')
    if re.search(r'!\[[^\]]*\]\s*\(|(?:url\s*\(|srcset\s*=|background\s*=)', variant.content, re.I):
        raise denied('assets_unavailable', '首期仅支持纯文章，配图须先具备可核验素材清单')
    soup = BeautifulSoup(variant.content, 'html.parser')
    if soup.find(['img','picture','video','audio','svg','iframe','object','embed','input']):
        raise denied('assets_unavailable', '首期仅支持纯文章，配图须先具备可核验素材清单')
    try:
        prepared = _prepare_distribution_variant(variant.title, variant.content, variant.platform_code, strict_title=True)
    except (SeoDistributionError, ValueError):
        raise denied('content_invalid', '渠道稿未通过既有平台正文校验') from None
    if prepared['title'] != variant.title or prepared['content'] != variant.content:
        raise denied('content_invalid', '渠道稿仍需内容清理，请重新保存并审核后接入')
    ids = content.keyword_ids if content.keyword_ids is not None else ([content.keyword_id] if content.keyword_id else [])
    registered = row['keywords'] or []
    if (not isinstance(ids,list) or len(ids)>5 or any(not positive(i) for i in ids) or len(set(ids))!=len(ids)
            or set(ids)!={k['id'] for k in registered} or any(k['tenant_id']!=tenant or k['site_id'] not in (None,scope)
                or k['keyword'].casefold() not in prepared['plain_text'].casefold() for k in registered)):
        raise denied('keywords_invalid', '渠道稿未满足当前目标关键词及网站归属要求')
    fingerprint = {'tenant_id':tenant, 'scope_id':scope, 'platform':platform, 'master_hash':master_hash,
        'variant':vars(variant), 'content_review':[content.id,content.reviewed_by,content.reviewed_at],
        'confirmation':vars(approval), 'keywords':sorted(registered,key=lambda item:item['id'])}
    if assets: fingerprint['assets'] = assets
    if assets and platform == 'wechat-article':
        fingerprint['cover_review'] = {key:media[key] for key in ('id','variant_seal','reviewed_by','reviewed_at')}
    digest = hashlib.sha256(json.dumps(fingerprint,ensure_ascii=False,sort_keys=True,default=str).encode()).hexdigest()
    revision = f'seo-m{content.version_count}-v{variant.revision_number}-{digest}'
    return {'module':'seo','tenant_id':tenant,'scope_id':scope,'variant_id':variant_id,'source_revision':revision,
        'content':{'version':revision,'title':variant.title,'body':variant.content,'assets':assets}}


async def load_asset(db, actor_id: int, tenant_id: int, scope_id: int,
                     variant_id: int, platform: str, asset_id: str) -> bytes:
    """Only bytes belonging to the current fully authorized, frozen snapshot."""
    snapshot = await load_source(db,actor_id,tenant_id,scope_id,variant_id,platform)
    item = next((item for item in snapshot['content']['assets'] if item['id']==asset_id),None)
    if not item: raise denied('asset_not_found','已审稿件不存在该图片',404)
    from app.seo_distribution_media import require_strict_decoder, validate_image
    require_strict_decoder()
    try:
        with db.no_autoflush:
            data = await db.scalar(text('SELECT a.data FROM seo_distribution_media_bytes a '
                'JOIN seo_distribution_media_sets b ON b.id=a.set_id '
                'WHERE a.id::text=:id AND b.variant_id=:variant AND b.tenant_id=:tenant AND b.site_id=:scope'),
                {'id':asset_id,'variant':variant_id,'tenant':tenant_id,'scope':scope_id})
        if data is None or len(data)!=item['bytes'] or hashlib.sha256(data).hexdigest()!=item['sha256']:
            raise denied('assets_unavailable','图片字节校验失败')
        import asyncio
        await asyncio.to_thread(validate_image,bytes(data),item['mediaType'])
        if snapshot!=await load_source(db,actor_id,tenant_id,scope_id,variant_id,platform):
            raise denied('source_stale','读取期间已审稿件发生变化')
        return bytes(data)
    except (SQLAlchemyError,OSError,TimeoutError):
        raise denied('source_unavailable','来源结构或数据库暂不可用，请稍后核对',503) from None
