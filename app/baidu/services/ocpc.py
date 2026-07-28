"""OcpcService：oCPC 出价策略（目标转化包）查询。

文档 0285：OcpcService/getTargetPackageList。level=1 传 userId 拿账户下全部策略。
当前仅查询（只读）；新增/更新/删除（0287/0289/0291）后续单独做。
"""
from typing import Any

from app.baidu.client import BaiduAPIClient

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
