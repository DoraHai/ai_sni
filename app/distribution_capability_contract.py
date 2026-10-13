"""Capability registration protocol; separate from strict execution contract v1."""
from typing import Annotated, Literal
from pydantic import Field, model_validator
from app.distribution_contract import Message, Identifier, Digest, Uuid, Receipt, Scope, Platform


class CapabilityRegistration(Message):
    capabilityVersion: Literal[1]
    deviceId: Identifier
    adapterVersion: Literal['reviewed-manual-handoff-v1']
    manifestDigest: Digest
    manifest: dict
    bindingIds: Annotated[list[Uuid], Field(min_length=1, max_length=100)]
    expiresAt: Annotated[int, Field(ge=946684800000, le=4102444800000)]
    expectedRevision: Annotated[int, Field(ge=0)]
    requestId: Uuid

    @model_validator(mode='after')
    def unique_bindings(self):
        if len(set(self.bindingIds)) != len(self.bindingIds):
            raise ValueError('Duplicate binding')
        return self


class CapabilityRevocation(Message):
    capabilityVersion: Literal[1]
    deviceId: Identifier
    expectedRevision: Annotated[int, Field(ge=1)]
    requestId: Uuid


class HandoffReceipt(Message):
    handoffVersion: Literal[1]
    deviceId: Identifier
    grantId: Identifier
    receipt: Receipt


class HandoffInvestigation(Scope):
    task_id: Uuid
    source_revision: Identifier
    content_digest: Digest
    outcome: Literal['not-published']
    confirm_platform_checked: Literal[True]
    confirm_executor_stopped: Literal[True]
    confirm_no_publication: Literal[True]
    request_id: Uuid


class HandoffRetry(Scope):
    task_id: Uuid
    source_revision: Identifier
    content_digest: Digest
    confirm_executor_stopped: Literal[True]
    confirm_no_publication: Literal[True]
    request_id: Uuid


class HandoffResolutionRead(Message):
    handoffVersion: Literal[1]
    deviceId: Identifier
    taskId: Identifier
    grantId: Identifier
    leaseId: Identifier
    customerId: Identifier
    projectId: Identifier
    accountId: Identifier
    platform: Platform
    contentVersion: Identifier
    contentDigest: Digest
