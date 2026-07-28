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

    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()
