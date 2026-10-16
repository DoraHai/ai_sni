"""UTF-8 offline files only. No provider, network, scheduler or database calls."""
from __future__ import annotations

import csv
import io
import json
import re
import zipfile
from datetime import datetime, timezone
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from typing import Literal

# Gsnipers 多号通 e3c9d0b: src/shared/accounts.ts + supplemental-platforms.ts.
PLATFORMS = (
    "微信公众号", "微信视频号", "小红书创作服务平台", "知乎创作中心", "哔哩哔哩创作中心",
    "抖音创作者中心", "新浪微博", "LinkedIn 领英", "今日头条创作中心", "百家号创作中心",
    "快手创作者服务平台", "搜狐号", "网易号", "企鹅号", "一点号", "大鱼号", "简书",
    "CSDN", "掘金", "博客园", "SegmentFault（思否）", "开源中国", "什么值得买", "百度贴吧", "雪球",
)
MAX_BYTES = 2 * 1024 * 1024
MAX_ROWS = 200
ORDER_FIELDS = ("article_id", "title", "content_markdown", "material_path", "target_platform", "target_account", "scheduled_at", "source_version", "payload_hash")
RECEIPT_FIELDS = ("article_id", "platform", "account", "public_url", "published_at", "status", "source_version", "payload_hash")


def aware_time(value):
    if value is None or value == "":
        return None
    if isinstance(value, str) and not re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,6})?(?:Z|[+-]\d\d:\d\d)", value):
        raise ValueError("时间必须是带时区的 ISO 8601 日期时间")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) else value
    if not isinstance(parsed, datetime) or parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("时间必须携带时区")
    return parsed.astimezone(timezone.utc)


class Snapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")
    article_id: str = Field(pattern=r"^[1-9][0-9]{0,18}$")
    source_version: int = Field(ge=1, strict=True)
    payload_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("article_id")
    @classmethod
    def bigint(cls, value):
        if int(value) > 9223372036854775807:
            raise ValueError("稿件ID超出范围")
        return value


class Receipt(Snapshot):
    platform: str
    account: str = Field(min_length=1, max_length=120)
    public_url: str | None = Field(None, max_length=2000)
    published_at: datetime | None = None
    status: Literal["published", "failed", "unknown"]

    @field_validator("platform")
    @classmethod
    def platform_name(cls, value):
        if value not in PLATFORMS:
            raise ValueError("平台必须与多号通25渠道全名一致")
        return value

    @field_validator("account")
    @classmethod
    def account_name(cls, value):
        if value != value.strip() or any(ord(c) < 32 for c in value) or value.startswith(("=", "+", "-", "@")):
            raise ValueError("账号备注不得有首尾空格、控制字符或公式前缀")
        return value

    @field_validator("published_at", mode="before")
    @classmethod
    def timestamp(cls, value):
        return aware_time(value)

    @field_validator("public_url")
    @classmethod
    def https_url(cls, value):
        if value is None:
            return None
        try:
            parsed = urlsplit(value)
            valid = parsed.scheme == "https" and parsed.hostname and parsed.username is None and parsed.password is None
            _ = parsed.port
        except ValueError:
            valid = False
        if not valid or re.search(r"[\s\\\x00-\x1f\x7f]", value):
            raise ValueError("公开链接必须为不含账号信息的完整HTTPS地址")
        return value

    @model_validator(mode="after")
    def outcome(self):
        if self.status == "published" and (not self.public_url or self.published_at is None):
            raise ValueError("published 必须填写公开链接和发布时间")
        if self.status != "published" and (self.public_url is not None or self.published_at is not None):
            raise ValueError("failed/unknown 的公开链接与发布时间必须为空")
        return self


def parse_receipts(data: bytes, filename: str) -> list[Receipt]:
    """Reject the entire input before any write; never echo uploaded values."""
    if len(data) > MAX_BYTES:
        raise ValueError("回执文件不得超过2MiB")
    try:
        source = data.decode("utf-8-sig")
        if filename.lower().endswith(".json"):
            rows = json.loads(source)
        elif filename.lower().endswith(".csv"):
            reader = csv.DictReader(io.StringIO(source, newline=""), strict=True)
            if reader.fieldnames != list(RECEIPT_FIELDS):
                raise ValueError("CSV表头或顺序不符合回执格式")
            rows = list(reader)
            for row in rows:
                if None in row or any(v is None for v in row.values()):
                    raise ValueError("CSV行列数不一致")
                if not re.fullmatch(r"[1-9][0-9]*", row["source_version"]):
                    raise ValueError("source_version 必须为正整数")
                row["source_version"] = int(row["source_version"])
                for name in ("public_url", "published_at"):
                    row[name] = row[name] or None
        else:
            raise ValueError("回执仅支持JSON或CSV")
    except (UnicodeError, json.JSONDecodeError, csv.Error):
        raise ValueError("文件必须是有效UTF-8 JSON或CSV") from None
    if not isinstance(rows, list) or not 1 <= len(rows) <= MAX_ROWS:
        raise ValueError("回执必须为1至200行的数组")
    parsed, seen, urls = [], set(), set()
    for index, row in enumerate(rows, 1):
        try:
            receipt = Receipt.model_validate(row)
        except ValueError:
            raise ValueError(f"第{index}条回执字段无效，请按FORMAT核对类型、平台、HTTPS链接和状态") from None
        key = (receipt.article_id, receipt.platform, receipt.account)
        url_key = (receipt.article_id, receipt.public_url)
        if key in seen or (receipt.public_url and url_key in urls):
            raise ValueError(f"第{index}条回执重复")
        seen.add(key)
        urls.add(url_key)
        parsed.append(receipt)
    return parsed


def encode_csv(rows, fields):
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\r\n")
    writer.writeheader()
    for row in rows:
        # Quoting alone does not stop Excel formulas. JSON retains original text.
        writer.writerow({k: ("'" + str(row[k]) if isinstance(row.get(k), str) and row[k].lstrip().startswith(("=", "+", "-", "@")) else row.get(k)) for k in fields})
    return stream.getvalue()


def order_package(orders):
    templates = [{"article_id": r["article_id"], "platform": r["target_platform"], "account": r["target_account"],
                  "public_url": None, "published_at": None, "status": "unknown",
                  "source_version": r["source_version"], "payload_hash": r["payload_hash"]} for r in orders]
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("orders.json", json.dumps(orders, ensure_ascii=False, indent=2))
        archive.writestr("orders.csv", encode_csv(orders, ORDER_FIELDS))
        archive.writestr("receipts-template.json", json.dumps(templates, ensure_ascii=False, indent=2))
        archive.writestr("receipts-template.csv", encode_csv(templates, RECEIPT_FIELDS))
    return output.getvalue()
