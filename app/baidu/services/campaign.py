"""CampaignService：搜索推广计划相关。

文档 0042：CampaignService/getCampaign，campaignIds 传空返回整个账户的计划。
"""
import logging
from typing import Any

from app.baidu.client import BaiduAPIClient, BaiduAPIError

logger = logging.getLogger(__name__)

# 计划维度同步字段。regionPriceFactor / schedulePriceFactors 是
# 出价系数叠加里的分地域、分时段两层；priceRatio 是移动比例层
# （查询文档 0042 枚举漏列，但批量服务列名 0346 / 更新示例 0046 都有，
#  PROBE_FIELDS 里防御：被拒就剔除重试）
CAMPAIGN_SYNC_FIELDS = [
    "campaignId",
    "campaignName",
    "budget",
    "pause",
    "status",
    "equipmentType",
    "regionTarget",
    "schedule",
    "regionPriceFactor",
    "schedulePriceFactors",
    "priceRatio",
    "negativeWords",
    "exactNegativeWords",
    "createTime",
]

# 文档枚举没列、靠生产试探确认的字段。9011519 = Request field is invalid
PROBE_FIELDS = {"priceRatio"}


class CampaignService:
    def __init__(self, client: BaiduAPIClient):
        self._client = client

    async def add_campaign(self, campaign: dict[str, Any]) -> dict[str, Any]:
        """新增推广计划（addCampaign，文档 0044）。

        ⚠️ 写接口：is_write=True 触发 dry-run 安全网。调用方只传已确认字段，
        避免把不确定的地域、时段、否词等设置带入真实账户。
        """
        return await self._client.call(
            "CampaignService",
            "addCampaign",
            {"campaignTypes": [campaign], "adType": 0},
            is_write=True,
        )

    async def get_all_campaigns(
        self, fields: list[str] | None = None
    ) -> list[dict[str, Any]]:
        """拉账户下全部计划（搜索推广，adType=0 普通计划）。

        试探字段被百度拒绝时自动剔除重试，不让每日同步整体失败。
        """
        use_fields = list(fields or CAMPAIGN_SYNC_FIELDS)
        try:
            resp = await self._call_get(use_fields)
        except BaiduAPIError as e:
            stripped = [f for f in use_fields if f not in PROBE_FIELDS]
            if stripped == use_fields:
                raise
            logger.warning(
                "getCampaign 含试探字段被拒（code=%s msg=%s），剔除 %s 重试",
                e.code, e.message, PROBE_FIELDS & set(use_fields),
            )
            resp = await self._call_get(stripped)
        data = resp.get("data") or []
        return data if isinstance(data, list) else []

    async def _call_get(self, fields: list[str]) -> dict[str, Any]:
        return await self._client.call(
            "CampaignService",
            "getCampaign",
            {
                "campaignFields": fields,
                "campaignIds": [],
                "adType": 0,
            },
        )

    async def update_campaign_budget(
        self, campaign_id: int, budget: float
    ) -> dict[str, Any]:
        """更新计划每日预算（updateCampaign，文档 0046）。body key=campaignTypes。

        ⚠️ 只传 campaignId+budget，绝不带 negativeWords/schedule/regionTarget 等其它字段，
        否则会把计划的否词/时段/地域等设置一并覆盖。is_write=True 走 dry-run 安全网。
        计划预算范围 [50, min(1000万, 账户预算)]，超账户预算百度会拒。
        """
        return await self._client.call(
            "CampaignService",
            "updateCampaign",
            {"campaignTypes": [{"campaignId": campaign_id, "budget": budget}]},
            is_write=True,
        )

    async def update_campaign_pause(
        self, campaign_id: int, pause: bool
    ) -> dict[str, Any]:
        """计划启停（updateCampaign pause，文档 0046）。pause=True 暂停 / False 启用。

        ⚠️ 只传 campaignId+pause，不带其它字段避免覆盖。is_write=True 走 dry-run 安全网。
        """
        return await self._client.call(
            "CampaignService",
            "updateCampaign",
            {"campaignTypes": [{"campaignId": campaign_id, "pause": pause}]},
            is_write=True,
        )
