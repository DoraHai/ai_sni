"""ReportService：百度营销 API 数据报告。

实测可用流程（文档 0255/0299）：
  - 同步接口 OpenApiReportService.getReportData，单次返回最多 10 万行
  - reportType 2602783 = 关键词维度
  - reportType 2307838 = 搜索词维度
  - reportType 1237122 = 关键词实时排名（30 分钟窗口）
  - QPS 10，时间范围最大 731 天

> 超过 10 万行时切异步报告流（getProfessionalReportId + 轮询 + 下 CSV），
> 本文件先不实现 — 苏尔寿这种单账户日报告不会超。
"""
from typing import Any

from app.baidu.client import BaiduAPIClient


# 关键词维度报告 columns（文档 0299 全列已收纳）
KEYWORD_REPORT_COLUMNS = [
    "date",
    "userId",
    "userName",
    "campaignId",
    "campaignName",
    "adGroupId",
    "adGroupName",
    "wInfoId",
    "wInfoNameStatus",
    "mixWmatchEnum",
    "device",
    # 效果
    "impression",
    "click",
    "cost",
    "cpc",
    "ctr",
    "avgRank",
    # 质量
    "qualityEnum",
    "estimatedClickRate",
    "businessRelationship",
    "landPageExperience",
    # 上方位
    "topPageViews",
    "topPClicks",
    "topPay",
    "topPvWinA",
    "topFirstPvWinA",
    # 出价
    "bidNew",
    # 转化（苏尔寿配的是电话类：Detail2 电话按钮点击量为主指标，见文档 0262）
    "ocpcConversionsDetail2",
]


# 搜索词报告 columns（文档 0301，reportType 2307838，最大 91 天窗口）
SEARCH_TERM_REPORT_COLUMNS = [
    "queryWord",
    "queryStatusName",
    "wInfoNameStatus",
    "campaignId",
    "campaignName",
    "adGroupId",
    "adGroupName",
    "wMatchId",
    "impression",
    "click",
    "cost",
    "ctr",
    "cpc",
]


KEYWORD_REGION_REPORT_COLUMNS = [
    "date",
    "userId",
    "userName",
    "campaignId",
    "campaignName",
    "adGroupId",
    "adGroupName",
    "wInfoId",
    "wInfoNameStatus",
    "device",
    "provinceCityName",
    "impression",
    "click",
    "cost",
    "ctr",
    "cpc",
]


KEYWORD_HOURLY_REPORT_COLUMNS = [
    "date",
    "userId",
    "userName",
    "campaignId",
    "campaignName",
    "adGroupId",
    "adGroupName",
    "wInfoId",
    "wInfoNameStatus",
    "device",
    "impression",
    "click",
    "cost",
    "ctr",
    "cpc",
]


class ReportService:
    KEYWORD_REPORT_TYPE = 2602783
    SEARCH_TERM_REPORT_TYPE = 2307838

    def __init__(self, client: BaiduAPIClient):
        self._client = client

    async def get_keyword_report(
        self,
        start_date: str,
        end_date: str,
        columns: list[str] | None = None,
        time_unit: str = "DAY",
        page_size: int = 10000,
    ) -> list[dict[str, Any]]:
        """同步拉关键词报告，自动分页直到拉完。

        日期格式 'YYYY-MM-DD'。time_unit 取 DAY/WEEK/MONTH/SUMMARY。
        """
        return await self._get_report_rows(
            self.KEYWORD_REPORT_TYPE,
            start_date,
            end_date,
            columns or KEYWORD_REPORT_COLUMNS,
            time_unit,
            page_size,
        )

    async def get_search_term_report(
        self,
        start_date: str,
        end_date: str,
        columns: list[str] | None = None,
        time_unit: str = "SUMMARY",
        page_size: int = 10000,
    ) -> list[dict[str, Any]]:
        """搜索词报告（拓词"搜索词转拓词"源）。窗口最大 91 天，默认时段汇总。"""
        return await self._get_report_rows(
            self.SEARCH_TERM_REPORT_TYPE,
            start_date,
            end_date,
            columns or SEARCH_TERM_REPORT_COLUMNS,
            time_unit,
            page_size,
        )

    async def get_keyword_region_report(
        self,
        start_date: str,
        end_date: str,
        columns: list[str] | None = None,
        time_unit: str = "DAY",
        page_size: int = 10000,
    ) -> list[dict[str, Any]]:
        """关键词地域效果报告。

        百度文档 0299：provinceCityName / provinceName 不支持 HOUR。
        """
        return await self._get_report_rows(
            self.KEYWORD_REPORT_TYPE,
            start_date,
            end_date,
            columns or KEYWORD_REGION_REPORT_COLUMNS,
            time_unit,
            page_size,
        )

    async def get_keyword_hourly_report(
        self,
        start_date: str,
        end_date: str,
        columns: list[str] | None = None,
        page_size: int = 10000,
    ) -> list[dict[str, Any]]:
        """关键词小时效果报告。"""
        return await self._get_report_rows(
            self.KEYWORD_REPORT_TYPE,
            start_date,
            end_date,
            columns or KEYWORD_HOURLY_REPORT_COLUMNS,
            "HOUR",
            page_size,
        )

    async def _get_report_rows(
        self,
        report_type: int,
        start_date: str,
        end_date: str,
        columns: list[str],
        time_unit: str,
        page_size: int,
    ) -> list[dict[str, Any]]:
        all_rows: list[dict[str, Any]] = []
        start_row = 0

        while True:
            body = {
                "reportType": report_type,
                "startDate": start_date,
                "endDate": end_date,
                "timeUnit": time_unit,
                "columns": columns,
                "sorts": [],
                "filters": [],
                "startRow": start_row,
                "rowCount": page_size,
                "needSum": False,
            }
            resp = await self._client.call(
                "OpenApiReportService", "getReportData", body
            )
            # 实测百度响应结构：
            #   {"data": [
            #     {"rowCount": N, "totalRowCount": M, "rows": [...真实数据...]},
            #     ...  多 userId 时每个 user 一条，单 user 时长度 1
            #   ]}
            # 偶尔退化为 {"data": {"rows": [...], "totalRowCount": M}}，也兼容
            data = resp.get("data")
            page_rows: list[dict[str, Any]] = []
            page_total: int | None = None
            if isinstance(data, list):
                for item in data:
                    if isinstance(item, dict):
                        page_rows.extend(item.get("rows") or [])
                        if page_total is None:
                            tc = item.get("totalRowCount")
                            page_total = int(tc) if tc is not None else None
            elif isinstance(data, dict):
                page_rows = data.get("rows") or []
                tc = data.get("totalRowCount")
                page_total = int(tc) if tc is not None else None

            all_rows.extend(page_rows)

            # 退出条件：本次空 / 不足一页 / 累计达 total
            if not page_rows:
                break
            if len(page_rows) < page_size:
                break
            if page_total is not None and len(all_rows) >= page_total:
                break
            start_row = len(all_rows)

        return all_rows
