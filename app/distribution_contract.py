"""Versioned, bounded distribution messages. No client supplied approved body."""
from __future__ import annotations

import hashlib
import json
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, PositiveInt, StringConstraints, model_validator

Identifier = Annotated[str, StringConstraints(pattern=r'^[a-zA-Z0-9_-]{1,100}$')]
Digest = Annotated[str, StringConstraints(pattern=r'^[a-f0-9]{64}$')]
Module = Literal['seo', 'geo']
Platform = Literal['wechat-article', 'xiaohongshu-image']
Action = Literal['preflight', 'handoff', 'publish']
Status = Literal['queued', 'running', 'awaiting-human', 'succeeded', 'failed', 'unknown', 'canceled']
Uuid = Annotated[UUID, Field(strict=False)]


class Message(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)


class Scope(Message):
    module: Module
    tenant_id: PositiveInt
    scope_id: PositiveInt


class PublicationMonitor(Message):
    module: Module
    publication_id: PositiveInt
    basis: Literal['page-capture', 'public-text']
    state: Literal['not_queued', 'pending', 'running', 'captured', 'observed', 'failed',
                   'unreachable', 'mismatch', 'version_changed', 'unavailable']
    evidence_source: Literal['auto', 'manual', 'none']
    observed_at: Annotated[int | None, Field(ge=0, le=4102444800000)]
    next_check_at: Annotated[int | None, Field(ge=0, le=4102444800000)]
    evidence_id: PositiveInt | None
    code: Annotated[str, StringConstraints(pattern=r'^[A-Za-z0-9_]{1,64}$')]

    @model_validator(mode='after')
    def meaning(self):
        if self.basis != {'seo': 'page-capture', 'geo': 'public-text'}[self.module]:
            raise ValueError('Wrong monitor basis')
        if (self.state == 'captured' and self.module != 'seo'
            or self.state == 'observed' and self.module != 'geo'
            or self.state in ('captured', 'observed') and self.observed_at is None):
            raise ValueError('Unproven observation')
        return self


class Binding(Scope):
    device_id: Identifier
    account_id: Identifier
    external_account_id: Identifier
    platform: Platform
    confirm_account_ownership: Literal[True]


class DeviceCreate(Message):
    label: Annotated[str, StringConstraints(min_length=1, max_length=80)]


class ChannelPermission(Message):
    platform: Identifier
    content_type: Literal['article', 'image-text']
    enabled: bool
    expected_revision: Annotated[int, Field(ge=0)]
    request_id: Uuid


class ProjectChannel(Scope):
    binding_id: Uuid
    content_type: Literal['article', 'image-text']
    enabled: bool
    expected_revision: Annotated[int, Field(ge=0)]
    request_id: Uuid


class ProjectControl(Scope):
    action: Literal['start', 'pause', 'resume', 'end']
    expected_revision: Annotated[int, Field(ge=0)]
    request_id: Uuid


class HandoffPermission(Scope):
    binding_id: Uuid
    enabled: bool
    stage: Literal['preflight','handoff']
    confirm_reviewed_handoff: Literal[True]
    expected_revision: Annotated[int, Field(ge=0)]
    request_id: Uuid


class TaskCreate(Scope):
    variant_id: PositiveInt
    binding_id: Uuid
    source_revision: Identifier
    expected_digest: Digest
    action: Action
    confirm_reviewed_content: Literal[True]
    confirm_manual_publication: bool = False
    expires_in_seconds: Annotated[int, Field(ge=300, le=86400)] = 3600
    request_id: Uuid


class PublishWindow(Message):
    start: Annotated[int, Field(ge=0, le=1439)]
    end: Annotated[int, Field(ge=1, le=1440)]

    @model_validator(mode='after')
    def ordered(self):
        if self.start >= self.end: raise ValueError('Split overnight windows at midnight')
        return self


class AccountPolicy(Message):
    binding_id: Uuid
    expected_revision: Annotated[int, Field(ge=0)]
    enabled: bool
    timezone: Annotated[str, StringConstraints(min_length=1, max_length=60)]
    min_interval_seconds: Annotated[int, Field(ge=0, le=86400)]
    daily_limit: Annotated[int, Field(ge=1, le=1000)]
    windows: Annotated[list[PublishWindow], Field(min_length=1, max_length=8)]
    request_id: Uuid

    @model_validator(mode='after')
    def valid_windows(self):
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
        try: ZoneInfo(self.timezone)
        except ZoneInfoNotFoundError: raise ValueError('Unknown timezone') from None
        for a,b in zip(self.windows, self.windows[1:]):
            if a.end > b.start: raise ValueError('Windows must be sorted and disjoint')
        return self


class AccountPause(Message):
    binding_id: Uuid
    expected_revision: Annotated[int, Field(ge=1)]
    action: Literal['pause','resume']
    request_id: Uuid


class AccountRestriction(Scope):
    binding_id: Uuid
    expected_revision: Annotated[int, Field(ge=0)]
    min_interval_seconds: Annotated[int, Field(ge=0, le=86400)]
    daily_limit: Annotated[int, Field(ge=1, le=1000)]
    request_id: Uuid


class TaskResolution(Scope):
    task_id: Uuid
    outcome: Literal['not-published','published']
    confirm_platform_checked: Literal[True]
    confirm_executor_stopped: Literal[True]
    public_url: Annotated[str | None, Field(max_length=2000)] = None
    request_id: Uuid


class PublicationCheck(Scope):
    task_id: Uuid
    mode: Literal['machine', 'human']
    expected_public_url: Annotated[str, Field(min_length=1, max_length=2000)]
    confirm_public_access: bool = False
    confirm_target_account: bool = False
    confirm_approved_content: bool = False
    request_id: Uuid

    @model_validator(mode='after')
    def require_human_checks(self):
        if self.mode == 'human' and not all((self.confirm_public_access, self.confirm_target_account, self.confirm_approved_content)):
            raise ValueError('Public access, target account and complete reviewed content must be checked')
        return self


class PublicationWriteback(Scope):
    task_id: Uuid
    event_id: Uuid
    request_id: Uuid


class Receipt(Message):
    receiptId: Uuid
    sequence: Annotated[int, Field(ge=1, le=9007199254740991)]
    contractVersion: Literal[1]
    taskId: Identifier
    customerId: Identifier
    projectId: Identifier
    deviceId: Identifier
    accountId: Identifier
    platform: Platform
    contentVersion: Identifier
    contentDigest: Digest
    leaseId: Identifier
    status: Status
    code: Annotated[str, StringConstraints(pattern=r'^[A-Z][A-Z0-9_]{0,63}$')]
    at: Annotated[int, Field(ge=946684800000, le=4102444800000)]
    evidence: Literal['none', 'simulation', 'human-reported']
    publicUrl: Annotated[str | None, Field(max_length=2000)]


class Exchange(Message):
    contractVersion: Literal[1]
    deviceId: Identifier
    receipts: Annotated[list[Receipt], Field(max_length=100)]

    @model_validator(mode='after')
    def distinct_receipts(self):
        if len({r.receiptId for r in self.receipts})!=len(self.receipts) or len({
            (r.taskId,r.leaseId,r.sequence) for r in self.receipts})!=len(self.receipts):
            raise ValueError('Duplicate receipt')
        return self


class Asset(Message):
    id: Identifier
    sha256: Digest
    mediaType: Literal['image/png','image/jpeg']
    bytes: Annotated[int, Field(ge=1, le=20000000)]


class ApprovedContent(Message):
    version: Identifier
    title: Annotated[str, Field(max_length=200)]
    body: Annotated[str, Field(min_length=1,max_length=100000)]
    assets: Annotated[list[Asset], Field(max_length=20)]

    @model_validator(mode='after')
    def browser_lengths(self):
        if len(self.title.encode('utf-16-le'))//2>200 or len(self.body.encode('utf-16-le'))//2>100000 or len({a.id for a in self.assets})!=len(self.assets):
            raise ValueError('Unsupported approved content')
        return self


def content_digest(content: dict) -> str:
    """Matches Node JSON.stringify on the ordered approved-content tuple."""
    value = [content['version'], content['title'], content['body'], [
        [a['id'], a['sha256'], a['mediaType'], a['bytes']] for a in content['assets']]]
    raw = json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()


def canonical(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
