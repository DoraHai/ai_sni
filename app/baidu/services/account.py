"""AccountService：账户信息查询 + 更新（账户日预算写回）。

文档：0034 查询账户 / 0036 更新账户（updateAccountInfo）。
"""
from typing import Any

from app.baidu.client import BaiduAPIClient


# 合法枚举见文档 0034，注意没有 userName / mobileBalance（传了报 9011519）
DEFAULT_ACCOUNT_FIELDS = [
    "userId",
    "balance",
    "pcBalance",
    "cost",
    "budgetType",
    "budget",
]


class AccountService:
    def __init__(self, client: BaiduAPIClient):
        self._client = client

    async def get_account_info(self, fields: list[str] | None = None) -> dict[str, Any]:
        body = {"accountFields": fields or DEFAULT_ACCOUNT_FIELDS}
        return await self._client.call("AccountService", "getAccountInfo", body)

    async def update_account_budget(
        self, budget: float, budget_type: int = 1
    ) -> dict[str, Any]:
        """更新账户日预算（updateAccountInfo，文档 0036）。budget_type=1 日预算。

        ⚠️ 只传 budget+budgetType，绝不带 regionTarget/excludeIp 等其它字段，
        否则会把账户的地域/IP 排除等设置一并重置。is_write=True 走 dry-run 安全网。
        """
        return await self._client.call(
            "AccountService",
            "updateAccountInfo",
            {"accountInfo": {"budget": budget, "budgetType": budget_type}},
            is_write=True,
            write_scope="account_budget",
        )
