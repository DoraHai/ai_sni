"""模块数据源抽象。

现在三个方法都返回手写的假数据，形状严格按 contracts.py 里的共享契约来。
等 SEM / SEO / GEO 三个窗口把真实的指标快照接口和任务接口做出来之后，
把这里换成真正的 httpx 调用即可——上层（main.py）不需要跟着改。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timedelta, timezone

from app.contracts import Metric, Trend7d


def _now() -> datetime:
    return datetime.now(timezone.utc)


class ModuleMetricSource(ABC):
    module: str

    @abstractmethod
    async def fetch_metrics(self, tenant_id: str) -> list[Metric]:
        ...


class MockSemSource(ModuleMetricSource):
    module = "sem"

    async def fetch_metrics(self, tenant_id: str) -> list[Metric]:
        now = _now()
        return [
            Metric(
                metric_key="sem.spend.budget_utilization_pct",
                value=78.0,
                unit="pct",
                as_of=now,
                trend_7d=Trend7d(direction="up", change_pct=5.0),
                definition="本月已消耗预算 / 本月总预算，按百度推广账户日预算累加计算",
            ),
            Metric(
                metric_key="sem.writeback.pending_approval_count",
                value=3,
                unit="count",
                as_of=now,
                trend_7d=Trend7d(direction="flat", change_abs=0),
                definition="当前状态为 pending 且等待人工确认的出价/预算写回操作数",
            ),
            Metric(
                metric_key="sem.identity.conflict_tenant_count",
                value=0,
                unit="count",
                as_of=now,
                trend_7d=None,
                definition="因 UCID 归属冲突被 fail-closed 暂停展示数据的客户数",
            ),
        ]


class MockSeoSource(ModuleMetricSource):
    module = "seo"

    async def fetch_metrics(self, tenant_id: str) -> list[Metric]:
        now = _now()
        return [
            Metric(
                metric_key="seo.ranking.top10_keyword_count",
                value=42,
                unit="count",
                as_of=now,
                trend_7d=Trend7d(direction="up", change_abs=3),
                definition="当前排名进入百度自然搜索结果前 10 的核心词数量",
            ),
            Metric(
                metric_key="seo.content.published_7d_count",
                value=3,
                unit="count",
                as_of=now,
                trend_7d=Trend7d(direction="up", change_abs=1),
                definition="近 7 天内状态变为已发布的内容篇数",
            ),
            Metric(
                metric_key="seo.image_remediation.confirmed_fix_rate_pct",
                value=61.0,
                unit="pct",
                as_of=now,
                trend_7d=Trend7d(direction="up", change_pct=8.0),
                definition="重新抓取确认已修复的图片数 / 已审核通过的图片建议总数",
            ),
        ]


class MockGeoSource(ModuleMetricSource):
    module = "geo"

    async def fetch_metrics(self, tenant_id: str) -> list[Metric]:
        now = _now()
        return [
            Metric(
                metric_key="geo.visibility.ai_mention_count_7d",
                value=21,
                unit="count",
                as_of=now,
                trend_7d=Trend7d(direction="up", change_abs=6),
                definition="近 7 天内品牌在受监测 AI 引擎问答中被提及的次数",
            ),
            Metric(
                metric_key="geo.visibility.score",
                value=68.0,
                unit="score",
                as_of=now,
                trend_7d=Trend7d(direction="up", change_pct=12.0),
                definition="综合提及频次、引用位置、竞品对比换算出的 0-100 可见度评分",
            ),
            Metric(
                metric_key="geo.competitor.visibility_delta_pct",
                value=0.0,
                unit="pct",
                as_of=now,
                trend_7d=Trend7d(direction="flat", change_pct=0.0),
                definition="同期跟踪竞品的可见度评分环比变化，用于判断是行业普涨还是自身突出",
            ),
        ]


SOURCES: dict[str, ModuleMetricSource] = {
    "sem": MockSemSource(),
    "seo": MockSeoSource(),
    "geo": MockGeoSource(),
}
