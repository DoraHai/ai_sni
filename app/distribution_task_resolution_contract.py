"""Separate negative-history read protocol; never an execution/receipt grant."""
from typing import Annotated, Literal
from pydantic import Field, StringConstraints, model_validator
from app.distribution_contract import Message, Identifier, Digest, Platform

CanonicalUuid = Annotated[str, StringConstraints(pattern=r'^[a-f0-9]{8}-[a-f0-9]{4}-[1-5][a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$')]
Timestamp = Annotated[int, Field(ge=946684800000, le=4102444800000)]


class TaskResolutionRead(Message):
    resolutionVersion: Literal[1]
    deviceId: Identifier
    taskId: CanonicalUuid
    grantId: CanonicalUuid
    publicationGrantId: CanonicalUuid
    leaseId: CanonicalUuid
    customerId: Identifier
    projectId: Identifier
    accountId: Identifier
    platform: Platform
    contentVersion: Identifier
    contentDigest: Digest

    @model_validator(mode='before')
    @classmethod
    def strict_version(cls, value):
        if isinstance(value, dict) and type(value.get('resolutionVersion')) is not int:
            raise ValueError('Integer resolutionVersion required')
        return value


class NegativeTaskResolution(Message):
    id: Annotated[int, Field(ge=1, le=2**53-1)]
    outcome: Literal['not-published']
    checkedAt: Timestamp
    evidence: Literal['advisor-reported']


class TaskResolutionReadView(TaskResolutionRead):
    asOf: Timestamp
    resolution: NegativeTaskResolution | None
    publicationVerified: Literal[False]
    executionAuthorized: Literal[False]

    @model_validator(mode='after')
    def ordered_evidence(self):
        if self.resolution is not None and self.resolution.checkedAt > self.asOf:
            raise ValueError('Stored evidence cannot be newer than this read')
        return self
