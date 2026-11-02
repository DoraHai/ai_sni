"""顾问单页提交契约；字段是内部模型，不是百度模板列。"""
from __future__ import annotations

from datetime import datetime
from ipaddress import ip_address
from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]
Id = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80, pattern=r"^[\w-]+$")]
Money = Annotated[int, Field(strict=True, gt=0)]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class TimeSlot(Contract):
    days: list[Annotated[int, Field(strict=True, ge=1, le=7)]] = Field(min_length=1, max_length=7)
    start_hour: int = Field(strict=True, ge=0, le=23)
    end_hour: int = Field(strict=True, ge=1, le=24)

    @model_validator(mode="after")
    def ordered(self):
        if self.start_hour >= self.end_hour or len(set(self.days)) != len(self.days):
            raise ValueError("时段必须递增且星期不可重复")
        return self


class LandingSubmission(Contract):
    tenant_id: int = Field(strict=True, gt=0)
    account_id: int = Field(strict=True, gt=0)
    product_line_id: Id
    landing_page_id: Id
    expected_revision: int = Field(strict=True, ge=0)
    case_type: Literal["new_account", "new_product", "event", "page_change"]
    account_ready: bool = Field(strict=True)
    landing_url: Text
    page_content: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=50000)]
    goal: Text
    budget_cents: Money
    budget_period: Literal["daily", "total"]
    currency: Literal["CNY"]
    bid_cap_cents: Money
    regions: list[Text] = Field(min_length=1, max_length=50)
    timezone: Literal["Asia/Shanghai"]
    schedule: list[TimeSlot] = Field(min_length=1, max_length=50)
    brand_rules: Text
    negative_keywords: list[Text] = Field(max_length=1000)
    starts_at: datetime
    ends_at: datetime | None = None
    no_deadline_explicit: bool = Field(strict=True)
    link_source: Literal["email", "group"]
    authorized_scope: Text

    @field_validator("landing_url")
    @classmethod
    def url_contract(cls, value):
        try:
            u = urlsplit(value)
            valid = (u.scheme in {"http", "https"} and u.hostname and not u.username
                     and not u.password and u.port in {None, 80, 443} and not u.fragment)
            if not valid or any(c.isspace() for c in value) or "\\" in value:
                raise ValueError
            host = u.hostname.lower()
            if host == "localhost" or host.endswith((".localhost", ".local")):
                raise ValueError
            try:
                address = ip_address(host)
            except ValueError:
                address = None
            if address is not None and not address.is_global:
                raise ValueError
        except ValueError:
            raise ValueError("仅接受无凭证的HTTP(S)页面URL；不执行DNS或抓取") from None
        return value

    @model_validator(mode="after")
    def boundaries(self):
        if self.case_type == "page_change":
            raise ValueError("情况②换页未开放，阶段1b另开")
        if not self.account_ready:
            raise ValueError("须明确账户已开好")
        if self.starts_at.utcoffset() is None or (self.ends_at and self.ends_at.utcoffset() is None):
            raise ValueError("日期必须包含时区偏移")
        if self.ends_at is None:
            if not self.no_deadline_explicit or self.case_type == "event":
                raise ValueError("无截止须显式选择；活动必须有截止")
        elif self.no_deadline_explicit or self.ends_at <= self.starts_at:
            raise ValueError("截止时间须晚于开始，且不能同时选择无截止")
        return self
