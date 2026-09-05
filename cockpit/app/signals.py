"""信号引擎的占位实现。

真正的信号引擎应该是：拿 sources.py 汇总出的指标快照，跑一批人工定义好的
触发规则，命中了才产出一条 Signal。现在还没有指标真实数据也没有规则库，
先手写一条和原型演示里一致的信号，把"信号是怎么被对话引用"的接口形状定下来。

替换成真实规则引擎时，evaluate_signals() 的函数签名不用变，
上层（main.py）不需要跟着改。
"""
from __future__ import annotations

from datetime import datetime, timezone

from app.contracts import Signal


async def evaluate_signals(tenant_id: str) -> list[Signal]:
    now = datetime.now(timezone.utc)
    return [
        Signal(
            id="sig-001",
            modules=["sem", "seo", "geo"],
            headline=(
                "SEM「智能仓储解决方案」这批词花费集中但转化偏低，"
                "SEO 同批词的新内容正在自然爬升，GEO 该话题本周提及量创近三月新高——"
                "建议把这批词的部分预算转去支持内容承接。"
            ),
            basis=[
                "sem.spend.budget_utilization_pct：该批词占本月预算 34%，转化率低于账户均值",
                "seo.content.published_7d_count：同批词相关内容《智能仓储如何降低30%人力成本》"
                "首周流量已在爬升",
                "geo.visibility.ai_mention_count_7d：该话题本周被 AI 引擎提及 21 次，环比 +6，"
                "同期竞品可见度持平，说明是自身内容抓住窗口，非行业普涨",
            ],
            confidence="medium",
            detected_at=now,
            related_metric_keys=[
                "sem.spend.budget_utilization_pct",
                "seo.content.published_7d_count",
                "geo.visibility.ai_mention_count_7d",
                "geo.competitor.visibility_delta_pct",
            ],
        )
    ]
