"""KeywordService：搜索推广关键词相关。"""
import logging
import re
from typing import Any

from app.baidu.client import BaiduAPIClient, BaiduAPIError

logger = logging.getLogger(__name__)

DEFAULT_KEYWORD_FIELDS = [
    "keywordId",
    "adgroupId",
    "campaignId",
    "keyword",
    "matchType",
    "price",
    "status",
    "pause",
    "device",
    "phraseType",
]

# 关键词维度同步用字段（getWord，文档 0066）。tabs[31]=重点关键词标签
WORD_SYNC_FIELDS = [
    "keywordId",
    "campaignId",
    "adgroupId",
    "keyword",
    "matchType",
    "phraseType",
    "price",
    "pause",
    "status",
    "tabs",
    "quality",
    "createTime",
    "leftPriceGuide",  # 计算机指导价（文档 0066，[0,999.99)，数据不足返回 -）
    "mPriceGuide",  # 移动指导价
]

# idType=11 按关键词 ID 查，单次上限 10000；留余量分批
GET_WORD_BATCH = 5000
# idType=5 按单元 ID 查，单次上限 50
GET_WORD_ADGROUP_BATCH = 50


class KeywordService:
    def __init__(self, client: BaiduAPIClient):
        self._client = client

    async def update_word_bid(
        self, keyword_id: int, price: float
    ) -> dict[str, Any]:
        """回写单个关键词出价（updateWord，文档 0070）。

        ⚠️ 写接口：is_write=True 触发 dry-run 安全网（演练开关开启时不真发，见 client.py）。
        body 必填 keywordTypes[]（文档 0070 请求示例核对）；price 单位元，保留两位。
        """
        body = {"keywordTypes": [{"keywordId": keyword_id, "price": round(float(price), 2)}]}
        return await self._client.call(
            "KeywordService", "updateWord", body, is_write=True
        )

    async def update_word_pause(
        self, keyword_id: int, pause: bool
    ) -> dict[str, Any]:
        """暂停 / 启用关键词（updateWord 的 pause 字段，文档 0070）。

        ⚠️ 写接口：is_write=True 触发 dry-run 安全网。pause=True 暂停、False 启用。
        """
        body = {"keywordTypes": [{"keywordId": keyword_id, "pause": bool(pause)}]}
        return await self._client.call(
            "KeywordService", "updateWord", body, is_write=True
        )

    async def update_word_match_type(
        self, keyword_id: int, match_type: int, phrase_type: int
    ) -> dict[str, Any]:
        """修改关键词匹配模式（updateWord 的 matchType/phraseType 字段）。"""
        body = {
            "keywordTypes": [
                {
                    "keywordId": keyword_id,
                    "matchType": match_type,
                    "phraseType": phrase_type,
                }
            ]
        }
        return await self._client.call(
            "KeywordService", "updateWord", body, is_write=True
        )

    async def add_word(
        self, adgroup_id: int, keyword: str, match_type: int, phrase_type: int, price: float
    ) -> dict[str, Any]:
        """新增关键词到单元（addWord，文档 0068，搜索词转拓词用）。

        ⚠️ 写接口：is_write=True 触发 dry-run 安全网。body 必填 keywordTypes[]，
        matchType + phraseType 必须配合（文档 0064/0068）：精确=1+1、短语=2+1、智能=2+3。
        price 单位元，保留两位。
        """
        body = {
            "keywordTypes": [
                {
                    "adgroupId": adgroup_id,
                    "keyword": keyword,
                    "matchType": match_type,
                    "phraseType": phrase_type,
                    "price": round(float(price), 2),
                }
            ]
        }
        return await self._client.call(
            "KeywordService", "addWord", body, is_write=True
        )

    async def get_keyword_by_adgroup_id(
        self, adgroup_ids: list[int], fields: list[str] | None = None
    ) -> dict[str, Any]:
        body = {
            "adgroupIds": adgroup_ids,
            "keywordFields": fields or DEFAULT_KEYWORD_FIELDS,
        }
        return await self._client.call(
            "KeywordService", "getKeywordByAdgroupId", body
        )

    async def get_words_by_ids(
        self, keyword_ids: list[int], fields: list[str] | None = None
    ) -> list[dict[str, Any]]:
        """按关键词 ID 批量查关键词属性（getWord, idType=11），自动分批。

        快照里的词可能已在百度后台删除，getWord 会整批报错
        （90180000259 "winfoid xxx not exists"，生产实测 2026-06-11）——
        从 failures 里解析出不存在的 ID 剔除后重试。
        """
        words: list[dict[str, Any]] = []
        for i in range(0, len(keyword_ids), GET_WORD_BATCH):
            words.extend(
                await self._get_word_batch(
                    keyword_ids[i : i + GET_WORD_BATCH],
                    fields or WORD_SYNC_FIELDS,
                    id_type=11,
                )
            )
        return words

    async def get_words_by_adgroup_ids(
        self, adgroup_ids: list[int], fields: list[str] | None = None
    ) -> list[dict[str, Any]]:
        """按单元 ID 全量枚举关键词（getWord, idType=5），零展现词也能拿到。"""
        words: list[dict[str, Any]] = []
        for i in range(0, len(adgroup_ids), GET_WORD_ADGROUP_BATCH):
            words.extend(
                await self._get_word_batch(
                    adgroup_ids[i : i + GET_WORD_ADGROUP_BATCH],
                    fields or WORD_SYNC_FIELDS,
                    id_type=5,
                )
            )
        return words

    async def _get_word_batch(
        self, ids: list[int], fields: list[str], id_type: int
    ) -> list[dict[str, Any]]:
        remaining = list(ids)
        for _ in range(10):  # 每轮剔除报错的不存在 ID，防御性上限
            if not remaining:
                return []
            try:
                resp = await self._client.call(
                    "KeywordService",
                    "getWord",
                    {
                        "wordFields": fields,
                        "ids": remaining,
                        "idType": id_type,
                        "getTemp": 0,
                    },
                )
                data = resp.get("data") or []
                return data if isinstance(data, list) else []
            except BaiduAPIError as e:
                failures = (e.raw.get("header") or {}).get("failures") or []
                bad = {
                    int(m)
                    for f in failures
                    for m in re.findall(r"\d{6,}", str(f.get("message", "")))
                }
                bad &= set(remaining)
                if not bad:
                    raise  # 不是"ID 不存在"类错误，原样抛出
                logger.info("getWord 剔除已删除关键词 %d 个后重试", len(bad))
                remaining = [i for i in remaining if i not in bad]
        logger.warning("getWord 重试次数耗尽，跳过剩余 %d 个 ID", len(remaining))
        return []
