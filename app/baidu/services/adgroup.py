"""AdgroupService：搜索推广单元相关。

文档 0056：AdgroupService/getAdgroup，idType=3 按计划 ID 查（单次 ≤100）。
"""
import logging
from typing import Any

from app.baidu.client import BaiduAPIClient, BaiduAPIError

logger = logging.getLogger(__name__)

# priceRatio（单元移动出价比率）：查询文档 0056 枚举漏列，但概述 0052 /
# 批量服务列名 0346 / SDK 示例 0017 都有；被拒就剔除重试
ADGROUP_SYNC_FIELDS = [
    "adgroupId",
    "campaignId",
    "adgroupName",
    "maxPrice",
    "pause",
    "status",
    "priceRatio",
    "negativeWords",
    "exactNegativeWords",
    "pcFinalUrl",
    "mobileFinalUrl",
    "pcTrackParam",
    "mobileTrackParam",
    "pcTrackTemplate",
    "mobileTrackTemplate",
]

PROBE_FIELDS = {"priceRatio"}

GET_ADGROUP_BATCH = 100  # idType=3 计划 ID 单次上限


class AdgroupService:
    def __init__(self, client: BaiduAPIClient):
        self._client = client

    async def add_adgroup(self, adgroup: dict[str, Any]) -> dict[str, Any]:
        """新增推广单元（addAdgroup，文档 0058）。

        ⚠️ 写接口：is_write=True 触发 dry-run 安全网。
        """
        return await self._client.call(
            "AdgroupService",
            "addAdgroup",
            {"adgroupTypes": [adgroup]},
            is_write=True,
            write_scope="adgroup_create",
        )

    async def get_adgroups_by_campaign_ids(
        self, campaign_ids: list[int], fields: list[str] | None = None
    ) -> list[dict[str, Any]]:
        """按计划 ID 批量拉单元，自动分批。

        试探字段被明确拒绝时剔除后重试。单个已删除计划不能拖垮整批：
        对“Campaign id not exist”批次做有限二分，隔离并跳过失效 ID。
        """
        use_fields = list(fields or ADGROUP_SYNC_FIELDS)
        adgroups: list[dict[str, Any]] = []

        async def fetch_batch(batch: list[int]) -> list[dict[str, Any]]:
            nonlocal use_fields
            try:
                resp = await self._call_get(use_fields, batch)
            except BaiduAPIError as e:
                if e.is_invalid_request_field:
                    stripped = [f for f in use_fields if f not in PROBE_FIELDS]
                    if stripped == use_fields:
                        raise
                    logger.warning(
                        "getAdgroup 含试探字段被拒（code=%s msg=%s），剔除 %s 重试",
                        e.code, e.message, PROBE_FIELDS & set(use_fields),
                    )
                    use_fields = stripped
                    return await fetch_batch(batch)
                if not e.is_missing_entity("campaign"):
                    raise
                if len(batch) == 1:
                    logger.warning("getAdgroup 跳过百度侧不存在的计划 id=%s", batch[0])
                    return []
                midpoint = len(batch) // 2
                return await fetch_batch(batch[:midpoint]) + await fetch_batch(batch[midpoint:])
            data = resp.get("data") or []
            return data if isinstance(data, list) else []

        for i in range(0, len(campaign_ids), GET_ADGROUP_BATCH):
            # 同一 ID 无需重复请求；dict 保留原始顺序。
            batch = list(dict.fromkeys(campaign_ids[i : i + GET_ADGROUP_BATCH]))
            adgroups.extend(await fetch_batch(batch))
        return adgroups

    async def _call_get(
        self, fields: list[str], ids: list[int]
    ) -> dict[str, Any]:
        return await self._client.call(
            "AdgroupService",
            "getAdgroup",
            {
                "adgroupFields": fields,
                "ids": ids,
                "idType": 3,
                "getTemp": 0,
            },
        )

    async def update_negative_words(
        self,
        adgroup_id: int,
        negative_words: list[str] | None = None,
        exact_negative_words: list[str] | None = None,
    ) -> dict[str, Any]:
        """更新单元否词（updateAdgroup，文档 0057）。

        ⚠️ 写接口 + 全量覆盖：百度按传入列表整体替换该单元的否词，调用方须传"现有 + 新增"
        的完整列表（见 writeback.apply_negative_writeback）。is_write=True 触发 dry-run 安全网。
        """
        adgroup: dict[str, Any] = {"adgroupId": adgroup_id}
        if negative_words is not None:
            adgroup["negativeWords"] = negative_words
        if exact_negative_words is not None:
            adgroup["exactNegativeWords"] = exact_negative_words
        return await self._client.call(
            "AdgroupService", "updateAdgroup", {"adgroupTypes": [adgroup]},
            is_write=True, write_scope="adgroup_negative_words",
        )

    async def update_adgroup_fields(
        self,
        adgroup_id: int,
        *,
        max_price: float | None = None,
        pause: bool | None = None,
        pc_final_url: str | None = None,
        mobile_final_url: str | None = None,
        pc_track_param: str | None = None,
        mobile_track_param: str | None = None,
        pc_track_template: str | None = None,
        mobile_track_template: str | None = None,
    ) -> dict[str, Any]:
        """更新单元字段（updateAdgroup，文档 0060）。只传需要改的字段。

        ⚠️ 只传 adgroupId + 指定字段，不带 negativeWords 等避免覆盖。is_write=True 走 dry-run。
        maxPrice 范围 (0, 999.99] 且 ≤ 所属计划预算；pause=True 暂停 / False 启用。
        """
        adgroup: dict[str, Any] = {"adgroupId": adgroup_id}
        if max_price is not None:
            adgroup["maxPrice"] = max_price
        if pause is not None:
            adgroup["pause"] = pause
        if pc_final_url is not None:
            adgroup["pcFinalUrl"] = pc_final_url
        if mobile_final_url is not None:
            adgroup["mobileFinalUrl"] = mobile_final_url
        if pc_track_param is not None:
            adgroup["pcTrackParam"] = pc_track_param
        if mobile_track_param is not None:
            adgroup["mobileTrackParam"] = mobile_track_param
        if pc_track_template is not None:
            adgroup["pcTrackTemplate"] = pc_track_template
        if mobile_track_template is not None:
            adgroup["mobileTrackTemplate"] = mobile_track_template
        scope_categories = {
            "adgroup_bid" if max_price is not None else None,
            "adgroup_pause" if pause is not None else None,
            "adgroup_landing_url" if any(
                value is not None
                for value in (
                    pc_final_url,
                    mobile_final_url,
                    pc_track_param,
                    mobile_track_param,
                    pc_track_template,
                    mobile_track_template,
                )
            ) else None,
        } - {None}
        if len(scope_categories) != 1:
            raise ValueError("update_adgroup_fields 每次只能更新一种动作类别")
        write_scope = scope_categories.pop()
        return await self._client.call(
            "AdgroupService", "updateAdgroup", {"adgroupTypes": [adgroup]},
            is_write=True, write_scope=write_scope,
        )
