"""China GEO channel blueprint seeds (GeoLook D1, vendored constants).

Numbers come from GeoLook references/cn-source-ranking.md (CN-GEO citation corpus).
Official sites are fact sources (~1.37% of citations), not primary citation sources.
"""

from __future__ import annotations

from typing import Any

# priority_band -> numeric sort weight for media_placements.priority
_BAND_PRIORITY = {"P0": 100, "P1": 80, "P2": 50}

# Map blueprint channel id -> geo_media_placements.channel_type
_TYPE_MAP = {
    "official": "website",
    "baike": "encyclopedia",
    "ranking": "industry_media",
    "wechat": "wechat",
    "toutiao": "toutiao",
    "zhihu": "zhihu",
    "tech": "community_qa",
    "quark": "other",
    "baijia": "baijiahao",
    "media": "industry_media",
    "bilibili": "visual_content",
}

CHANNELS_CN: list[dict[str, Any]] = [
    {
        "id": "official",
        "name": "官网（事实源）",
        "priority": "P0",
        "national": 2569,
        "why": "品牌官网类信源约占国内全库引用的 1.37%——它是事实源不是引用源。作用是让 AI 描述口径正确。",
        "forms": ["定义块与首屏事实", "FAQ", "llms.txt", "JSON-LD"],
        "cadence": "一次建好 + 季度维护",
    },
    {
        "id": "baike",
        "name": "百度百科 / 搜狗百科",
        "priority": "P0",
        "national": 9396,
        "why": "实体消歧地基；baidu.com 同时是百度 AI / 文心高权重来源。",
        "forms": ["品牌词条", "产品词条"],
        "cadence": "一次建好 + 半年维护",
    },
    {
        "id": "ranking",
        "name": "榜单/品牌库站（买购网 chinapp cnpp）",
        "priority": "P1",
        "national": 17116,
        "why": "约 28 个域名吃掉全库引用约 9.1%，且平均引用位置靠前；「有哪些/哪个好」类问题高杠杆。",
        "forms": ["品牌条目", "品类榜单收录", "参数对比表"],
        "cadence": "一次提交 + 季度更新",
    },
    {
        "id": "wechat",
        "name": "微信公众号 / 腾讯新闻",
        "priority": "P1",
        "national": 11017,
        "why": "qq.com 覆盖多平台端，也是腾讯元宝重要引用源。",
        "forms": ["深度长文", "行业观点", "案例复盘"],
        "cadence": "每周或每两周",
    },
    {
        "id": "toutiao",
        "name": "今日头条号 / 抖音图文",
        "priority": "P1",
        "national": 20956,
        "why": "字节生态是豆包系硬门槛；toutiao / iesdouyin 引用量高。",
        "forms": ["图文", "行业科普"],
        "cadence": "每周",
    },
    {
        "id": "zhihu",
        "name": "知乎",
        "priority": "P1",
        "national": None,
        "why": "B2B 决策者聚集地；承接「哪个好/怎么选」类问题。",
        "forms": ["问答回答", "专栏长文"],
        "cadence": "每两周",
    },
    {
        "id": "tech",
        "name": "CSDN / 博客园 / 云开发者社区",
        "priority": "P1",
        "national": 1388,
        "why": "技术 B2B 高权重信源；对 DeepSeek / Kimi 友好。",
        "forms": ["技术实现", "选型对比", "踩坑记录"],
        "cadence": "每两周",
    },
    {
        "id": "quark",
        "name": "夸克 / 神马搜索收录",
        "priority": "P1",
        "national": 6990,
        "why": "sm.cn 引用位置靠前，也是千问重要来源；提交收录成本低。",
        "forms": ["站点收录", "sitemap 推送"],
        "cadence": "一次 + 新页补提",
    },
    {
        "id": "baijia",
        "name": "百家号 / 百度知道",
        "priority": "P2",
        "national": 9396,
        "why": "百度 AI / 文心生态封闭度高，不进百度系难进候选池。",
        "forms": ["百家号文章", "百度知道问答"],
        "cadence": "每两周",
    },
    {
        "id": "media",
        "name": "行业垂类媒体 / 综合新闻",
        "priority": "P2",
        "national": 14733,
        "why": "权威背书；时效衰减快，不适合做唯一常青阵地。",
        "forms": ["新闻稿", "行业观点投稿"],
        "cadence": "按节奏",
    },
    {
        "id": "bilibili",
        "name": "B站 / 视频号",
        "priority": "P2",
        "national": None,
        "why": "视频生态对豆包/抖音 AI 权重高；字幕比画面更关键。",
        "forms": ["演示视频", "教程（完整字幕）"],
        "cadence": "每月",
    },
]

CHANNEL_FITS: dict[str, list[str]] = {
    "official": ["推荐", "比较", "替代", "价格", "风险", "品牌验证", "场景"],
    "baike": ["品牌验证"],
    "ranking": ["推荐", "比较", "替代"],
    "wechat": ["场景", "推荐", "风险"],
    "toutiao": ["场景", "推荐"],
    "zhihu": ["推荐", "比较", "替代", "风险"],
    "tech": ["场景", "比较", "风险"],
    "quark": [],
    "baijia": ["推荐", "场景", "品牌验证"],
    "media": ["推荐", "品牌验证"],
    "bilibili": ["场景"],
}

GROUP_PLAN: dict[str, tuple[str, str]] = {
    "推荐": ("榜单/品类页", "承接「有哪些/best」——先写评选方法再给榜单"),
    "比较": ("对比页", "同口径维度 6–10 个，须写自己的局限"),
    "替代": ("对比页", "正面回应为什么不用现有方案"),
    "价格": ("定义/说明页", "价格透明度直接影响可信度"),
    "风险": ("定义/说明页", "正面回应数据安全/可靠性质疑"),
    "品牌验证": ("关于页 + 百科", "实体消歧与公司事实源"),
    "场景": ("教程/how-to 页", "步骤块 + 数字事实提升可抽取度"),
}

# Longest-suffix first. Used to tag measured cite domains onto CHANNELS_CN.
HOST_SUFFIX_TO_CHANNEL: list[tuple[str, str]] = [
    ("mp.weixin.qq.com", "wechat"),
    ("baijiahao.baidu.com", "baijia"),
    ("baike.baidu.com", "baike"),
    ("zhuanlan.zhihu.com", "zhihu"),
    ("zhihu.com", "zhihu"),
    ("toutiao.com", "toutiao"),
    ("iesdouyin.com", "toutiao"),
    ("csdn.net", "tech"),
    ("cnblogs.com", "tech"),
    ("juejin.cn", "tech"),
    ("bilibili.com", "bilibili"),
    ("sm.cn", "quark"),
    ("chinapp.com", "ranking"),
    ("cnpp.cn", "ranking"),
    ("qq.com", "wechat"),
]


def channel_type_for(channel_id: str) -> str:
    return _TYPE_MAP.get(channel_id, "other")


def match_blueprint_for_domain(domain: str) -> dict[str, Any] | None:
    """Map a cited hostname onto CHANNELS_CN when the suffix is known."""
    host = (domain or "").lower().strip(".")
    if not host:
        return None
    channel_id = None
    for suffix, cid in HOST_SUFFIX_TO_CHANNEL:
        if host == suffix or host.endswith("." + suffix):
            channel_id = cid
            break
    if not channel_id:
        return None
    ch = next((c for c in CHANNELS_CN if c["id"] == channel_id), None)
    if not ch:
        return None
    return {
        "channel_key": channel_id,
        "channel_name": ch["name"],
        "priority_band": ch["priority"],
        "citation_national": ch.get("national"),
    }


def priority_for_band(band: str) -> int:
    return _BAND_PRIORITY.get(band, 40)


def default_media_placement_rows(tenant_id: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index, ch in enumerate(CHANNELS_CN):
        band = ch["priority"]
        national = ch.get("national")
        note_parts = [str(ch["why"])]
        if national is not None:
            note_parts.append(f"CN-GEO 引用量参考：{national}")
        forms = "、".join(ch.get("forms") or [])
        if forms:
            note_parts.append(f"建议形态：{forms}")
        note_parts.append(f"节奏：{ch.get('cadence') or '-'}")
        rows.append(
            {
                "tenant_id": tenant_id,
                "name": ch["name"],
                "channel_type": channel_type_for(ch["id"]),
                "channel_key": ch["id"],
                "target_url": None,
                "authority_note": " ".join(note_parts),
                "status": "planned",
                "published_url": None,
                "priority": priority_for_band(band),
                "priority_band": band,
                "fits_groups": list(CHANNEL_FITS.get(ch["id"], [])),
                "citation_national": national,
                "related_prompt_id": None,
                "created_by": None,
            }
        )
        _ = index
    return rows


def recommend_channels_for_group(group: str | None) -> list[dict[str, Any]]:
    """Return blueprint channels that fit a question group, P0/P1 first."""
    g = (group or "").strip()
    form_note = GROUP_PLAN.get(g)
    form = form_note[0] if form_note else None
    note = form_note[1] if form_note else None
    items: list[dict[str, Any]] = []
    for ch in CHANNELS_CN:
        fits = CHANNEL_FITS.get(ch["id"], [])
        if g:
            # Official is always the fact-source home; others must list the group.
            if ch["id"] != "official" and g not in fits:
                continue
        items.append(
            {
                "channel_key": ch["id"],
                "name": ch["name"],
                "priority_band": ch["priority"],
                "channel_type": channel_type_for(ch["id"]),
                "fits_groups": fits,
                "citation_national": ch.get("national"),
                "why": ch["why"],
                "content_form": form,
                "content_note": note,
            }
        )
    order = {"P0": 0, "P1": 1, "P2": 2}
    items.sort(
        key=lambda x: (order.get(x["priority_band"], 9), -(x["citation_national"] or 0))
    )
    return items


def blueprint_payload(*, group: str | None = None) -> dict[str, Any]:
    return {
        "source": "geolook-cn-geo-citation",
        "official_cite_share_note": "官网类信源约占国内全库引用 1.37%，定位为事实源而非主引用源",
        "groups": list(GROUP_PLAN.keys()),
        "group": group,
        "group_plan": (
            {"form": GROUP_PLAN[group][0], "note": GROUP_PLAN[group][1]}
            if group in GROUP_PLAN
            else None
        ),
        "channels": recommend_channels_for_group(group),
        "all_channels": [
            {
                "channel_key": ch["id"],
                "name": ch["name"],
                "priority_band": ch["priority"],
                "channel_type": channel_type_for(ch["id"]),
                "fits_groups": CHANNEL_FITS.get(ch["id"], []),
                "citation_national": ch.get("national"),
                "why": ch["why"],
            }
            for ch in CHANNELS_CN
        ],
    }
