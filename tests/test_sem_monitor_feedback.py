import asyncio
from datetime import date
import os
from types import SimpleNamespace

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("BAIDU_APP_ID", "test-app")
os.environ.setdefault("BAIDU_SECRET_KEY", "test-secret")
os.environ.setdefault("BAIDU_DEFAULT_USERNAME", "test-user")
os.environ.setdefault("BAIDU_DEFAULT_UCID", "1")
os.environ.setdefault("BAIDU_SELF_ACCESS_TOKEN", "test-token")
os.environ.setdefault("BAIDU_SELF_TOKEN_EXPIRES_AT", "2099-01-01T00:00:00")
os.environ.setdefault(
    "CRYPTO_MASTER_KEY_B64", "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="
)
os.environ.setdefault("ADMIN_API_KEY", "test-admin-key")

from app.rules.budget_overrun import BudgetOverrunRule
from app.rules.site_health import SiteHealthRule, _is_excluded_probe_url


class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _Scalars:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _BudgetSession:
    def __init__(self, accounts):
        self._accounts = accounts

    async def execute(self, _statement):
        return _Rows([(1, 100), (2, 20), (None, 30)])

    async def scalars(self, _statement):
        return _Scalars(self._accounts)


class _SiteSession:
    def __init__(self, adgroups):
        self._adgroups = adgroups

    async def scalars(self, _statement):
        return _Scalars(self._adgroups)


def test_account_budget_alert_uses_only_that_baidu_accounts_cost(monkeypatch):
    accounts = [
        SimpleNamespace(id=1, baidu_username="account-one"),
        SimpleNamespace(id=2, baidu_username="account-two"),
    ]

    class _AccountService:
        def __init__(self, account):
            self.account = account

        async def get_account_info(self, _fields):
            return {"data": {"budget": 50, "budgetType": 1}}

    monkeypatch.setattr(
        "app.rules.budget_overrun._account_client", lambda account: account
    )
    monkeypatch.setattr("app.rules.budget_overrun.AccountService", _AccountService)

    alerts = asyncio.run(
        BudgetOverrunRule()._account_alerts(
            _BudgetSession(accounts),
            SimpleNamespace(id=9),
            date(2026, 8, 31),
        )
    )

    assert [alert.entity_ref for alert in alerts] == ["account:1"]
    assert alerts[0].metrics["cost"] == 100
    assert alerts[0].metrics["cost_baidu_account_id"] == 1


def test_single_account_keeps_legacy_cost_without_account_id(monkeypatch):
    account = SimpleNamespace(id=1, baidu_username="only-account")

    class _AccountService:
        def __init__(self, account):
            self.account = account

        async def get_account_info(self, _fields):
            return {"data": {"budget": 120, "budgetType": 1}}

    monkeypatch.setattr(
        "app.rules.budget_overrun._account_client", lambda account: account
    )
    monkeypatch.setattr("app.rules.budget_overrun.AccountService", _AccountService)

    alerts = asyncio.run(
        BudgetOverrunRule()._account_alerts(
            _BudgetSession([account]),
            SimpleNamespace(id=9),
            date(2026, 8, 31),
        )
    )

    assert len(alerts) == 1
    assert alerts[0].metrics["cost"] == 130


def test_site_health_excludes_only_wejianzhan_aisite_host_family():
    assert _is_excluded_probe_url("https://aisite.wejianzhan.com/site/page")
    assert _is_excluded_probe_url("https://A.AISITE.WEJIANZHAN.COM.:443/path")
    assert not _is_excluded_probe_url("https://aisite.wejianzhan.com.evil.example/path")
    assert not _is_excluded_probe_url(
        "https://customer.example/?next=https://aisite.wejianzhan.com"
    )


def test_site_health_does_not_probe_excluded_wejianzhan_url(monkeypatch):
    adgroups = [
        SimpleNamespace(
            adgroup_id=1,
            adgroup_name="provider-page",
            pc_final_url="https://aisite.wejianzhan.com/site/a",
            mobile_final_url=None,
        ),
        SimpleNamespace(
            adgroup_id=2,
            adgroup_name="customer-page",
            pc_final_url="https://customer.example/landing",
            mobile_final_url=None,
        ),
    ]
    seen = []

    async def _fetch(url, **_kwargs):
        seen.append(url)
        return SimpleNamespace(status_code=200)

    monkeypatch.setattr("app.rules.site_health.fetch_public_url", _fetch)

    alerts = asyncio.run(
        SiteHealthRule().evaluate(
            _SiteSession(adgroups),
            SimpleNamespace(id=9),
            date(2026, 9, 1),
        )
    )

    assert alerts == []
    assert seen == ["https://customer.example/landing"]
