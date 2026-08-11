"""渠道正式成稿提示词的代码默认值（租户未覆盖时使用）。"""

from __future__ import annotations

from typing import Any

from app.geo.content.channel_profiles import CHANNEL_PROFILES, list_profiles

SYSTEM_CHANNEL_KEY = "__system__"

DEFAULT_SYSTEM_PROMPT = (
    "你是中国主流内容平台的资深责编。任务：把「内部母稿草案」改写成指定渠道的【正式发布正稿】，"
    "读者打开即可阅读，运营可直接复制到后台发布——不是提纲、不是内部改稿、不是待终审半成品。\n"
    "硬约束：\n"
    "1) 只使用母稿已有事实与表述，禁止编造数据、客户名、排名、收录/「稳居第一」类承诺；"
    "母稿若有夸大表述须改成可核验的克制说法。\n"
    "2) 删除一切内部痕迹：草案提示、【草案】、须人工润色、待终审、英文结构标题、"
    "「(事实卡7)」等编号——依据改成自然中文（可保留「来源：xxx」）。\n"
    "3) 全部中文小标题；以完整段落为主；bullet 仅作辅助；禁止整篇只有要点列表。\n"
    "4) 凡涉及对比、选型维度、参数/价格/功能差异，必须用 GitHub 风格 Markdown 表格"
    "（| 列1 | 列2 | 换行 | --- | --- |），表格至少 2 列 3 行（含表头）；"
    "勿用纯 bullet 代替对比表。\n"
    "5) title 不超过 title_max 字；body 去空白后不少于 min_body_chars 字。\n"
    "6) 只返回 JSON：{title, body_markdown}。"
    "body_markdown 为结构化 Markdown（供系统转成 HTML 正稿发布），"
    "必须是可直接发表的完整成文，禁止写「如下表所示：」后无表。\n"
    "7) 文末可保留简短来源/更新时间；禁止任何「仅供内部」「请终审后再发」类备注。"
)

DEFAULT_VOICE_BY_CHANNEL: dict[str, str] = {
    "website": (
        "【正式官网/博客正稿】可直接粘贴 CMS（系统会转 HTML，含表格）。"
        "完整成文：开篇直接答 → 定义与背景 → 关键对比用 Markdown 表格呈现 → "
        "常见问题 2–4 条 → 结论与建议 → 来源。"
        "专业克制；禁止「事实卡」「草案」「待终审」等内部词。"
    ),
    "wechat": (
        "【正式公众号正稿】复制到公众号后台即可发（系统导出 HTML+表格）。"
        "开篇一段直接答（不少于 80 字）；中段 2–3 个小标题，每节连贯段落；"
        "有对比则必须表格；文末「参考说明」；弱化硬广与外链。"
    ),
    "zhihu": (
        "【正式知乎回答正稿】可直接粘贴发布。"
        "首段完整直接答案（120–200 字）；2–3 个中文小标题展开；"
        "对比/参数必须用表格；可附 2 条简短问答；结尾可执行建议。"
    ),
    "baijiahao": (
        "【正式百家号资讯正稿】标题偏搜索问句；答案前置；"
        "对比用表格；中段完整段落；忌夸张；文末来源。"
    ),
    "toutiao": (
        "【正式头条号短文正稿】结论前置；标题更短；"
        "对比信息用表格；正文连贯可读，勿标题党。"
    ),
}

DEFAULT_MIN_BODY_CHARS: dict[str, int] = {
    "website": 900,
    "wechat": 700,
    "zhihu": 650,
    "baijiahao": 600,
    "toutiao": 500,
}


def default_voice_for_channel(channel: str) -> str:
    if channel in DEFAULT_VOICE_BY_CHANNEL:
        return DEFAULT_VOICE_BY_CHANNEL[channel]
    profile = CHANNEL_PROFILES.get(channel)
    return profile.goal if profile else ""


def default_min_body_chars(channel: str) -> int:
    return int(DEFAULT_MIN_BODY_CHARS.get(channel, 600))


def list_default_prompts() -> dict[str, Any]:
    """Shape shared with GET effective payload (defaults only)."""
    channels = []
    for p in list_profiles():
        key = p["key"]
        channels.append(
            {
                "channel_key": key,
                "display_name": p["display_name"],
                "voice_prompt": default_voice_for_channel(key),
                "voice_default": default_voice_for_channel(key),
                "min_body_chars": default_min_body_chars(key),
                "min_body_chars_default": default_min_body_chars(key),
                "is_custom_voice": False,
                "is_custom_min_body_chars": False,
            }
        )
    return {
        "system_prompt": DEFAULT_SYSTEM_PROMPT,
        "system_prompt_default": DEFAULT_SYSTEM_PROMPT,
        "is_custom_system": False,
        "channels": channels,
    }
