"""FluctuationAnalysisService：波动归因（只读）。

文档 1033：queryFluctuationReasons 查询波动分析结果——百度官方判定「展现/点击/
消费/转化为什么涨跌」（如"有10个关键词提高出价,2个单元提高出价"）。
同名接口有两个版本，用 FluctuationAnalysisService（1033）不用 DiagnosisService
（1007）：前者多返回 adviceId（可关联优化中心）+ topKeywords（波动关键词及增幅）。

限制：ids 单次只能传 1 个；计划层级（idType=3）timeRange 只能 1；
diagnosisDate 格式 yyyyMMdd；OCPC 出价策略层级 idType=48（timeRange 可 1/3/7）。
"""
import logging
from typing import Any

from app.baidu.client import BaiduAPIClient

logger = logging.getLogger(__name__)

ID_TYPE_CAMPAIGN = 3  # 计划
ID_TYPE_OCPC = 48  # OCPC 出价策略

DIMENSION_LABELS = {1: "展现", 2: "点击", 3: "消费", 4: "转化"}

COMPARE_DAY_ON_DAY = 2  # 日环比（对比前一天）
COMPARE_LABELS = {1: "日同比", 2: "日环比", 3: "过去七天环比"}


class FluctuationService:
    def __init__(self, client: BaiduAPIClient):
        self._client = client

    async def query_fluctuation_reasons(
        self,
        entity_id: int,
        diagnosis_date: str,
        dimension: int,
        id_type: int = ID_TYPE_CAMPAIGN,
        compare_type: int = COMPARE_DAY_ON_DAY,
        time_range: int = 1,
    ) -> list[dict[str, Any]]:
        """查单个计划/投放包某指标的波动原因，返回 factors 列表（可能为空）。

        diagnosis_date 格式 yyyyMMdd。factors 元素含 description /
        adviceId / topKeywords（[{keyword, changeValue}]）/ details（嵌套原因）。
        """
        resp = await self._client.call(
            "FluctuationAnalysisService",
            "queryFluctuationReasons",
            {
                "idType": id_type,
                "ids": [entity_id],
                "timeRange": time_range,
                "compareType": compare_type,
                "diagnosisDate": diagnosis_date,
                "dimension": dimension,
            },
        )
        data = resp.get("data") or []
        factors: list[dict[str, Any]] = []
        for entity in data:
            if isinstance(entity, dict):
                factors.extend(f for f in (entity.get("factors") or []) if isinstance(f, dict))
        return factors
