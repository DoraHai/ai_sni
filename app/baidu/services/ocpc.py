"""OcpcService：oCPC 出价策略（目标转化包）查询。

文档 0285：OcpcService/getTargetPackageList。level=1 传 userId 拿账户下全部策略。
文档 0289：updateTargetPackage 仅修改目标转化出价；新增和删除未接入。
"""
from typing import Any
from decimal import Decimal, InvalidOperation

from app.baidu.client import BaiduAPIClient


def normalize_ocpc_bid(value) -> float:
    if isinstance(value, bool):
        raise ValueError("目标转化出价必须是金额")
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError("目标转化出价必须是金额") from None
    if not amount.is_finite() or not Decimal("0.01") <= amount <= Decimal("9999.00"):
        raise ValueError("目标转化出价须在 0.01～9999.00 元之间")
    if amount != amount.quantize(Decimal("0.01")):
        raise ValueError("目标转化出价最多保留两位小数")
    return float(amount)


# 不请求的属性无返回值，按文档 0285 取全字段
TARGET_PACKAGE_FIELDS = [
    "targetPackageId",
    "targetPackageName",
    "ocpcBid",
    "ocpcBidType",
    "scope",
    "dataFlowData",
    "assistTransTypes",
    "ocpcDeepCpa",
    "packageStatus",
    "deepTypeStat",
    "deepTransTypeMode",
    "transAsset",
    "transAssetId",
]


class OcpcService:
    def __init__(self, client: BaiduAPIClient):
        self._client = client

    async def get_target_packages(self, user_id: int) -> list[dict[str, Any]]:
        """拉账户下全部 oCPC 出价策略（level=1，ids=[userId]）。"""
        resp = await self._client.call(
            "OcpcService",
            "getTargetPackageList",
            {
                "targetPackageTypeFields": TARGET_PACKAGE_FIELDS,
                "ids": [user_id],
                "level": 1,
            },
        )
        data = resp.get("data") or []
        return data if isinstance(data, list) else []

    async def update_target_bid(self, package_id: int, bid: float) -> dict[str, Any]:
        """0289：只发送策略 ID 和目标价，不改模式、绑定计划或深度转化。"""
        return await self._client.call(
            "OcpcService", "updateTargetPackage",
            {"targetPackageType": [{"targetPackageId": package_id,
                                    "ocpcBid": normalize_ocpc_bid(bid)}]},
            is_write=True, write_scope="ocpc_bid",
        )
