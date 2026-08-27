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

CHANNEL_TYPE_LABELS = {
    "website": "官网",
    "docs": "文档",
    "wechat": "微信公众号",
    "zhihu": "知乎",
    "baijiahao": "百家号",
    "toutiao": "头条号",
    "industry_media": "行业媒体",
    "community_qa": "社区问答",
    "encyclopedia": "百科",
    "visual_content": "视频",
}

PUBLISH_MODE_OPTIONS = ("auto_publish", "draft_then_manual", "manual_only")

# New tenants: multi-media auto-push ready by default (only credentials missing).
_DEFAULT_CHANNELS = (
    ("官网内容中心", "website", "auto_publish"),
    ("帮助中心 / 产品文档", "docs", "auto_publish"),
    ("微信公众号", "wechat", "auto_publish"),
    ("知乎机构号", "zhihu", "auto_publish"),
    ("百家号", "baijiahao", "auto_publish"),
    ("头条号", "toutiao", "auto_publish"),
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
