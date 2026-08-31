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
    "geoLocationStatus",
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
            if not e.is_invalid_request_field:
                raise
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

    async def update_campaign_schedule(
        self,
        campaign_id: int,
        schedule_price_factors: list[dict[str, Any]],
        *,
        pause: bool = False,
    ) -> dict[str, Any]:
        """整表替换计划投放时段；停投模板同时暂停计划。"""
        campaign: dict[str, Any] = {
            "campaignId": campaign_id,
            "schedulePriceFactors": schedule_price_factors,
        }
        if pause:
            campaign["pause"] = True
        return await self._client.call(
            "CampaignService",
            "updateCampaign",
            {"campaignTypes": [campaign]},
            is_write=True,
        )

    async def update_campaign_region(
        self,
        campaign_id: int,
        region_target: list[int],
        *,
        region_price_factor: list[dict[str, Any]] | None = None,
        geo_location_status: int | None = None,
    ) -> dict[str, Any]:
        """更新计划投放地域及分地域出价系数（updateCampaign，文档 0046）。

        ``regionTarget`` 和 ``regionPriceFactor`` 是整表替换字段。调用方应传入
        已确认的完整目标列表；本方法刻意不携带计划的预算、时段、否词等其它字段。
        """
        campaign: dict[str, Any] = {
            "campaignId": campaign_id,
            "regionTarget": region_target,
        }
        if region_price_factor is not None:
            campaign["regionPriceFactor"] = region_price_factor
        if geo_location_status is not None:
            campaign["geoLocationStatus"] = geo_location_status
        return await self._client.call(
            "CampaignService",
            "updateCampaign",
            {"campaignTypes": [campaign]},
            is_write=True,
        )

    async def update_campaign_negative_words(
        self,
        campaign_id: int,
        *,
        negative_words: list[str] | None = None,
        exact_negative_words: list[str] | None = None,
    ) -> dict[str, Any]:
        """更新计划级否词，优先专用服务，失败时回退 updateCampaign。

        与单元级一致，调用方必须传“现有 + 新增”的完整列表；这里只传
        campaignId + 否词字段，避免覆盖计划其他配置。
        """
        body: dict[str, Any] = {"campaignId": campaign_id}
        if negative_words is not None:
            body["negativeWords"] = negative_words
        if exact_negative_words is not None:
            body["exactNegativeWords"] = exact_negative_words
        try:
            return await self._client.call(
                "NegativeWordService",
                "updateCampaignNegativeWordsSync",
                body,
                is_write=True,
            )
        except BaiduAPIError:
            return await self._client.call(
                "CampaignService",
                "updateCampaign",
                {"campaignTypes": [body]},
                is_write=True,
            )
