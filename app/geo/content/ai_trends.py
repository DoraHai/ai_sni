"""Curated AI industry trends + GEO strategy impact suggestions for a tenant."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import GeoAnswerSnapshot, GeoDailyMetric, GeoTrackingEngine

# Hand-maintained catalog (region: cn | global | both). Update as models ship.
AI_TREND_CATALOG: list[dict[str, Any]] = [
    {
        "id": "ds-v3-dashscope",
        "region": "cn",
        "vendor": "DeepSeek / 阿里云百炼",
        "title": "DeepSeek-V3 经百炼 OpenAI 兼容通道广泛可用",
        "summary": "国内 ECS 可直连兼容接口；内容生成与巡检模拟可统一用 deepseek-v3 类模型。",
        "impact_tags": ["llm_config", "content_gen", "patrol"],
        "published_on": "2025-12-01",
        "source": "阿里云百炼模型广场",
    },
    {
        "id": "doubao-seed",
        "region": "cn",
        "vendor": "字节跳动 · 豆包",
        "title": "豆包持续强化中文口语与多模态入口",
        "summary": "C 端流量大，品牌口语化问答与短视频联动信源更易被引用。",
        "impact_tags": ["engine_doubao", "placements_shortform", "tone"],
        "published_on": "2026-03-01",
        "source": "豆包产品动态（公开）",
    },
    {
        "id": "kimi-longctx",
        "region": "cn",
        "vendor": "月之暗面 · Kimi",
        "title": "Kimi 长上下文成为选型对比长文场景的重要入口",
        "summary": "长文档/白皮书类信源更可能进入回答；官网深度页与 PDF 可读性权重上升。",
        "impact_tags": ["engine_kimi", "longform", "website"],
        "published_on": "2026-01-15",
        "source": "Kimi 公开能力说明",
    },
    {
        "id": "gptbot-robots",
        "region": "global",
        "vendor": "OpenAI",
        "title": "GPTBot / ChatGPT-User 抓取策略需在 robots 显式声明",
        "summary": "若整站 Disallow GPTBot，官网内容进入 ChatGPT 引用池的概率显著下降。",
        "impact_tags": ["crawler_audit", "website"],
        "published_on": "2025-06-01",
        "source": "OpenAI crawler docs",
    },
    {
        "id": "claudebot",
        "region": "global",
        "vendor": "Anthropic",
        "title": "ClaudeBot 与公开网页抓取合规要求",
        "summary": "与 GPTBot 类似，需检查 robots；结构化 FAQ / Organization Schema 仍有助于抽取。",
        "impact_tags": ["crawler_audit", "schema"],
        "published_on": "2025-08-01",
        "source": "Anthropic crawler docs",
    },
    {
        "id": "perplexity-cite",
        "region": "global",
        "vendor": "Perplexity",
        "title": "Perplexity 回答强依赖可验证外链与权威域名",
        "summary": "第三方权威阵地（百科、行业媒体、知乎机构号）对引用率影响更大。",
        "impact_tags": ["engine_perplexity", "placements", "citations"],
        "published_on": "2025-10-01",
        "source": "Perplexity 产品观察",
    },
    {
        "id": "google-extended",
        "region": "global",
        "vendor": "Google",
        "title": "Google-Extended 控制是否用于生成式训练/摘要",
        "summary": "robots 中 Google-Extended 与经典 Googlebot 策略宜分开审视。",
        "impact_tags": ["crawler_audit"],
        "published_on": "2025-05-01",
        "source": "Google Search Central",
    },
    {
        "id": "cn-blueprint",
        "region": "cn",
        "vendor": "国内 GEO 实践",
        "title": "国内引擎引用更依赖知乎 / 百科 / 垂直媒体蓝图",
        "summary": "相对纯英文维基路径，中文信源布局仍是豆包/DeepSeek/Kimi 的主战场。",
        "impact_tags": ["placements", "cn_blueprint"],
        "published_on": "2026-02-01",
        "source": "Growth Sniper GEO 蓝图",
    },
]


def list_trend_catalog(*, region: str | None = None, limit: int = 40) -> list[dict[str, Any]]:
    items = list(AI_TREND_CATALOG)
    if region in ("cn", "global"):
        items = [t for t in items if t.get("region") in (region, "both")]
    items.sort(key=lambda t: t.get("published_on") or "", reverse=True)
    return items[: max(1, min(limit, 80))]


async def build_strategy_impacts(
    session: AsyncSession,
    *,
    tenant_id: int,
    trends: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Map catalog trends + live tenant signals into actionable GEO suggestions."""
    trends = trends if trends is not None else list_trend_catalog(limit=20)
    engines = list(
        await session.scalars(
            select(GeoTrackingEngine).where(GeoTrackingEngine.tenant_id == tenant_id)
        )
    )
    enabled = {str(e.engine_key) for e in engines if e.enabled}
    from app.geo.content.engine_providers import resolve_platform_engine_credentials

    real_ready = {
        str(e.engine_key)
        for e in engines
        if e.enabled
        and bool(resolve_platform_engine_credentials(e.engine_key))
    }

    today = date.today()
    metrics = list(
        await session.scalars(
            select(GeoDailyMetric)
            .where(
                GeoDailyMetric.tenant_id == tenant_id,
                GeoDailyMetric.scope_key == "t",
                GeoDailyMetric.metric_date >= today - timedelta(days=7),
            )
            .order_by(GeoDailyMetric.metric_date.desc())
        )
    )
    latest = metrics[0] if metrics else None
    snap_n = int(
        await session.scalar(
            select(GeoAnswerSnapshot.id)
            .where(GeoAnswerSnapshot.tenant_id == tenant_id)
            .limit(1)
        )
        or 0
    )
    has_snaps = bool(snap_n)

    suggestions: list[dict[str, Any]] = []

    def add(
        *,
        trend_id: str | None,
        level: str,
        title: str,
        detail: str,
        href: str,
        tags: list[str],
    ) -> None:
        suggestions.append(
            {
                "trend_id": trend_id,
                "level": level,
                "title": title,
                "detail": detail,
                "href": href,
                "tags": tags,
            }
        )

    if "kimi" not in enabled:
        add(
            trend_id="kimi-longctx",
            level="info",
            title="建议启用 Kimi 监测引擎",
            detail="默认引擎列表已含 Kimi；开启后可在巡检中覆盖长上下文场景。",
            href="/geo/engines",
            tags=["engine_kimi"],
        )
    elif "kimi" not in real_ready:
        add(
            trend_id="kimi-longctx",
            level="info",
            title="Kimi 仍为人设模拟",
            detail="平台尚未配置 Kimi 真采样，请联系管理员处理服务密钥或余额。",
            href="/geo/engines",
            tags=["engine_kimi", "patrol"],
        )

    if not real_ready:
        add(
            trend_id="ds-v3-dashscope",
            level="warning",
            title="真采样引擎未就绪",
            detail="巡检将回退人设模拟。请联系管理员配置平台托管的引擎凭证。",
            href="/geo/engines",
            tags=["patrol", "llm_config"],
        )

    if latest is not None:
        cite = int(latest.citation_count or 0)
        mention = latest.brand_mention_rate
        if cite < 3:
            add(
                trend_id="perplexity-cite",
                level="warning",
                title="近七日自有引用偏少",
                detail=f"最近租户日切片引用次数约 {cite}，优先补权威第三方阵地与可引用结论段。",
                href="/geo/placements",
                tags=["citations", "placements"],
            )
        if mention is not None and mention < 0.25:
            add(
                trend_id="cn-blueprint",
                level="warning",
                title="品牌提及率偏低",
                detail=f"最近提及率约 {mention * 100:.0f}%，建议加强意图词覆盖与母稿结论先行结构。",
                href="/geo/prompts",
                tags=["content_gen", "patrol"],
            )

    add(
        trend_id="gptbot-robots",
        level="info",
        title="复查 AI 爬虫 robots 声明",
        detail="对 GPTBot / ClaudeBot / Google-Extended 做一次网站体检，避免整站拦截。",
        href="/diagnostic-center/",
        tags=["crawler_audit", "website"],
    )

    if not has_snaps:
        add(
            trend_id=None,
            level="info",
            title="尚无可见度快照",
            detail="先跑一轮全自动巡检或手工登记 AI 可见度，策略影响才能贴合你的数据。",
            href="/geo/visibility/patrol",
            tags=["patrol"],
        )

    # Deduplicate by title
    seen: set[str] = set()
    uniq = []
    for s in suggestions:
        if s["title"] in seen:
            continue
        seen.add(s["title"])
        uniq.append(s)
    level_rank = {"error": 0, "warning": 1, "info": 2}
    uniq.sort(key=lambda x: level_rank.get(x["level"], 9))
    return uniq


async def build_ai_trends_payload(
    session: AsyncSession,
    *,
    tenant_id: int,
    region: str | None = None,
) -> dict[str, Any]:
    trends = list_trend_catalog(region=region, limit=30)
    impacts = await build_strategy_impacts(session, tenant_id=tenant_id, trends=trends)
    return {
        "tenant_id": tenant_id,
        "generated_at": datetime.utcnow().isoformat(timespec="seconds"),
        "region": region or "all",
        "trends": trends,
        "impacts": impacts,
        "summary": {
            "trend_count": len(trends),
            "impact_count": len(impacts),
            "warning": sum(1 for i in impacts if i["level"] == "warning"),
        },
    }
