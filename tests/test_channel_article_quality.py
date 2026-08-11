"""Article-level quality gate for channel polish."""

from __future__ import annotations

from app.geo.content.channel_polish import assess_article_quality


def test_outline_style_rejected():
    md = """
## 三大关键评估维度

**安全架构**是首要考量。平台应支持认证。

**生产就绪性**同样重要。平台需要故障转移。

**合规**也要注意。
"""
    issues = assess_article_quality(md, min_chars=1000, channel="zhihu")
    assert any("字数不足" in x or "段落" in x or "加粗" in x for x in issues)


def test_full_article_passes():
    para = (
        "在制造业场景中，企业选择私有化数据分析平台时，需要同时兼顾数据主权、"
        "产线稳定性与分级授权能力。单纯套用通用云方案，往往在网络隔离与身份集成上"
        "无法满足工厂现场的硬约束，因此应先明确安全边界与运维职责再进入选型。"
    )
    md = f"""
## 开篇

{para}

{para}

## 核心要求

{para}

{para}

## 选型对比

| 维度 | 自建 | 商业平台 |
| --- | --- | --- |
| 权限 | 细 | 中 |
| 运维 | 高 | 低 |

上表说明：权限要求高时应优先评估可对接企业身份源的方案，并预留产线网络分区策略。

{para}

## 结论

{para}
"""
    issues = assess_article_quality(md, min_chars=600, channel="zhihu")
    assert issues == [], issues
