"""GEO 内容域 Pydantic schemas。"""

from __future__ import annotations

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, Field


class PromptCreate(BaseModel):
    tenant_id: int
    question: str = Field(..., min_length=4, max_length=500)
    priority: int = 0
    tags: list[str] = Field(default_factory=list)
    demand_note: str | None = None
    source: Literal["manual", "import", "demo"] = "manual"
    language: str = "zh-CN"


class PromptUpdate(BaseModel):
    question: str | None = Field(None, min_length=4, max_length=500)
    priority: int | None = None
    tags: list[str] | None = None
    demand_note: str | None = None
    status: Literal["active", "archived"] | None = None


class PromptImportItem(BaseModel):
    question: str = Field(..., min_length=4, max_length=500)
    priority: int = 0
    tags: list[str] = Field(default_factory=list)
    demand_note: str | None = None


class PromptImportRequest(BaseModel):
    tenant_id: int
    items: list[PromptImportItem] = Field(..., min_length=1)


class FactCreate(BaseModel):
    tenant_id: int
    title: str = Field(..., min_length=1, max_length=200)
    statement: str = Field(..., min_length=4)
    fact_type: Literal["product", "case", "metric", "policy", "other"] = "product"
    source_name: str = Field(..., min_length=1, max_length=200)
    source_url: str | None = None
    observed_at: date | None = None
    trust_level: Literal["verified", "needs_review", "draft"] = "needs_review"
    meta: dict[str, Any] | None = None


class FactUpdate(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=200)
    statement: str | None = Field(None, min_length=4)
    fact_type: Literal["product", "case", "metric", "policy", "other"] | None = None
    source_name: str | None = Field(None, min_length=1, max_length=200)
    source_url: str | None = None
    observed_at: date | None = None
    trust_level: Literal["verified", "needs_review", "draft"] | None = None
    status: Literal["active", "archived"] | None = None
    meta: dict[str, Any] | None = None


class TaskCreate(BaseModel):
    tenant_id: int
    prompt_id: int
    title: str | None = Field(None, max_length=300)
    target_channels: list[str] = Field(default_factory=lambda: ["website", "zhihu"])
    fact_ids: list[int] = Field(default_factory=list)
    brief: dict[str, Any] | None = None


class TaskFactsUpdate(BaseModel):
    fact_ids: list[int] = Field(..., min_length=0)


class ArticleUpdate(BaseModel):
    title: str = Field(..., min_length=1)
    body_markdown: str = Field(..., min_length=1)
    outline: dict[str, Any] | None = None


class VariantsCreate(BaseModel):
    channels: list[str] = Field(default_factory=lambda: ["website", "zhihu"])


class PublicationCreate(BaseModel):
    tenant_id: int
    channel: str
    published_url: str = Field(..., min_length=8)
    note: str | None = None
