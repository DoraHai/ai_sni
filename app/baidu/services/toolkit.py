"""ToolkitService：工具类接口。

文档 0915：getOperationRecord 查询历史操作记录（只读）。
optLevel 单值必填，多层级要多次调用；回溯窗口按客户星级 3-12 个月。
"""
import logging
from typing import Any

from app.baidu.client import BaiduAPIClient

logger = logging.getLogger(__name__)

# 调价台账订阅的层级 → 操作内容（文档 0914）。只拉出价/状态/系数类，噪音项不订阅。
# 注意：这里是【请求】传给百度的 optContents，百度严格校验，只能填文档列出的合法枚举
# （mobilePrice 等文档未列的字段作为请求会报 9011708，不能放这里）。
SUBSCRIBED_CONTENTS: dict[int, list[str]] = {
    5: ["bidPriceWord", "shelveWord", "updWordMatch", "wordStrategy"],
    1: ["bidPriceUnit", "matchPriceFactor", "devicePriceFactor"],
    2: ["campaignCycPriceFactor", "updateCampaignPrice", "priceStrategy"],
}

# 入库白名单：百度【返回】里会自带订阅外的项（实测有 mobilePrice 移动出价＝有值要留、
# shelveIdea 创意暂停＝噪音要挡）。入库时按此过滤——在订阅集基础上「加」mobilePrice、
# 不引入它进请求。生产实测：mobilePrice 请求传则 9011708，但返回里会出现且有值。
WHITELISTED_CONTENTS: set[str] = {c for cs in SUBSCRIBED_CONTENTS.values() for c in cs} | {
    "mobilePrice"
}

ALL_OPT_TYPES = list(range(1, 12))  # 文档说"默认为全部"但字段必填，显式传全量


class ToolkitService:
    def __init__(self, client: BaiduAPIClient):
        self._client = client

    async def get_operation_records(
        self, start_date: str, end_date: str
    ) -> list[dict[str, Any]]:
        """拉 [start_date, end_date] 的操作记录，按订阅层级逐层调用后合并。"""
        records: list[dict[str, Any]] = []
        for level, contents in SUBSCRIBED_CONTENTS.items():
            resp = await self._client.call(
                "ToolkitService",
                "getOperationRecord",
                {
                    "startDate": start_date,
                    "endDate": end_date,
                    "optTypes": ALL_OPT_TYPES,
                    "optLevel": level,
                    "optContents": contents,
                    "recordType": 1,  # 搜索
                },
            )
            data = resp.get("data") or []
            if isinstance(data, list):
                for r in data:
                    r["_optLevel"] = level  # 返回体不带层级，调用侧补
                records.extend(data)
        return records
