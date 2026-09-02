import re
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


SEM_CUSTOMER_LIVE_WRITE_SCOPES = frozenset(
    {
        "account_budget",
        "adgroup_bid",
        "adgroup_landing_url",
        "adgroup_negative_words",
        "adgroup_pause",
        "campaign_budget",
        "campaign_negative_words",
        "campaign_pause",
        "campaign_region",
        "campaign_schedule",
        "keyword_bid",
        "keyword_create",
        "keyword_match_type",
        "keyword_pause",
    }
)


def parse_positive_id_csv(value: str, *, label: str) -> frozenset[int]:
    """Parse a comma-separated positive-ID allowlist and fail closed on typos."""
    ids: set[int] = set()
    for raw in str(value or "").split(","):
        item = raw.strip()
        if not item:
            continue
        if not item.isascii() or not item.isdecimal() or int(item) <= 0:
            raise ValueError(
                f"{label} must contain only comma-separated positive integers"
            )
        ids.add(int(item))
    return frozenset(ids)


def parse_write_scope_csv(value: str, *, label: str) -> frozenset[str]:
    """Parse explicit snake-case live-write scopes and reject ambiguous values."""
    scopes: set[str] = set()
    for raw in str(value or "").split(","):
        item = raw.strip()
        if not item:
            continue
        if re.fullmatch(r"[a-z][a-z0-9_]*", item) is None:
            raise ValueError(
                f"{label} must contain only comma-separated lowercase action scopes"
            )
        scopes.add(item)
    return frozenset(scopes)


def resolve_baidu_write_dry_run(
    settings: object,
    tenant_id: int | None,
    account_id: int | None,
    write_scope: str | None,
) -> bool:
    """兼容测试/过渡配置并默认失败关闭真实回写。"""
    resolver = getattr(settings, "baidu_write_is_dry_run", None)
    if callable(resolver):
        return bool(resolver(tenant_id, account_id, write_scope))
    # A partial/legacy settings object cannot prove an exact allowlist match.
    return True


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False, extra="ignore")

    app_env: str = "dev"
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    app_base_url: str = "https://gsnipers.snipers.com.cn"

    database_url: str = Field(..., description="SQLAlchemy async URL，需用 postgresql+asyncpg 方言")

    baidu_api_base_url: str = "https://api.baidu.com"
    baidu_app_id: str
    baidu_secret_key: str
    baidu_oauth_base_url: str = "https://u.baidu.com"
    baidu_oauth_platform_id: str = "4960345965958561794"
    # 从商业开发者中心「授权链接」中复制 scope 参数。权限变化后需同步更新。
    baidu_oauth_scope: str = ""
    # 默认按 APP_BASE_URL 拼接；仅在回调域名与主站不同时覆盖。
    baidu_oauth_callback_url: str = ""
    baidu_oauth_state_ttl_minutes: int = 15

    # 写回演练开关：True=dry-run，所有写百度的请求只算改动+记台账，绝不真发（开发/验证默认）。
    # 关闭=真写线上出价，必须用户明确批准后才在生产改为 False（红线 feedback-no-baidu-writeback）。
    baidu_write_dry_run: bool = True
    # 真写必须同时命中租户和本地百度账户双白名单。空值表示拒绝全部真实写请求。
    baidu_live_write_tenant_ids: str = ""
    baidu_live_write_account_ids: str = ""
    baidu_live_write_scopes: str = ""
    baidu_write_confirmation_ttl_minutes: int = Field(default=15, ge=1, le=120)
    # 仅用于先后发布兼容。真实写开启时 prod_guard 强制要求关闭。
    baidu_legacy_split_confirmation_enabled: bool = True

    def baidu_live_write_identity_allowed(
        self,
        tenant_id: int | None,
        account_id: int | None,
    ) -> bool:
        if tenant_id is None or account_id is None:
            return False
        tenant_ids = parse_positive_id_csv(
            self.baidu_live_write_tenant_ids,
            label="BAIDU_LIVE_WRITE_TENANT_IDS",
        )
        account_ids = parse_positive_id_csv(
            self.baidu_live_write_account_ids,
            label="BAIDU_LIVE_WRITE_ACCOUNT_IDS",
        )
        return int(tenant_id) in tenant_ids and int(account_id) in account_ids

    def baidu_live_write_allowed(
        self,
        tenant_id: int | None,
        account_id: int | None,
        write_scope: str | None,
    ) -> bool:
        if not self.baidu_live_write_identity_allowed(tenant_id, account_id):
            return False
        scopes = parse_write_scope_csv(
            self.baidu_live_write_scopes,
            label="BAIDU_LIVE_WRITE_SCOPES",
        )
        return bool(write_scope) and write_scope in scopes

    def baidu_write_is_dry_run(
        self,
        tenant_id: int | None,
        account_id: int | None,
        write_scope: str | None,
    ) -> bool:
        """Resolve the effective mode for one customer/account/action."""
        if self.baidu_write_dry_run or self.baidu_legacy_split_confirmation_enabled:
            return True
        try:
            return not self.baidu_live_write_allowed(
                tenant_id,
                account_id,
                write_scope,
            )
        except (TypeError, ValueError):
            # Invalid allowlists must never turn a request into a live write.
            return True

    # P0 自授权：苏尔寿单租户硬编码进 env。P1 多租户后改为从 baidu_accounts 表读。
    baidu_default_username: str
    baidu_default_ucid: int
    baidu_self_access_token: str
    baidu_self_token_expires_at: str

    crypto_master_key_b64: str = Field(..., description="32 字节 AES-256 主密钥的 base64 编码")

    admin_api_key: str = Field(
        ..., description="admin / dashboard 接口的 API Key，调用方经 X-API-Key 请求头携带"
    )
    # 是否允许 ?key= 传 API Key（URL 会进日志/Referer，生产必须 False）
    # 查询参数会进入浏览器历史、代理与访问日志；默认关闭，仅兼容环境显式开启。
    admin_api_key_query_enabled: bool = False
    # 若设置，API Key 访问绑定到该租户（ensure_tenant 生效）；None=可跨租户（仅运维）
    admin_api_key_tenant_id: int | None = None

    # 登录态 JWT 签名密钥；不配则退化复用 admin_api_key（本地冒烟方便），生产必须单独配
    jwt_secret: str = ""
    jwt_expire_hours: int = 12

    # 登录防护：失败次数在一个时间窗内累计，达到阈值后临时锁定账号。
    login_max_failed_attempts: int = Field(default=5, ge=3, le=20)
    login_failure_window_minutes: int = Field(default=15, ge=1, le=1440)
    login_lockout_minutes: int = Field(default=10, ge=1, le=1440)

    # 逗号分隔，生产环境不得包含通配符。浏览器前端均应走同源 HTTPS。
    cors_allowed_origins: str = "https://gsnipers.snipers.com.cn"

    def cors_origin_list(self) -> list[str]:
        return [
            origin.strip().rstrip("/")
            for origin in self.cors_allowed_origins.split(",")
            if origin.strip()
        ]

    # GEO：是否允许同一人提交审校又审批通过（默认禁止）
    geo_allow_self_review: bool = False

    # DeepSeek 官方（SEM 建议引擎等）。不配 key 则建议引擎只产规则版。
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-chat"

    # 站长之家 SEO 数据。仅在 GEO 诊断后端调用，Key 不得进入前端构建产物。
    # 不同商品可能下发不同 API Key；各项独立 Key 为空时回退到通用 Key。
    chinaz_api_enabled: bool = True
    chinaz_api_key: str = ""
    chinaz_baidu_index_api_key: str = ""
    chinaz_baidu_pc_keywords_api_key: str = ""
    chinaz_baidu_mobile_keywords_api_key: str = ""
    chinaz_baidu_pc_top50_api_key: str = ""
    chinaz_baidu_mobile_top50_api_key: str = ""
    chinaz_weight_all_api_key: str = ""
    chinaz_whois_api_key: str = ""
    chinaz_api_base_url: str = "https://openapi.chinaz.net/v1/1001"
    chinaz_api_timeout_seconds: float = 8.0
    # 每天 02:00 自动采集全部启用 SEO 关键词的百度 PC/移动前 50。
    seo_rank_scheduler_enabled: bool = True
    seo_rank_scheduler_batch_size: int = 20
    seo_rank_scheduler_use_ai: bool = True
    seo_rank_scheduler_max_keywords_per_tenant: int = 200
    seo_rank_scheduler_max_requests_per_run: int = 1000
    # 用户手动点击“更新排名”使用独立额度；调度器不走此限制。
    seo_manual_rank_cooldown_seconds: int = 3600
    seo_manual_rank_max_requests_per_day: int = 100

    # SEO multi-engine live SERP. Credentials are server-only and never stored per site.
    seo_dataforseo_login: str = ""
    seo_dataforseo_password: str = ""
    seo_dataforseo_base_url: str = "https://api.dataforseo.com/v3"
    seo_dataforseo_location_code: int = 2156
    seo_dataforseo_language_code: str = "zh_CN"
    seo_dataforseo_timeout_seconds: float = 30.0

    # Google Search Console service-account JSON, base64 encoded. Individual sites only
    # store their non-secret Search Console property URL in seo_sites.site_settings.
    seo_gsc_service_account_json_b64: str = ""
    seo_gsc_timeout_seconds: float = 30.0

    # Google PageSpeed Insights。仅由后端调用，Key 不得进入前端构建产物。
    pagespeed_api_key: str = ""
    pagespeed_api_base_url: str = (
        "https://pagespeedonline.googleapis.com/pagespeedonline/v5/runPagespeed"
    )
    pagespeed_api_timeout_seconds: float = 60.0

    # 本地 Lighthouse：大陆服务器无法访问 PageSpeed API 时使用。
    lighthouse_cli_path: str = "/opt/lighthouse-runner/node_modules/.bin/lighthouse"
    lighthouse_chrome_path: str = "/usr/bin/chromium-browser"
    lighthouse_timeout_seconds: float = 90.0

    # 阿里云百炼 DashScope（GEO 默认推荐；OpenAI 兼容模式）
    dashscope_api_key: str = ""
    dashscope_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    dashscope_model: str = "deepseek-v3"

    # GEO 母稿质量门禁（P2/P3）：默认关闭，仅 warn 不挡发布
    geo_score_gate: bool = False
    geo_score_threshold: int = 60
    geo_ai_review_gate: bool = False
    # 编造风险 lint：高危条数 >0 时拦截发布/Webhook（产品化增强）
    geo_lint_gate: bool = True

    # GEO 巡检配额（产品化必做：防一键烧穿 LLM）
    # 单租户自然日（Asia/Shanghai）最多启动次数（手动+定时合计）
    geo_patrol_max_runs_per_day: int = 24
    # 单次巡检最大探测格数 ≈ 机会词 × 引擎（超出截断并记 summary）
    geo_patrol_max_cells_per_run: int = 200

    # GEO 异步作业超时（秒）：pending/running 超时后标记 failed，并恢复任务状态
    geo_async_stale_pending_seconds: int = 120
    geo_async_stale_running_seconds: int = 45 * 60

    # 缺口 SLA：brand_missing 且无任务超过 N 天则告警
    geo_gap_sla_days: int = 7

    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()
