from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False, extra="ignore")

    app_env: str = "dev"
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    app_base_url: str = "https://sem.snipers.com.cn"

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

    # P0 自授权：苏尔寿单租户硬编码进 env。P1 多租户后改为从 baidu_accounts 表读。
    baidu_default_username: str
    baidu_default_ucid: int
    baidu_self_access_token: str
    baidu_self_token_expires_at: str

    crypto_master_key_b64: str = Field(..., description="32 字节 AES-256 主密钥的 base64 编码")

    admin_api_key: str = Field(
        ..., description="admin / dashboard 接口的 API Key，调用方经 X-API-Key 请求头携带"
    )

    # 登录态 JWT 签名密钥；不配则退化复用 admin_api_key（本地冒烟方便），生产必须单独配
    jwt_secret: str = ""
    jwt_expire_hours: int = 12

    # DeepSeek（AI 调价建议判断层）。不配 key 则建议引擎只产规则版、不调用 AI。
    # 阿里云大陆可直连 api.deepseek.com；模型 deepseek-chat 兼容 OpenAI 接口。
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-chat"

    # 站长之家 SEO 数据。仅在 GEO 诊断后端调用，Key 不得进入前端构建产物。
    # 不同商品可能下发不同 API Key；各项独立 Key 为空时回退到通用 Key。
    chinaz_api_key: str = ""
    chinaz_baidu_index_api_key: str = ""
    chinaz_baidu_pc_keywords_api_key: str = ""
    chinaz_baidu_mobile_keywords_api_key: str = ""
    chinaz_weight_all_api_key: str = ""
    chinaz_whois_api_key: str = ""
    chinaz_api_base_url: str = "https://openapi.chinaz.net/v1/1001"
    chinaz_api_timeout_seconds: float = 8.0

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

    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()
