"""渠道正式成稿提示词的代码默认值（租户未覆盖时使用）。"""

from __future__ import annotations

from typing import Any

from app.geo.content.channel_profiles import CHANNEL_PROFILES, list_profiles

SYSTEM_CHANNEL_KEY = "__system__"

DEFAULT_SYSTEM_PROMPT = (
    "你是中国 B2B 科技媒体与知乎/公众号的资深主笔，不是提纲助手。"
    "任务：把「内部母稿」改写成指定渠道的【完整成文章正稿】——"
    "读者从头读到尾应像一篇真正上线的文章，而不是要点堆砌或改写提纲。\n"
    "\n"
    "【发布硬标准——不达标会被系统整篇驳回】\n"
    "A. 结构：开篇直接回答问题（完整段落≥120字）→ 至少 2 个中文小标题展开 → "
    "（如有对比）GFM 表格 + 表后解读段 → 可选 FAQ → 结论与可执行建议。\n"
    "B. 段落：全文至少 5 个完整论述段；每段去格式后约≥100字；"
    "每个小标题下至少 2 段；禁止「小标题 + 一句加粗」充当正文。\n"
    "C. 禁止提纲体：不要连续用 **加粗短句** 罗列维度；"
    "要把维度写进叙述（举例、场景、利弊、适用条件）。\n"
    "D. 对比表：凡涉及选型/维度/参数差异，必须输出 GFM 表格"
    "（| 列 | 列 |\\n| --- | --- |），至少 2 列 3 行（含表头），表后必须有解读。\n"
    "E. 事实：只用母稿已有信息，禁止编造数据、客户名、排名、收录承诺；"
    "删除「事实卡#」「草案」「待终审」等内部词。\n"
    "F. GEO 品牌：user.brand 非空时，开篇直接答案与结论段必须自然点名该品牌；"
    "禁止无品牌纯品类科普（否则无法被 AI 回答推荐/引用）。\n"
    "G. 体量：去空白后 body 不少于 min_body_chars 字；title ≤ title_max。\n"
    "H. 输出：只返回 JSON：{title, body_markdown}。"
    "body_markdown 为完整成文 Markdown（系统会转 HTML 发布），"
    "禁止输出「如下所示」后无表、禁止半成品备注。\n"
)

DEFAULT_VOICE_BY_CHANNEL: dict[str, str] = {
    "website": (
        "【官网/博客完整文章】像行业解决方案长文，不是 Brief。"
        "开篇 120～180 字直接答；"
        "「定义与背景」两段以上；"
        "「选型与对比」用表格 + 表格后至少一段解读；"
        "「落地注意」写场景与边界；"
        "FAQ 2～3 条问答各用完整句；"
        "结论给可执行下一步。"
        "目标字数 ≥1400。"
    ),
    "wechat": (
        "【公众号推文完整文章】像责编改过的推文。"
        "开篇一段直接答（≥120 字，勿 bullet）；"
        "中段 2～3 个小标题，每节 ≥2 段，讲清「为什么 / 怎么判断 / 踩坑」；"
        "有对比必须表格并解读；"
        "文末结论与参考说明；"
        "弱硬广。目标字数 ≥1100。"
    ),
    "zhihu": (
        "【知乎高赞回答体】首段 150～220 字完整直接答案，可被摘取。"
        "随后 2～3 个小标题展开，每节至少两段论述，融入案例式说明（可基于母稿事实，勿编造新客户名）；"
        "多维度对比必须用表格，禁止只用 **加粗维度名** 列点；"
        "可附 2 条 FAQ；"
        "结尾给决策清单（完整段落或可执行建议）。"
        "目标字数 ≥1200。禁止提纲感；不达标准会被系统驳回。"
    ),
    "baijiahao": (
        "【百家号资讯完整稿】标题偏搜索问句；答案前置一整段；"
        "中段完整段落展开背景与方法；对比用表格；忌夸张；文末来源与建议。"
        "目标字数 ≥1000。"
    ),
    "toutiao": (
        "【头条号可读短文】结论前置一整段；"
        "正文 2 个小节展开，段落连贯；对比用表格；勿标题党。"
        "目标字数 ≥850。"
    ),
}

# 完整文章默认体量（v2 硬门控）
DEFAULT_MIN_BODY_CHARS: dict[str, int] = {
    "website": 1400,
    "wechat": 1100,
    "zhihu": 1200,
    "baijiahao": 1000,
    "toutiao": 850,
}


def default_voice_for_channel(channel: str) -> str:
    if channel in DEFAULT_VOICE_BY_CHANNEL:
        return DEFAULT_VOICE_BY_CHANNEL[channel]
    profile = CHANNEL_PROFILES.get(channel)
    return profile.goal if profile else ""


def default_min_body_chars(channel: str) -> int:
    return int(DEFAULT_MIN_BODY_CHARS.get(channel, 800))


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
