"""PriceStrategyService：优化排名出价策略。

文档 0302：PriceStrategyService/getPriceStrategy。
"""
from typing import Any

from app.baidu.client import BaiduAPIClient

STRATEGY_FIELDS = [
    "strategyId",
    "strategyName",
    "strategyType",
    "targetRank",
    "priceFactor",
    "isPause",
    "priceStrategyCampaignTypes",
]


class PriceStrategyService:
    def __init__(self, client: BaiduAPIClient):
        self._client = client

    async def get_ranking_strategies(self) -> list[dict[str, Any]]:
        """拉账户全部「优化排名」出价策略（strategyType=0）。

        文档把 ids 标为必填，传空数组期望返回全部（同 getCampaign 约定）；
        若生产实测不支持需改为先查 ID 列表。
        """
        resp = await self._client.call(
            "PriceStrategyService",
            "getPriceStrategy",
            {
                "fields": STRATEGY_FIELDS,
                "strategyTypes": [0],
                "ids": [],
                "idType": 32,
                "strategyLevels": [3],
            },
        )
        data = resp.get("data") or []
        return data if isinstance(data, list) else []
