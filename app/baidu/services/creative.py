"""CreativeService：搜索推广基础创意相关。"""
from typing import Any

from app.baidu.client import BaiduAPIClient


class CreativeService:
    def __init__(self, client: BaiduAPIClient):
        self._client = client

    async def add_creative(self, creative: dict[str, Any]) -> dict[str, Any]:
        """新增基础创意（addCreative，文档 0143）。

        ⚠️ 写接口：is_write=True 触发 dry-run 安全网。
        """
        return await self._client.call(
            "CreativeService",
            "addCreative",
            {"creativeTypes": [creative]},
            is_write=True,
        )
