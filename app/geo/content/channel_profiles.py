"""中国主流图文分发渠道画像（Channel Profile）。

只服务「母稿 → 平台文稿」确定性改写；不含短视频/小红书，不含自动发布。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class ChannelProfile:
    key: str
    display_name: str
    tier: str  # owned / must / search / feed
    goal: str
    title_max: int
    mode: str  # full | short | wechat
    faq_limit: int
    keep_definition: bool
    keep_conclusion: bool
    keep_sources: bool
    export_format: str
    default_selected: bool
    notes: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


CHANNEL_PROFILES: dict[str, ChannelProfile] = {
    "website": ChannelProfile(
        key="website",
        display_name="官网 / 博客",
        tier="owned",
        goal="完整母稿上线，作为可核验权威信源",
        title_max=80,
        mode="full",
        faq_limit=8,
        keep_definition=True,
        keep_conclusion=True,
        keep_sources=True,
        export_format="html",
        default_selected=True,
        notes="导出 HTML 正稿（含表格）；优先发布后再铺其它渠道。",
    ),
    "wechat": ChannelProfile(
        key="wechat",
        display_name="微信公众号",
        tier="must",
        goal="品牌主阵地图文：直接答案 + 适度展开 + 弱外链",
        title_max=64,
        mode="wechat",
        faq_limit=3,
        keep_definition=True,
        keep_conclusion=True,
        keep_sources=True,
        export_format="html",
        default_selected=True,
        notes="导出 HTML 正稿可粘贴公众号；外链可能被折叠。",
    ),
    "zhihu": ChannelProfile(
        key="zhihu",
        display_name="知乎",
        tier="must",
        goal="回答型短文，利于被摘取结论与 FAQ",
        title_max=40,
        mode="short",
        faq_limit=3,
        keep_definition=True,
        keep_conclusion=True,
        keep_sources=True,
        export_format="html",
        default_selected=True,
        notes="导出 HTML 正稿；首段必须是直接答案；对比用表格。",
    ),
    "baijiahao": ChannelProfile(
        key="baijiahao",
        display_name="百家号",
        tier="search",
        goal="百度生态资讯体，保留答案与来源",
        title_max=36,
        mode="short",
        faq_limit=2,
        keep_definition=True,
        keep_conclusion=True,
        keep_sources=True,
        export_format="html",
        default_selected=False,
        notes="导出 HTML 正稿；标题偏资讯、忌夸张。",
    ),
    "toutiao": ChannelProfile(
        key="toutiao",
        display_name="头条号",
        tier="feed",
        goal="信息流可读短文，结论前置",
        title_max=30,
        mode="short",
        faq_limit=2,
        keep_definition=False,
        keep_conclusion=True,
        keep_sources=True,
        export_format="html",
        default_selected=False,
        notes="导出 HTML 正稿；控制标题党，对比用表格。",
    ),
}

SUPPORTED_CHANNELS = tuple(CHANNEL_PROFILES.keys())
DEFAULT_TARGET_CHANNELS = tuple(
    p.key for p in CHANNEL_PROFILES.values() if p.default_selected
)


def get_profile(channel: str) -> ChannelProfile | None:
    return CHANNEL_PROFILES.get(channel)


def list_profiles() -> list[dict[str, Any]]:
    order = ["website", "wechat", "zhihu", "baijiahao", "toutiao"]
    return [CHANNEL_PROFILES[k].to_dict() for k in order if k in CHANNEL_PROFILES]


def normalize_channels(channels: list[str] | None) -> list[str]:
    if not channels:
        return list(DEFAULT_TARGET_CHANNELS)
    out: list[str] = []
    for raw in channels:
        key = str(raw or "").strip().lower()
        if key in CHANNEL_PROFILES and key not in out:
            out.append(key)
    return out or list(DEFAULT_TARGET_CHANNELS)
