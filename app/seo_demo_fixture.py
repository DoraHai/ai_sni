"""Deterministic, database-neutral SEO demonstration fixture.

The package deliberately uses logical keys instead of database ids.  It is a
reviewable input for a future database-owned loader; importing this module has
no database, crawler, scheduler, AI, or publisher side effects.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from typing import Any
from urllib.parse import unquote, urlsplit


FIXTURE_VERSION = "seo-demo-v1"
DEMO_TENANT_KEY = "g-snipers-global-demo"
DEMO_SITE_KEY = "g-snipers-demo-site"
DEMO_DOMAIN = "g-snipers-seo-demo.example"
FORBIDDEN_TENANT_IDS = {4}


@dataclass(frozen=True)
class DemoDatabaseTarget:
    """Credential-free description of an approved isolated demo database."""

    driver: str
    hostname: str
    port: int | None
    database: str


def validate_demo_database_target(
    database_url: str,
    *,
    allowed_hostnames: set[str] | frozenset[str],
    required_database_name: str,
    runtime_mode: str,
) -> DemoDatabaseTarget:
    """Validate the target for a future loader without opening a connection.

    The caller must supply an exact, non-wildcard hostname allowlist and exact
    database name from deployment configuration.  This is only a reusable
    fail-closed guard; the repository intentionally has no database apply path.
    """
    if runtime_mode.strip().lower() != "demo":
        raise ValueError("SEO demo loader requires runtime_mode=demo")
    hosts = {str(value).strip().lower().rstrip(".") for value in allowed_hostnames}
    if not hosts or any(not value or "*" in value for value in hosts):
        raise ValueError("an exact non-wildcard demo database hostname allowlist is required")
    required_name = required_database_name.strip()
    if not required_name or "/" in required_name or required_name.lower() in {
        "postgres",
        "template0",
        "template1",
    }:
        raise ValueError("an exact dedicated demo database name is required")
    try:
        parsed = urlsplit(database_url.strip())
        hostname = (parsed.hostname or "").lower().rstrip(".")
        port = parsed.port
    except ValueError as exc:
        raise ValueError("invalid demo database URL") from exc
    if parsed.scheme not in {
        "postgresql",
        "postgresql+asyncpg",
        "postgresql+psycopg",
        "postgresql+psycopg2",
    }:
        raise ValueError("demo loader only supports PostgreSQL")
    if not hostname or hostname not in hosts:
        raise ValueError("database hostname is not in the exact demo allowlist")
    database = unquote(parsed.path.lstrip("/"))
    if not database or "/" in database or database != required_name:
        raise ValueError("database name does not match the dedicated demo database")
    return DemoDatabaseTarget(
        driver=parsed.scheme,
        hostname=hostname,
        port=port,
        database=database,
    )


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _ref(table: str, key: str) -> dict[str, str]:
    return {"table": table, "key": key}


def _row(key: str, **values: Any) -> dict[str, Any]:
    return {"_key": key, **values}


def build_seo_demo_fixture(
    *, anchor: datetime | None = None, proposed_tenant_id: int | None = None
) -> dict[str, Any]:
    """Build one repeatable synthetic SEO data package.

    ``anchor`` controls all relative timestamps.  The default is fixed so two
    executions produce byte-for-byte equivalent JSON after canonical encoding.
    ``proposed_tenant_id`` is metadata only and is rejected when it could target
    Tiger's tenant 4.
    """
    if proposed_tenant_id in FORBIDDEN_TENANT_IDS:
        raise ValueError("tenant_id=4 belongs to Tiger and cannot receive demo data")
    anchor = anchor or datetime(2026, 9, 1, 8, 0, tzinfo=timezone.utc)
    if anchor.tzinfo is None:
        raise ValueError("anchor must include a timezone")
    anchor = anchor.astimezone(timezone.utc).replace(microsecond=0)

    tables: dict[str, list[dict[str, Any]]] = {
        name: []
        for name in (
            "tenants",
            "tenant_modules",
            "seo_sites",
            "seo_metric_snapshots",
            "seo_keyword_assets",
            "seo_rank_snapshots",
            "seo_serp_results",
            "seo_site_pages",
            "seo_page_index_reviews",
            "seo_crawl_runs",
            "seo_page_snapshots",
            "seo_content_assets",
            "seo_content_review_events",
            "seo_distribution_connections",
            "seo_content_publications",
            "seo_publish_attempts",
            "seo_image_alt_reviews",
            "seo_image_verifications",
            "seo_internal_links",
            "seo_backlinks",
            "seo_competitors",
            "seo_competitor_events",
            "seo_tasks",
            "seo_automation_runs",
        )
    }
    tenant_ref = _ref("tenants", DEMO_TENANT_KEY)
    site_ref = _ref("seo_sites", DEMO_SITE_KEY)
    module_ref = _ref("tenant_modules", "g-snipers-demo-seo-module")
    tables["tenants"].append(
        _row(
            DEMO_TENANT_KEY,
            proposed_id=proposed_tenant_id,
            name="G-Snipers 全域演示（虚拟数据）",
            industry="工业自动化演示",
            business_desc="仅用于产品演示；企业、产品、页面及指标均为虚构。",
            fixture_marker=FIXTURE_VERSION,
        )
    )
    tables["tenant_modules"].append(
        _row(
            "g-snipers-demo-seo-module",
            tenant=tenant_ref,
            module_code="seo",
            status="active",
            expires_at=None,
            module_settings={"fixture_marker": FIXTURE_VERSION, "synthetic": True},
        )
    )
    tables["seo_sites"].append(
        _row(
            DEMO_SITE_KEY,
            tenant=tenant_ref,
            tenant_module=module_ref,
            name="星虎机器人演示站（虚拟）",
            domain=DEMO_DOMAIN,
            canonical_domain=DEMO_DOMAIN,
            default_url=f"https://{DEMO_DOMAIN}/",
            status="paused",
            site_settings={
                "fixture_marker": FIXTURE_VERSION,
                "synthetic": True,
                "scheduler_excluded": True,
                "external_actions_disabled": True,
                "google_search_console": {"enabled": False, "property_url": None},
            },
        )
    )

    # 90 daily, site-level search observations.  The explicit synthetic source
    # prevents these values from being mistaken for Search Console evidence.
    for day in range(90):
        observed = anchor - timedelta(days=89 - day)
        phase = day / 89
        impressions = round(2100 + 3100 * phase + (day % 7) * 37)
        clicks = round(72 + 188 * phase + (day % 5) * 3)
        values = {
            "gsc_impressions": (impressions, "impressions"),
            "gsc_clicks": (clicks, "clicks"),
            "gsc_ctr": (round(clicks / impressions, 4), "ratio"),
            "gsc_position": (round(24.8 - 10.6 * phase + (day % 6) * 0.18, 2), "position"),
        }
        for metric_type, (value, unit) in values.items():
            tables["seo_metric_snapshots"].append(
                _row(
                    f"search-{observed.date()}-{metric_type}",
                    tenant=tenant_ref,
                    site=site_ref,
                    metric_type=metric_type,
                    dimension="daily_site_total",
                    numeric_value=value,
                    unit=unit,
                    source="demo_fixture",
                    data_quality="estimated",
                    status="available",
                    observed_at=_iso(observed),
                    raw_payload={
                        "synthetic": True,
                        "fixture_marker": FIXTURE_VERSION,
                        "scope": "site_daily_total",
                        "article_attribution": "unsupported",
                    },
                )
            )
    tables["seo_metric_snapshots"].append(
        _row(
            "site-index-estimate-latest",
            tenant=tenant_ref,
            site=site_ref,
            metric_type="baidu_index_estimate",
            dimension="site_total",
            numeric_value=38,
            unit="pages",
            source="demo_fixture",
            data_quality="estimated",
            status="available",
            observed_at=_iso(anchor),
            raw_payload={
                "synthetic": True,
                "fixture_marker": FIXTURE_VERSION,
                "scope": "site_total_estimate",
                "article_attribution": "unsupported",
                "page_level_inclusion": "unsupported",
            },
        )
    )

    keywords = [
        ("协作机器人选型", "选型", "商业", "P0", "improving", "/guides/cobot-selection"),
        ("六轴机器人价格", "价格", "价格", "P0", "declining", "/products/six-axis"),
        ("码垛机器人方案", "场景", "方案", "P1", "improving", "/solutions/palletizing"),
        ("机器人视觉定位", "技术", "学习", "P1", "stable", "/guides/vision-positioning"),
        ("工业机器人维护", "维护", "学习", "P1", "declining", "/guides/maintenance"),
        ("焊接机器人工作站", "场景", "产品", "P1", "improving", "/solutions/welding"),
        ("机器人安全围栏", "安全", "产品", "P2", "stable", "/products/safety-fence"),
        ("机器人重复定位精度", "参数", "对比", "P2", "improving", "/guides/repeatability"),
        ("国产机器人品牌对比", "品牌", "对比", "P2", "declining", "/guides/brand-comparison"),
        ("机器人集成商", "服务", "决策", "P2", "stable", "/services/integration"),
        ("自动化产线改造", "场景", "方案", "P3", "improving", "/solutions/line-upgrade"),
        ("机器人培训课程", "服务", "学习", "P3", "declining", "/services/training"),
    ]
    for idx, (keyword, cluster, intent, priority, scenario, path) in enumerate(keywords, 1):
        key = f"kw-{idx:02d}"
        landing = f"https://{DEMO_DOMAIN}{path}"
        tables["seo_keyword_assets"].append(
            _row(
                key,
                tenant=tenant_ref,
                site=site_ref,
                keyword=keyword,
                cluster=cluster,
                intent=intent,
                monthly_volume=700 + idx * 210,
                difficulty=28 + idx * 3,
                priority=priority,
                landing_page=landing,
                status="active",
                source="demo_fixture",
                notes=f"{FIXTURE_VERSION}; synthetic scenario={scenario}",
            )
        )
        for point in range(13):
            checked = anchor - timedelta(days=(12 - point) * 7)
            if scenario == "improving":
                rank = max(3, 31 - point * 2 - idx % 3)
            elif scenario == "declining":
                rank = min(48, 8 + point * 2 + idx % 4)
            else:
                rank = 14 + ((point + idx) % 3) - 1
            tables["seo_rank_snapshots"].append(
                _row(
                    f"{key}-rank-{point:02d}",
                    tenant=tenant_ref,
                    site=site_ref,
                    keyword=_ref("seo_keyword_assets", key),
                    engine="baidu",
                    device="desktop",
                    region="全国",
                    domain=DEMO_DOMAIN,
                    subject_type="own",
                    rank=rank,
                    result_url=landing,
                    source="demo_fixture",
                    checked_at=_iso(checked),
                )
            )

    pages = [
        ("home", "/", "星虎机器人", "healthy", 200, 92, [], True),
        ("selection", "/guides/cobot-selection", "协作机器人选型指南", "verified", 200, 94, [], True),
        ("six-axis", "/products/six-axis", "六轴机器人", "needs_fix", 200, 68, ["title_too_long"], True),
        ("pallet", "/solutions/palletizing", "码垛机器人方案", "implemented", 200, 83, ["image_alt_missing"], True),
        ("vision", "/guides/vision-positioning", "视觉定位", "needs_fix", 200, 71, ["description_missing"], True),
        ("maintenance", "/guides/maintenance", "工业机器人维护", "verified", 200, 96, [], True),
        ("welding", "/solutions/welding", "焊接工作站", "healthy", 200, 90, [], True),
        ("legacy", "/old/training", "旧培训页", "error", 404, 20, ["http_4xx"], False),
        ("noindex", "/campaign/private-offer", "活动落地页", "needs_fix", 200, 62, ["noindex"], False),
        ("timeout", "/guides/heavy-report", "大型报告", "error", None, 0, ["timeout"], None),
    ]
    for idx, (key, path, title, status, http, score, issues, indexable) in enumerate(pages):
        tables["seo_site_pages"].append(
            _row(
                f"page-{key}",
                tenant=tenant_ref,
                site=site_ref,
                url=f"https://{DEMO_DOMAIN}{path}",
                page_type="home" if key == "home" else "article",
                title=title,
                meta_description=f"{title}的虚拟演示摘要。",
                h1=title,
                canonical=f"https://{DEMO_DOMAIN}{path}",
                indexable=indexable,
                http_status=http,
                content_units=5 + idx,
                audit_score=score,
                issue_codes=issues,
                status=status,
                last_error="演示：上游响应超时" if key == "timeout" else None,
                last_checked_at=_iso(anchor - timedelta(hours=idx + 1)),
            )
        )

    for key, page_key, intent, reason in (
        ("index-intent", "page-selection", "index", "演示：希望公开指南参与索引"),
        ("noindex-intent", "page-noindex", "noindex", "演示：活动页不进入自然搜索"),
        ("undecided-intent", "page-vision", "undecided", "演示：等待内容负责人确认"),
    ):
        tables["seo_page_index_reviews"].append(
            _row(
                key,
                tenant=tenant_ref,
                site=site_ref,
                page=_ref("seo_site_pages", page_key),
                intent=intent,
                reason=reason,
                actor_id=900002,
                actor_name="演示审核员",
                evidence={
                    "synthetic": True,
                    "fixture_marker": FIXTURE_VERSION,
                    "meaning": "human_indexing_intent_not_verified_inclusion",
                },
                created_at=_iso(anchor - timedelta(days=3)),
            )
        )

    # Completed runs and stored snapshots are evidence only; no queued run can
    # be picked up by a worker.
    for run_idx, days_ago in enumerate((28, 14, 7, 0), 1):
        run_key = f"crawl-{run_idx}"
        run_at = anchor - timedelta(days=days_ago)
        tables["seo_crawl_runs"].append(
            _row(
                run_key,
                tenant=tenant_ref,
                site=site_ref,
                status="completed",
                seed_url=f"https://{DEMO_DOMAIN}/",
                max_urls=50,
                discovered_count=10,
                fetched_count=9,
                failed_count=1,
                blocked_count=0,
                issue_count=4 if run_idx < 4 else 3,
                started_at=_iso(run_at - timedelta(minutes=2)),
                completed_at=_iso(run_at),
                error_summary="虚拟快照：1 个超时页面",
            )
        )
        for page_key in ("home", "selection", "pallet", "maintenance", "legacy", "timeout"):
            page = next(row for row in tables["seo_site_pages"] if row["_key"] == f"page-{page_key}")
            fixed_image = page_key == "pallet" and run_idx == 4
            is_timeout = page_key == "timeout"
            is_404 = page_key == "legacy"
            evidence_items = []
            if page_key == "pallet":
                evidence_items = [
                    {
                        "position": 2,
                        "section": "安全配置",
                        "source_url": f"https://assets.{DEMO_DOMAIN}/pallet-safety.example.jpg",
                        "source_attribute": "src",
                        "in_link": False,
                        "alt_state": "missing",
                    }
                ]
                if not fixed_image:
                    evidence_items.insert(0,
                    {
                        "position": 1,
                        "section": "方案结构",
                        "source_url": f"https://assets.{DEMO_DOMAIN}/pallet-cell.example.jpg",
                        "source_attribute": "src",
                        "in_link": False,
                        "alt_state": "missing",
                    })
            tables["seo_page_snapshots"].append(
                _row(
                    f"{run_key}-{page_key}",
                    tenant=tenant_ref,
                    site=site_ref,
                    crawl_run=_ref("seo_crawl_runs", run_key),
                    url=page["url"],
                    final_url=page["url"],
                    discovery_source="demo_fixture",
                    click_depth=0 if page_key == "home" else 1,
                    status_code=None if is_timeout else 404 if is_404 else 200,
                    fetch_error="演示：连接超时" if is_timeout else None,
                    error_type="timeout" if is_timeout else None,
                    content_type=None if is_timeout else "text/html; charset=utf-8",
                    content_length=None if is_timeout else 4200 + run_idx * 110,
                    response_time_ms=None if is_timeout else 180 + run_idx * 7,
                    raw_html_hash=sha256(f"{run_key}:{page_key}".encode()).hexdigest(),
                    robots_allowed=None if is_timeout else True,
                    meta_robots="noindex" if page_key == "noindex" else "index,follow",
                    canonical_url=page["canonical"],
                    indexable=False if is_404 else None if is_timeout else True,
                    title=page["title"],
                    title_length=len(page["title"]),
                    meta_description=page["meta_description"],
                    description_length=len(page["meta_description"]),
                    h1_texts=[page["title"]],
                    h1_count=1,
                    html_lang="zh-CN",
                    main_content_extractable=not (is_timeout or is_404),
                    word_count=None if is_timeout else 900,
                    schema_types=["Article"] if page_key != "home" else ["Organization", "WebSite"],
                    internal_links_count=4,
                    external_links_count=1,
                    images_count=3 if page_key == "pallet" else 1,
                    images_missing_alt_count=len(evidence_items),
                    image_alt_evidence={
                        "synthetic": True,
                        "candidate_count": len(evidence_items),
                        "items": evidence_items,
                    },
                    issue_codes=([] if fixed_image else page["issue_codes"]),
                    fetched_at=_iso(run_at),
                )
            )

    content_specs = [
        ("draft", "协作机器人选型清单", "planned", None),
        ("writing", "六轴机器人采购指南", "drafting", None),
        ("review", "视觉定位误差排查", "review", None),
        ("ready", "焊接工作站上线前检查", "ready", None),
        ("published-a", "码垛产线改造案例", "published", 5),
        ("published-b", "工业机器人维护周期", "published", 2),
        ("publish-failed", "国产机器人对比方法", "ready", None),
        ("archived", "2025 年旧型号盘点", "archived", None),
    ]
    for idx, (key, title, status, published_days_ago) in enumerate(content_specs, 1):
        content_key = f"content-{key}"
        published_at = (
            _iso(anchor - timedelta(days=published_days_ago))
            if published_days_ago is not None
            else None
        )
        tables["seo_content_assets"].append(
            _row(
                content_key,
                tenant=tenant_ref,
                site=site_ref,
                source_page=None,
                keyword=_ref("seo_keyword_assets", f"kw-{min(idx, 12):02d}"),
                keyword_ids=[_ref("seo_keyword_assets", f"kw-{min(idx, 12):02d}")],
                content_type="article",
                title=title,
                outline=f"{title}：背景、方案、核对清单。",
                draft=f"【虚拟演示内容】{title}。所有企业、产品与结果均为虚构。",
                target_platforms=["知乎", "百家号"] if status in {"ready", "published"} else [],
                version_count=2 if status in {"review", "ready", "published"} else 1,
                status=status,
                page_url=(
                    f"https://zhihu.example/demo/{key}" if status == "published" else None
                ),
                author="演示内容组（非真实负责人）",
                published_at=published_at,
                review_submitted_by=900001 if status in {"review", "ready", "published"} else None,
                review_submitted_at=_iso(anchor - timedelta(days=8)) if status in {"review", "ready", "published"} else None,
                reviewed_by=900002 if status in {"ready", "published"} else None,
                reviewed_at=_iso(anchor - timedelta(days=7)) if status in {"ready", "published"} else None,
                created_by=900001,
            )
        )
        if status in {"review", "ready", "published"}:
            tables["seo_content_review_events"].append(
                _row(
                    f"review-submit-{key}",
                    tenant=tenant_ref,
                    site=site_ref,
                    content=_ref("seo_content_assets", content_key),
                    action="submit",
                    from_status="drafting",
                    to_status="review",
                    note="虚拟演示审核记录",
                    actor_id=900001,
                    created_at=_iso(anchor - timedelta(days=8)),
                )
            )
        if status in {"ready", "published"}:
            tables["seo_content_review_events"].append(
                _row(
                    f"review-approve-{key}",
                    tenant=tenant_ref,
                    site=site_ref,
                    content=_ref("seo_content_assets", content_key),
                    action="approve",
                    from_status="review",
                    to_status="ready",
                    note="虚拟演示：独立审核人通过",
                    actor_id=900002,
                    created_at=_iso(anchor - timedelta(days=7)),
                )
            )

    for platform, label in (("zhihu", "知乎演示入口"), ("baijiahao", "百家号演示入口")):
        tables["seo_distribution_connections"].append(
            _row(
                f"connection-{platform}",
                tenant=tenant_ref,
                platform_code=platform,
                name=label,
                mode="assisted",
                base_url=None,
                config={"fixture_marker": FIXTURE_VERSION, "synthetic": True},
                capabilities=["copy", "handoff"],
                credentials_encrypted=None,
                has_credentials=False,
                enabled=False,
                status="unconfigured",
                last_error="演示连接：禁止真实平台动作",
            )
        )

    publications = [
        ("pub-a-zhihu", "content-published-a", "zhihu", "知乎", "published", "https://zhihu.example/demo/pallet-case", None),
        ("pub-a-baijia", "content-published-a", "baijiahao", "百家号", "published", "https://baijiahao.example/demo/pallet-case", None),
        ("pub-b-zhihu", "content-published-b", "zhihu", "知乎", "published", f"https://{DEMO_DOMAIN}/guides/maintenance", None),
        ("pub-failed", "content-publish-failed", "baijiahao", "百家号", "failed", None, "演示失败：平台拒绝了过长标题"),
        ("pub-ready", "content-ready", "zhihu", "知乎", "manual_required", None, None),
    ]
    for idx, (key, content_key, platform, name, status, page_url, error) in enumerate(publications):
        tables["seo_content_publications"].append(
            _row(
                key,
                tenant=tenant_ref,
                content=_ref("seo_content_assets", content_key),
                connection=_ref("seo_distribution_connections", f"connection-{platform}"),
                platform_code=platform,
                platform_name=name,
                publish_mode="assisted",
                status=status,
                source_version=2,
                adapted_title=next(row["title"] for row in tables["seo_content_assets"] if row["_key"] == content_key),
                external_id=f"demo-{idx+1}" if status == "published" else None,
                page_url=page_url,
                handoff_url=None,
                idempotency_key=f"{FIXTURE_VERSION}-{key}",
                last_error=error,
                published_at=_iso(anchor - timedelta(days=5 - min(idx, 3))) if status == "published" else None,
                link_discovery={"synthetic": True, "state": "fixture_only"},
            )
        )
        attempt_status = "succeeded" if status == "published" else "failed" if status == "failed" else "prepared"
        tables["seo_publish_attempts"].append(
            _row(
                f"attempt-{key}",
                tenant=tenant_ref,
                publication=_ref("seo_content_publications", key),
                action="assisted_handoff",
                status=attempt_status,
                request_summary={"synthetic": True, "provider_called": False},
                response_summary={"fixture_marker": FIXTURE_VERSION, "provider_called": False},
                error=error,
                started_at=_iso(anchor - timedelta(days=6 - min(idx, 3))),
                completed_at=_iso(anchor - timedelta(days=6 - min(idx, 3), minutes=-1)),
            )
        )

    # One approved image repair has a later synthetic crawl proving the issue
    # disappeared.  Another remains pending for the task list.
    old_snapshot = _ref("seo_page_snapshots", "crawl-3-pallet")
    latest_snapshot = _ref("seo_page_snapshots", "crawl-4-pallet")
    for key, status, result in (
        ("image-fixed", "verified", latest_snapshot),
        ("image-pending", "pending", None),
    ):
        review_key = f"review-{key}"
        tables["seo_image_alt_reviews"].append(
            _row(
                review_key,
                tenant=tenant_ref,
                site=site_ref,
                page=_ref("seo_site_pages", "page-pallet"),
                snapshot=old_snapshot if key == "image-fixed" else latest_snapshot,
                position=1 if key == "image-fixed" else 2,
                source_url=f"https://assets.{DEMO_DOMAIN}/{key}.example.jpg",
                observed_alt_state="missing",
                decision="informative",
                alt_suggestion="虚拟码垛机器人工作单元示意图",
                note="虚拟演示修复方案",
                review_status="approved",
                actor_id=900002,
                actor_name="演示审核员",
                reviewed_at=_iso(anchor - timedelta(days=6)),
            )
        )
        tables["seo_image_verifications"].append(
            _row(
                f"verify-{key}",
                tenant=tenant_ref,
                site=site_ref,
                page=_ref("seo_site_pages", "page-pallet"),
                review=_ref("seo_image_alt_reviews", review_key),
                status=status,
                approved_at=_iso(anchor - timedelta(days=6)),
                available_at=_iso(anchor + timedelta(days=30)) if status == "pending" else _iso(anchor - timedelta(days=5)),
                checked_at=_iso(anchor) if status == "verified" else None,
                evidence={
                    "synthetic": True,
                    "fixture_marker": FIXTURE_VERSION,
                    "outcome": "alt_confirmed_after_recrawl" if status == "verified" else "awaiting_demo_verification",
                },
                result_snapshot=result,
            )
        )

    link_specs = [
        ("home", "selection", "选型指南"),
        ("home", "six-axis", "六轴机器人"),
        ("home", "pallet", "码垛方案"),
        ("selection", "vision", "视觉定位"),
        ("selection", "maintenance", "维护建议"),
        ("six-axis", "legacy", "旧培训资料"),
        ("pallet", "welding", "焊接方案"),
        ("vision", "selection", "选型基础"),
        ("maintenance", "home", "返回首页"),
        ("welding", "pallet", "码垛案例"),
        ("home", "noindex", "活动方案"),
        ("noindex", "home", "官网"),
    ]
    for idx, (source, target, anchor_text) in enumerate(link_specs, 1):
        tables["seo_internal_links"].append(
            _row(
                f"internal-{idx:02d}",
                tenant=tenant_ref,
                site=site_ref,
                source_page=_ref("seo_site_pages", f"page-{source}"),
                target_page=_ref("seo_site_pages", f"page-{target}"),
                anchor_text=anchor_text,
                discovered_at=_iso(anchor - timedelta(days=1)),
            )
        )

    backlink_specs = [
        ("automation-news.example", "selection", "found", "active", 74),
        ("robot-forum.example", "pallet", "found", "active", 61),
        ("industry-directory.example", "home", "found", "active", 55),
        ("old-blog.example", "maintenance", "missing", "lost", 43),
        ("spam-list.example", "home", "found", "ignored", 8),
        ("partner-lab.example", "vision", "unverified", "paused", 69),
    ]
    for idx, (source_domain, target, verification_state, status, authority) in enumerate(backlink_specs, 1):
        tables["seo_backlinks"].append(
            _row(
                f"backlink-{idx:02d}",
                tenant=tenant_ref,
                site=site_ref,
                source_url=f"https://{source_domain}/virtual/reference-{idx}",
                target_url=next(row["url"] for row in tables["seo_site_pages"] if row["_key"] == f"page-{target}"),
                source_domain=source_domain,
                anchor_text="虚拟引用",
                authority_score=authority,
                toxic_score=82 if status == "ignored" else 9,
                status=status,
                first_seen_at=_iso(anchor - timedelta(days=70 - idx)),
                last_seen_at=_iso(anchor - timedelta(days=idx)),
                last_checked_at=_iso(anchor - timedelta(days=idx)),
                verification={"state": verification_state, "synthetic": True, "provider_called": False},
                missing_checks=2 if verification_state == "missing" else 0,
            )
        )

    competitors = [
        ("competitor-a", "灵虎机器人（虚拟竞品）", "linghu-robot.example"),
        ("competitor-b", "锐虎机器人（虚拟竞品）", "ruihu-robot.example"),
        ("competitor-c", "云虎机器人（虚拟竞品）", "yunhu-robot.example"),
    ]
    for idx, (key, name, domain) in enumerate(competitors, 1):
        tables["seo_competitors"].append(
            _row(
                key,
                tenant=tenant_ref,
                site=site_ref,
                name=name,
                domain=domain,
                notes=f"{FIXTURE_VERSION}; synthetic competitor",
                status="active",
                last_checked_at=_iso(anchor - timedelta(days=idx)),
            )
        )
        tables["seo_competitor_events"].append(
            _row(
                f"event-{key}",
                tenant=tenant_ref,
                site=site_ref,
                competitor=_ref("seo_competitors", key),
                event_type="new_content",
                title=f"{name}发布虚拟新品页",
                url=f"https://{domain}/virtual/new-product",
                source_url=f"https://{domain}/",
                summary="完全虚构的竞品动态，仅用于界面演示。",
                event_at=_iso(anchor - timedelta(days=idx * 3)),
                detected_at=_iso(anchor - timedelta(days=idx * 3 - 1)),
            )
        )

    # The competitor ranking endpoint reads the latest SERP batch and matches
    # domains against active competitor records.  These are stored synthetic
    # observations and cannot schedule or perform a provider request.
    for keyword_index in range(1, 13):
        keyword_key = f"kw-{keyword_index:02d}"
        for competitor_index, (competitor_key, _, competitor_domain) in enumerate(competitors, 1):
            rank = 4 + competitor_index * 5 + (keyword_index * competitor_index) % 17
            tables["seo_serp_results"].append(
                _row(
                    f"serp-{keyword_key}-{competitor_key}",
                    tenant=tenant_ref,
                    site=site_ref,
                    keyword=_ref("seo_keyword_assets", keyword_key),
                    engine="baidu",
                    device="desktop",
                    region="全国",
                    rank=rank,
                    rank_label=str(rank),
                    title=f"虚拟竞品结果 {competitor_index}",
                    description="完全虚构的搜索结果，仅供演示竞争排名矩阵。",
                    result_url=f"https://{competitor_domain}/virtual/{keyword_index}",
                    domain=competitor_domain,
                    ownership_type="competitor",
                    match_method="domain",
                    confidence=100,
                    matched_asset=None,
                    is_confirmed=True,
                    provider="demo_fixture",
                    captured_at=_iso(anchor),
                )
            )

    task_specs = [
        ("task-rank-drop", "ranking_improvement", "排名下跌：检查六轴机器人价格页", "open", "seo_operator"),
        ("task-publish", "content_review", "发布已审核的焊接工作站文章", "in_progress", "content_operator"),
        ("task-page", "page_repair", "修复旧培训页断链", "open", "seo_operator"),
        ("task-image", "image_repair", "核实码垛页第二张图片替代文字", "open", "content_reviewer"),
        ("task-done", "image_repair", "码垛页主图修复复查", "done", "content_reviewer"),
        ("task-cancelled", "backlink_outreach", "联系已停用的虚拟合作站", "cancelled", "seo_operator"),
    ]
    for key, action_type, title, status, role in task_specs:
        done = status == "done"
        tables["seo_tasks"].append(
            _row(
                key,
                tenant=tenant_ref,
                site=site_ref,
                module="seo",
                action_type=action_type,
                title=title,
                params={"synthetic": True, "fixture_marker": FIXTURE_VERSION},
                status=status,
                created_by="cockpit-demo",
                assignee_role=role,
                completion_evidence=(
                    {
                        "synthetic": True,
                        "metric_key": "seo.images.verified_repair_count",
                        "before": 0,
                        "after": 1,
                        "source": _ref("seo_image_verifications", "verify-image-fixed"),
                    }
                    if done
                    else None
                ),
                baseline={"synthetic": True},
                created_at=_iso(anchor - timedelta(days=4)),
                updated_at=_iso(anchor - timedelta(days=1)),
            )
        )

    for job_type in ("ranking", "competitor", "backlink"):
        tables["seo_automation_runs"].append(
            _row(
                f"automation-{job_type}",
                tenant=tenant_ref,
                site=site_ref,
                job_type=job_type,
                trigger_type="manual",
                status="completed",
                planned_count=12,
                success_count=10,
                failed_count=1,
                skipped_count=1,
                error_summary="虚拟演示运行记录；未调用任何外部服务",
                started_at=_iso(anchor - timedelta(days=2, minutes=5)),
                completed_at=_iso(anchor - timedelta(days=2)),
            )
        )

    package = {
        "fixture": {
            "version": FIXTURE_VERSION,
            "tenant_key": DEMO_TENANT_KEY,
            "site_key": DEMO_SITE_KEY,
            "proposed_tenant_id": proposed_tenant_id,
            "anchor": _iso(anchor),
            "synthetic": True,
            "database_write_performed": False,
            "business_actions_performed": False,
        },
        "safety": {
            "forbidden_tenant_ids": sorted(FORBIDDEN_TENANT_IDS),
            "reserved_domain_only": True,
            "site_status": "paused",
            "scheduler_excluded": True,
            "connections_disabled": True,
            "credentials_present": False,
            "single_article_search_attribution": "unsupported",
        },
        "limitations": [
            "Search performance is synthetic and site-level only; it cannot be attributed to one article.",
            "Page indexable means crawl/index control eligibility, not verified search-engine inclusion.",
            "Publication success, page-check success, and search improvement are independent facts.",
            "The current latest-metric API does not expose the complete 90-day series.",
        ],
        "tables": tables,
    }
    package["counts"] = {name: len(rows) for name, rows in tables.items()}
    validate_seo_demo_fixture(package)
    return package


def validate_seo_demo_fixture(package: dict[str, Any]) -> None:
    """Fail closed when a package could start work or impersonate real data."""
    fixture = package.get("fixture") or {}
    tables = package.get("tables") or {}
    if fixture.get("synthetic") is not True or fixture.get("version") != FIXTURE_VERSION:
        raise ValueError("missing synthetic fixture marker")
    if fixture.get("proposed_tenant_id") in FORBIDDEN_TENANT_IDS:
        raise ValueError("tenant_id=4 is forbidden")
    counts = package.get("counts") or {}
    actual_counts = {name: len(rows) for name, rows in tables.items()}
    if counts and counts != actual_counts:
        raise ValueError("declared fixture counts do not match table rows")
    sites = tables.get("seo_sites") or []
    if len(sites) != 1 or sites[0].get("status") not in {"paused", "archived"}:
        raise ValueError("demo site must remain paused or archived")
    settings = sites[0].get("site_settings") or {}
    if settings.get("scheduler_excluded") is not True or settings.get("external_actions_disabled") is not True:
        raise ValueError("demo site safety markers are required")
    for connection in tables.get("seo_distribution_connections") or []:
        if connection.get("enabled") or connection.get("has_credentials") or connection.get("credentials_encrypted"):
            raise ValueError("demo connections must be disabled and credential-free")
    forbidden_run_statuses = {"queued", "running", "checking", "publishing", "uploading"}
    for table_name in ("seo_crawl_runs", "seo_automation_runs"):
        for row in tables.get(table_name) or []:
            if row.get("status") in forbidden_run_statuses:
                raise ValueError(f"{table_name} contains runnable status")
    for publication in tables.get("seo_content_publications") or []:
        if publication.get("status") in {"pending", "publishing", "uploading"}:
            raise ValueError("publication contains runnable status")
    metric_rows = tables.get("seo_metric_snapshots") or []
    days = {
        row["observed_at"][:10]
        for row in metric_rows
        if row.get("metric_type") == "gsc_clicks"
    }
    if len(days) != 90:
        raise ValueError("fixture must contain exactly 90 daily site-level search observations")
    for row in metric_rows:
        raw = row.get("raw_payload") or {}
        if row.get("source") != "demo_fixture" or raw.get("article_attribution") != "unsupported":
            raise ValueError("search metrics must be explicit synthetic site totals")
    urls: list[str] = []
    for rows in tables.values():
        for row in rows:
            for key, value in row.items():
                if (key.endswith("url") or key in {"domain", "canonical_domain", "source_domain"}) and isinstance(value, str):
                    urls.append(value if "://" in value else f"https://{value}")
    bad_hosts = sorted(
        {
            urlsplit(value).hostname
            for value in urls
            if urlsplit(value).hostname and not urlsplit(value).hostname.endswith(".example")
        }
    )
    if bad_hosts:
        raise ValueError(f"non-reserved demo hosts found: {bad_hosts}")
    keys = [row.get("_key") for rows in tables.values() for row in rows]
    duplicates = [key for key, count in Counter(keys).items() if key and count > 1]
    if duplicates:
        raise ValueError(f"fixture keys must be globally unique: {duplicates}")
    known = {
        (table_name, row.get("_key"))
        for table_name, rows in tables.items()
        for row in rows
    }

    def refs(value: Any):
        if isinstance(value, dict):
            if set(value) == {"table", "key"}:
                yield value["table"], value["key"]
            else:
                for child in value.values():
                    yield from refs(child)
        elif isinstance(value, list):
            for child in value:
                yield from refs(child)

    unresolved = sorted(
        {
            reference
            for rows in tables.values()
            for row in rows
            for reference in refs(row)
            if reference not in known
        }
    )
    if unresolved:
        raise ValueError(f"unresolved fixture references: {unresolved}")
