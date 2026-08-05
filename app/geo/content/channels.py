"""Publishing-channel registry defaults and input normalization."""

CHANNEL_TYPE_OPTIONS = (
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
)

PUBLISH_MODE_OPTIONS = ("auto_publish", "draft_then_manual", "manual_only")

_DEFAULT_CHANNELS = (
    ("官网内容中心", "website", "auto_publish"),
    ("帮助中心 / 产品文档", "docs", "auto_publish"),
    ("微信公众号", "wechat", "draft_then_manual"),
    ("知乎机构号", "zhihu", "draft_then_manual"),
    ("百家号", "baijiahao", "draft_then_manual"),
    ("头条号", "toutiao", "manual_only"),
    ("行业媒体 / 垂直社区", "industry_media", "manual_only"),
)


def normalize_channel_type(value: str | None) -> str:
    candidate = (value or "").strip().lower()
    return candidate if candidate in CHANNEL_TYPE_OPTIONS else "industry_media"


def normalize_publish_mode(value: str | None) -> str:
    candidate = (value or "").strip().lower()
    return candidate if candidate in PUBLISH_MODE_OPTIONS else "manual_only"


def default_channel_rows(tenant_id: int) -> list[dict[str, object]]:
    return [
        {
            "tenant_id": tenant_id,
            "name": name,
            "channel_type": channel_type,
            "publish_mode": publish_mode,
            "enabled": True,
            "sort_order": index,
        }
        for index, (name, channel_type, publish_mode) in enumerate(_DEFAULT_CHANNELS, start=10)
    ]
