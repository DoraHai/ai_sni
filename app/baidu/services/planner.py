"""KRService：关键词规划师（拓词数据源，只读）。

文档 1020：getKRByQuery 种子词推荐词（一次一个种子词）
文档 1019：getKRCustom 账户主动推荐词（按账户业务内容推词，id 传 null）

注意：两份文档的 competition 语义标注互相矛盾（1020 写 1低 3高，1019 写 1高 3低）。
按 1020（种子词接口）口径入库：1低 2中 3高——上生产后用已知高竞争词对照校验一次。
"""
import logging
from typing import Any

from app.baidu.client import BaiduAPIClient

logger = logging.getLogger(__name__)

# 每个种子词的推荐词上限。相关性随条数下降（文档 1020），默认收敛到 300
DEFAULT_MAX_NUM = 300


class KeywordPlannerService:
    def __init__(self, client: BaiduAPIClient):
        self._client = client

    def _seed_filter(self, max_num: int) -> dict[str, Any]:
        return {
            "device": 0,
            "maxNum": max_num,
            # 拓词只要新词：账户/计划内已购词都不要
            "removeDuplicate": True,
            "removeCampaignDuplicate": True,
        }

    async def get_words_by_seed(
        self, seed: str, max_num: int = DEFAULT_MAX_NUM
    ) -> list[dict[str, Any]]:
        """种子词 → 推荐词列表。一次调用只允许一个种子词（文档 1020）。"""
        resp = await self._client.call(
            "KRService",
            "getKRByQuery",
            {"query": seed, "seedFilter": self._seed_filter(max_num)},
        )
        data = resp.get("data") or []
        return data if isinstance(data, list) else []

    async def get_account_recommend_words(
        self, max_num: int = DEFAULT_MAX_NUM
    ) -> list[dict[str, Any]]:
        """账户主动推荐词（id 为 null 时 idType 任填，文档 1019）。"""
        resp = await self._client.call(
            "KRService",
            "getKRCustom",
            {"idType": 3, "seedFilter": self._seed_filter(max_num)},
        )
        data = resp.get("data") or []
        return data if isinstance(data, list) else []

    async def get_pv_search(self, words: list[str]) -> list[dict[str, Any]]:
        """批量查关键词流量（PvSearchFunction/getPvSearch，文档 1021，单批 ≤1000）。

        ⚠️ 返回的 kwc 是 1高 2中 3低，与 getKRByQuery 的 competition（1低3高）相反，
        调用侧入库前要做 4-kwc 翻转。黄反/超限的词不在返回里（看 actualWordList）。
        """
        results: list[dict[str, Any]] = []
        for i in range(0, len(words), 1000):
            chunk = words[i : i + 1000]
            resp = await self._client.call(
                "PvSearchFunction",
                "getPvSearch",
                {
                    "bidWordSource": "wordList",
                    "device": 0,
                    "keywordList": [
                        {"keywordName": w, "matchType": 1, "phraseType": 1}
                        for w in chunk
                    ],
                },
            )
            # 生产实测（2026-06-12）：body = {"data": [{"logid":..., "data": [行...],
            # "actualWordList": [...]}]}——外层多包一层 list（同报告接口多 userId 形态），
            # 与文档示例的 dict 形态不符。三种形态都兼容。
            data = resp.get("data")
            if isinstance(data, dict):
                data = [data]
            for item in data if isinstance(data, list) else []:
                if not isinstance(item, dict):
                    continue
                if "keywordName" in item:  # 退化形态：data 直接就是行列表
                    results.append(item)
                else:
                    inner = item.get("data")
                    if isinstance(inner, list):
                        results.extend(r for r in inner if isinstance(r, dict))
        return results
