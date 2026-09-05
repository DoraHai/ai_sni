"""GEO 内容域 Pydantic schemas。"""

from __future__ import annotations

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, Field


class PromptCreate(BaseModel):
    tenant_id: int
    question: str = Field(..., min_length=4, max_length=500)
    priority: int = 0
    tags: list[str] = Field(default_factory=list)
    demand_note: str | None = None
    source: Literal["manual", "import", "demo", "expand"] = "manual"
    language: str = "zh-CN"
    question_group: str | None = Field(None, max_length=32)
    market: Literal["cn", "global", "both"] = "cn"
    is_brand_probe: bool | None = None
    unit_id: int | None = None


class PromptUpdate(BaseModel):
    question: str | None = Field(None, min_length=4, max_length=500)
    priority: int | None = None
    tags: list[str] | None = None
    demand_note: str | None = None
    status: Literal["active", "archived"] | None = None
    question_group: str | None = Field(None, max_length=32)
    market: Literal["cn", "global", "both"] | None = None
    is_brand_probe: bool | None = None
    unit_id: int | None = None


class OptimizationBusinessCreate(BaseModel):
    tenant_id: int
    name: str = Field(..., min_length=1, max_length=120)
    description: str | None = None
    sort_order: int = 0
    profile: dict[str, Any] | None = None


class OptimizationBusinessUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=120)
    description: str | None = None
    status: Literal["active", "archived"] | None = None
    sort_order: int | None = None
    profile: dict[str, Any] | None = None


class OptimizationUnitCreate(BaseModel):
    tenant_id: int
    business_id: int
    name: str = Field(..., min_length=1, max_length=120)
    keyword: str | None = Field(None, max_length=200)
    description: str | None = None
    sort_order: int = 0


class OptimizationUnitUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=120)
    keyword: str | None = Field(None, max_length=200)
    description: str | None = None
    status: Literal["active", "archived"] | None = None
    sort_order: int | None = None
    business_id: int | None = None


class PromptImportItem(BaseModel):
    question: str = Field(..., min_length=4, max_length=500)
    priority: int = 0
    tags: list[str] = Field(default_factory=list)
    demand_note: str | None = None
    question_group: str | None = Field(None, max_length=32)
    market: Literal["cn", "global", "both"] = "cn"
    is_brand_probe: bool | None = None


class PromptImportRequest(BaseModel):
    tenant_id: int
    items: list[PromptImportItem] = Field(..., min_length=1)


class PromptExpandRoot(BaseModel):
    root: str = Field(..., min_length=2, max_length=80)
    kind: Literal["brand", "competitor", "category"] = "category"
    market: Literal["cn", "global", "both"] = "cn"


class PromptExpandRequest(BaseModel):
    tenant_id: int
    market: Literal["cn", "global", "both"] = "cn"
    roots: list[PromptExpandRoot] = Field(default_factory=list)
    competitors: list[str] = Field(default_factory=list)
    products: list[str] = Field(default_factory=list)
    seed_from_tenant: bool = True
    max_terms: int = Field(80, ge=1, le=200)
    persist: bool = True


class PromptPromoteItem(BaseModel):
    question: str = Field(..., min_length=4, max_length=500)
    question_group: str | None = Field(None, max_length=32)
    market: Literal["cn", "global", "both"] = "cn"
    priority: int = 10
    tags: list[str] = Field(default_factory=lambda: ["from_expand"])
    demand_note: str | None = None
    is_brand_probe: bool | None = None
    unit_id: int | None = None


class PromptPromoteRequest(BaseModel):
    tenant_id: int
    items: list[PromptPromoteItem] = Field(..., min_length=1, max_length=50)


class FactCreate(BaseModel):
    tenant_id: int
    title: str = Field(..., min_length=1, max_length=200)
    statement: str = Field(..., min_length=4)
    fact_type: Literal["product", "case", "metric", "policy", "other"] = "product"
    source_name: str = Field(..., min_length=1, max_length=200)
    source_url: str | None = None
    observed_at: date | None = None
    expires_at: date | None = None
    trust_level: Literal["verified", "needs_review", "draft"] = "needs_review"
    author_name: str | None = Field(None, max_length=100)
    business_id: int | None = None
    meta: dict[str, Any] | None = None


class FactUpdate(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=200)
    statement: str | None = Field(None, min_length=4)
    fact_type: Literal["product", "case", "metric", "policy", "other"] | None = None
    source_name: str | None = Field(None, min_length=1, max_length=200)
    source_url: str | None = None
    observed_at: date | None = None
    expires_at: date | None = None
    trust_level: Literal["verified", "needs_review", "draft"] | None = None
    author_name: str | None = Field(None, max_length=100)
    status: Literal["active", "archived"] | None = None
    business_id: int | None = None
    meta: dict[str, Any] | None = None


class FactVerifyRequest(BaseModel):
    excerpt: str = Field(..., min_length=8, max_length=400)
    excerpt_locator: str = Field(..., min_length=2, max_length=200)
    source_url: str | None = Field(None, max_length=800)
    note: str | None = Field(None, max_length=500)


class SourceOpportunityTaskCreate(BaseModel):
    evidence_version: str = Field(..., pattern=r"^[a-f0-9]{64}$")
    tenant_id: int
    prompt_id: int
    snapshot_ids: list[int] = Field(..., min_length=1, max_length=1000)


class TaskCreate(BaseModel):
    tenant_id: int
    prompt_id: int
    title: str | None = Field(None, max_length=300)
    target_channels: list[str] = Field(
        default_factory=lambda: ["website", "wechat", "zhihu"]
    )
    fact_ids: list[int] = Field(default_factory=list)
    brief: dict[str, Any] | None = None


class ArticleImportPreviewUrlRequest(BaseModel):
    tenant_id: int
    url: str = Field(..., min_length=8, max_length=2000)


class ArticleImportCreateTaskRequest(BaseModel):
    tenant_id: int
    prompt_id: int
    title: str = Field(..., min_length=1, max_length=300)
    body_markdown: str = Field(..., min_length=1, max_length=500_000)
    source_type: Literal["paste", "file", "url"]
    source_url: str | None = Field(None, max_length=2000)
    target_channels: list[str] = Field(
        default_factory=lambda: ["website", "wechat", "zhihu"],
        min_length=1,
        max_length=20,
    )


class ContentBrief(BaseModel):
    industry: str | None = Field(None, max_length=100)
    audience: str | None = Field(None, max_length=120)
    intent: str | None = Field(None, max_length=32)
    content_type: str | None = Field(None, max_length=32)
    cta: str | None = Field(None, max_length=160)
    banned_claims: list[str] = Field(default_factory=list)
    notes: str | None = Field(None, max_length=500)
    # v2 strategy (optional)
    ai_question: str | None = Field(None, max_length=300)
    not_recommended_reasons: list[str] = Field(default_factory=list)
    info_gaps: list[str] = Field(default_factory=list)
    recommend_when: str | None = Field(None, max_length=300)
    competitors: list[str] = Field(default_factory=list)
    must_cover: list[str] = Field(default_factory=list)
    source_bar: str | None = Field(None, max_length=40)
    strategy_notes: str | None = Field(None, max_length=500)
    schema_version: int | None = None


class TaskFactsUpdate(BaseModel):
    fact_ids: list[int] = Field(..., min_length=0)


class SuggestBriefRequest(BaseModel):
    overwrite: bool = False
    use_llm: bool = True


class RetrieveFactsRequest(BaseModel):
    limit: int = Field(10, ge=1, le=50)
    verified_only: bool = False
    auto_bind: bool = False


class RetrieveFactsApplyRequest(BaseModel):
    fact_ids: list[int] = Field(..., min_length=1, max_length=50)


class AiReviewRequest(BaseModel):
    """P3 AI Reviewer: default does not persist; set persist=true to store on task."""

    persist: bool = True


class ArticleUpdate(BaseModel):
    title: str = Field(..., min_length=1)
    body_markdown: str = Field(..., min_length=1)
    outline: dict[str, Any] | None = None


class VariantsCreate(BaseModel):
    channels: list[str] = Field(
        default_factory=lambda: ["website", "wechat", "zhihu"]
    )
    # True: LLM 按渠道润色成接近可发的渠道稿；失败回退确定性裁剪
    use_llm: bool = True


class VariantUpdate(BaseModel):
    title: str | None = Field(None, min_length=1)
    body_markdown: str | None = Field(None, min_length=1)


class PublicationCreate(BaseModel):
    tenant_id: int
    channel: str
    published_url: str = Field(..., min_length=8)
    note: str | None = None


class WebhookPushRequest(BaseModel):
    tenant_id: int
    channel: str = Field(..., min_length=1, max_length=32)
    account_id: int
    mode: Literal["draft", "publish"] = "publish"
    create_publication: bool = True
    published_url: str | None = Field(None, max_length=2000)
    note: str | None = None


class PushBatchTarget(BaseModel):
    channel: str = Field(..., min_length=1, max_length=32)
    account_id: int


class PushBatchRequest(BaseModel):
    """Push one task to multiple auto-publish media channels."""

    tenant_id: int
    mode: Literal["draft", "publish"] = "publish"
    create_publication: bool = True
    # null/empty → all ready targets for this task
    targets: list[PushBatchTarget] | None = None
    note: str | None = None


class ReviewSubmit(BaseModel):
    note: str | None = Field(None, max_length=2000)


class ReviewDecision(BaseModel):
    decision: Literal["approved", "rejected"]
    note: str | None = Field(None, max_length=2000)


class GapCreateTasksRequest(BaseModel):
    tenant_id: int
    prompt_ids: list[int] = Field(..., min_length=1, max_length=50)


class OptimizationPeriodCreate(BaseModel):
    tenant_id: int
    name: str = Field(..., min_length=1, max_length=160)
    starts_at: str
    ends_at: str
    business_id: int | None = None
    goal_note: str | None = Field(None, max_length=2000)
    capture_baseline: bool = True


class GeoOnboardingPreviewRequest(BaseModel):
    tenant_id: int
    website_url: str = Field(..., min_length=8, max_length=2000)
    expand: bool = True
    max_prompt_candidates: int = Field(24, ge=4, le=80)


class GeoOnboardingBusinessPick(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    description: str | None = None


class GeoOnboardingPromptPick(BaseModel):
    question: str = Field(..., min_length=4, max_length=500)
    question_group: str | None = None
    priority: int = 10
    tags: list[str] = Field(default_factory=lambda: ["from_onboarding", "brand_missing"])
    business_name: str | None = None
    is_brand_probe: bool | None = None


class GeoOnboardingFactPick(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    statement: str = Field(..., min_length=4)
    fact_type: Literal["product", "case", "metric", "policy", "other"] = "product"
    source_name: str = Field(..., min_length=1, max_length=200)
    source_url: str | None = None
    trust_level: Literal["verified", "needs_review", "draft"] = "needs_review"
    business_name: str | None = None


class GeoOnboardingApplyRequest(BaseModel):
    tenant_id: int
    website_url: str | None = None
    brand_terms: list[str] = Field(default_factory=list)
    businesses: list[GeoOnboardingBusinessPick] = Field(default_factory=list)
    prompts: list[GeoOnboardingPromptPick] = Field(default_factory=list)
    facts: list[GeoOnboardingFactPick] = Field(default_factory=list)
    create_website_channel: bool = True
    dry_run: bool = False


class MonitoringStanceUpdate(BaseModel):
    tenant_id: int
    monitoring_stance: Literal["simulation", "hybrid", "real_only"] = "hybrid"


class TaskUpdate(BaseModel):
    title: str | None = Field(None, max_length=300)
    owner_user_id: int | None = None
    target_channels: list[str] | None = None
    brief: ContentBrief | dict[str, Any] | None = None
    # draft|facts_bound|editing|needs_fix|ready|published|archived
    status: str | None = Field(None, max_length=32)


class TaskFromDiagnosis(BaseModel):
    tenant_id: int
    audit_id: int
    advice_code: str | None = None


class ApplyPatchRequest(BaseModel):
    code: str = Field(..., min_length=1, max_length=64)
    author_name: str | None = Field(None, max_length=100)


SnapshotEngine = Literal[
    "chatgpt",
    "deepseek",
    "doubao",
    "qwen",
    "hunyuan",
    "wenxin",
    "kimi",
    "perplexity",
    "other",
]
BrandPosition = Literal["first", "alternative", "mentioned", "absent", "unknown"]
SnapshotSentiment = Literal["positive", "neutral", "negative", "unknown"]
CitationFormat = Literal["linked", "plaintext", "mixed", "none", "unknown"]
CitationAccuracy = Literal["accurate", "partial", "inaccurate", "unknown"]


class AnswerSnapshotCreate(BaseModel):
    tenant_id: int
    prompt_id: int
    engine: SnapshotEngine = "other"
    raw_text: str = Field(..., min_length=4)
    captured_at: str | None = None  # ISO datetime; default now
    mentions_brand: bool = False
    cited_urls: list[str] = Field(default_factory=list)
    competitors: list[str] = Field(default_factory=list)
    brand_position: BrandPosition = "unknown"
    sentiment: SnapshotSentiment = "unknown"
    citation_format: CitationFormat = "unknown"
    citation_accuracy: CitationAccuracy = "unknown"
    note: str | None = None
    sample_mode: Literal["manual", "openai_compat", "mock_persona"] = "manual"


class AnswerSnapshotUpdate(BaseModel):
    engine: SnapshotEngine | None = None
    raw_text: str | None = Field(None, min_length=4)
    captured_at: str | None = None
    mentions_brand: bool | None = None
    cited_urls: list[str] | None = None
    competitors: list[str] | None = None
    brand_position: BrandPosition | None = None
    sentiment: SnapshotSentiment | None = None
    citation_format: CitationFormat | None = None
    citation_accuracy: CitationAccuracy | None = None
    note: str | None = None


class AnswerSnapshotProbeRequest(BaseModel):
    tenant_id: int
    prompt_id: int
    engine: SnapshotEngine = "deepseek"


class AnswerSnapshotProbeBatchRequest(BaseModel):
    """Probe multiple tracking engines; drafts only (no DB write)."""

    tenant_id: int
    prompt_id: int
    engines: list[SnapshotEngine] | None = None


class AnswerSnapshotExtractUrlsRequest(BaseModel):
    tenant_id: int
    raw_text: str = Field(..., min_length=1)


class AnswerSnapshotSuggestFieldsRequest(BaseModel):
    tenant_id: int
    raw_text: str = Field(..., min_length=4)
    prompt_id: int | None = None
    use_llm: bool = True


class AnswerSnapshotCitationCheckRequest(BaseModel):
    tenant_id: int
    cited_urls: list[str] = Field(default_factory=list)
    snapshot_id: int | None = None
    apply: bool = False


AiProvider = Literal["dashscope", "deepseek"]


class AiSettingsUpdate(BaseModel):
    tenant_id: int
    provider: AiProvider = "dashscope"
    base_url: str | None = Field(None, max_length=300)
    model: str | None = Field(None, max_length=80)
    api_key: str | None = Field(None, min_length=8, max_length=200)
    clear_api_key: bool = False
    enabled: bool = True
    note: str | None = None
    apply_preset: bool = False


class ChannelPolishPromptChannelUpdate(BaseModel):
    channel_key: str = Field(..., min_length=1, max_length=32)
    voice_prompt: str | None = Field(None, max_length=20000)
    min_body_chars: int | None = Field(None, ge=100, le=20000)
    reset: bool = False


class ChannelPolishPromptsUpdate(BaseModel):
    tenant_id: int
    system_prompt: str | None = Field(None, max_length=50000)
    reset_system: bool = False
    channels: list[ChannelPolishPromptChannelUpdate] = Field(default_factory=list)
    add_channel_key: str | None = Field(None, max_length=32)
    remove_channel_key: str | None = Field(None, max_length=32)


class CompetitorTraceReportRequest(BaseModel):
    tenant_id: int
    competitor: str = Field(..., min_length=1, max_length=120)
    source_urls: list[str] = Field(default_factory=list)
    platform_keys: list[str] = Field(default_factory=list)
    confirmed_external_urls: list[str] = Field(default_factory=list)
    note: str | None = Field(None, max_length=4000)
    insight: str | None = Field(None, max_length=8000)
    action: str | None = Field(None, max_length=8000)


class CompetitorRecTaskItem(BaseModel):
    prompt_id: int
    title: str | None = Field(None, max_length=300)
    channel_key: str | None = None
    reason: str | None = Field(None, max_length=800)
    sample_question: str | None = None


class CompetitorCreateTasksRequest(BaseModel):
    tenant_id: int
    competitor: str = Field(..., min_length=1, max_length=120)
    items: list[CompetitorRecTaskItem] = Field(default_factory=list, max_length=8)


class CompetitorReportUpsert(BaseModel):
    tenant_id: int
    competitor: str = Field(..., min_length=1, max_length=120)
    title: str | None = Field(None, max_length=240)
    business_id: int | None = None
    period_id: int | None = None
    insight: str | None = Field(None, max_length=8000)
    action: str | None = Field(None, max_length=8000)
    note: str | None = Field(None, max_length=4000)
    markdown: str | None = None
    source_urls: list[str] = Field(default_factory=list)
    platform_keys: list[str] = Field(default_factory=list)
    evidence: dict[str, Any] | None = None
    status: Literal["draft", "confirmed", "archived"] | None = None


class CompetitorReportPatch(BaseModel):
    title: str | None = Field(None, max_length=240)
    business_id: int | None = None
    period_id: int | None = None
    insight: str | None = Field(None, max_length=8000)
    action: str | None = Field(None, max_length=8000)
    note: str | None = Field(None, max_length=4000)
    markdown: str | None = None
    source_urls: list[str] | None = None
    platform_keys: list[str] | None = None
    evidence: dict[str, Any] | None = None
    status: Literal["draft", "confirmed", "archived"] | None = None


SampleMode = Literal["mock_persona", "openai_compat"]


class TrackingEngineItem(BaseModel):
    engine_key: SnapshotEngine
    display_name: str = Field(..., min_length=1, max_length=80)
    enabled: bool = True
    note: str | None = None
    sort_order: int = 0
    # P2: real multi-engine sampling (additive; default mock_persona)
    sample_mode: SampleMode = "mock_persona"
    api_base_url: str | None = Field(None, max_length=300)
    model: str | None = Field(None, max_length=80)
    api_key: str | None = Field(None, min_length=8, max_length=400)
    clear_api_key: bool = False


class TrackingEnginesPut(BaseModel):
    tenant_id: int
    items: list[TrackingEngineItem] = Field(..., min_length=1)


class VisibilityPatrolCreate(BaseModel):
    tenant_id: int
    auto_persist: bool = True
    prefer_real: bool = True
    prompt_limit: int = Field(20, ge=1, le=50)
    engine_keys: list[str] | None = None
    # run immediately in background (default True)
    run_async: bool = True


class VisibilityPatrolSettingsUpdate(BaseModel):
    tenant_id: int
    enabled: bool = False
    # legacy single-hour (optional); if window_* provided they take precedence
    daily_hour: int | None = Field(None, ge=0, le=23)
    # Asia/Shanghai local hour window (inclusive). Overnight ok when start > end.
    window_start_hour: int = Field(6, ge=0, le=23)
    window_end_hour: int = Field(22, ge=0, le=23)
    # hours between scheduled runs; allowed: 1,2,3,4,6,8,12,24
    interval_hours: int = Field(24, ge=1, le=24)
    auto_persist: bool = True
    prefer_real: bool = True
    prompt_limit: int = Field(20, ge=1, le=50)
    engine_keys: list[str] | None = None


MediaChannelType = Literal[
    "website",
    "zhihu",
    "wechat",
    "news",
    "wiki",
    "baijiahao",
    "toutiao",
    "encyclopedia",
    "community_qa",
    "industry_media",
    "visual_content",
    "other",
]
MediaPlacementStatus = Literal["planned", "in_progress", "published", "archived"]


class MediaPlacementCreate(BaseModel):
    tenant_id: int
    name: str = Field(..., min_length=1, max_length=200)
    channel_type: MediaChannelType = "other"
    channel_key: str | None = Field(None, max_length=32)
    target_url: str | None = None
    authority_note: str | None = None
    status: MediaPlacementStatus = "planned"
    published_url: str | None = None
    priority: int = 0
    priority_band: str | None = Field(None, max_length=8)
    fits_groups: list[str] | None = None
    citation_national: int | None = None
    related_prompt_id: int | None = None


class MediaPlacementUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=200)
    channel_type: MediaChannelType | None = None
    channel_key: str | None = Field(None, max_length=32)
    target_url: str | None = None
    authority_note: str | None = None
    status: MediaPlacementStatus | None = None
    published_url: str | None = None
    priority: int | None = None
    priority_band: str | None = Field(None, max_length=8)
    fits_groups: list[str] | None = None
    citation_national: int | None = None
    related_prompt_id: int | None = None


PublishingChannelType = Literal[
    "website",
    "docs",
    "wechat",
    "zhihu",
    "baijiahao",
    "toutiao",
    "industry_media",
    "community_qa",
    "encyclopedia",
    "visual_content",
]
PublishingMode = Literal["auto_publish", "draft_then_manual", "manual_only"]
ChannelAuthType = Literal["manual", "api_key", "oauth2", "webhook", "social_api"]


class PublishingChannelCreate(BaseModel):
    tenant_id: int
    name: str = Field(..., min_length=1, max_length=200)
    channel_type: PublishingChannelType
    publish_mode: PublishingMode = "manual_only"
    base_url: str | None = Field(None, max_length=2000)
    content_rules: dict[str, Any] | None = None
    enabled: bool = True
    sort_order: int = 0


class PublishingChannelUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=200)
    channel_type: PublishingChannelType | None = None
    publish_mode: PublishingMode | None = None
    base_url: str | None = Field(None, max_length=2000)
    content_rules: dict[str, Any] | None = None
    enabled: bool | None = None
    sort_order: int | None = None


class ChannelAccountCreate(BaseModel):
    tenant_id: int
    channel_id: int
    display_name: str = Field(..., min_length=1, max_length=160)
    auth_type: ChannelAuthType = "manual"
    credentials: dict[str, Any] | None = None


class ChannelAccountUpdate(BaseModel):
    display_name: str | None = Field(None, min_length=1, max_length=160)
    auth_type: ChannelAuthType | None = None
    credentials: dict[str, Any] | None = None
    clear_credentials: bool = False
    status: Literal["unconfigured", "active", "expired", "disabled"] | None = None
