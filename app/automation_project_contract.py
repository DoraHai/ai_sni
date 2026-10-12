"""Shared SEO/GEO project controls; no module models or provider configuration."""
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictBool, model_validator

PositiveInt = Annotated[int, Field(strict=True, gt=0)]


class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid')


class Cycle(Strict):
    mode: Literal['once', 'daily', 'monthly']
    enabled: StrictBool

    @model_validator(mode='after')
    def once_is_not_recurring(self):
        if self.mode == 'once' and self.enabled:
            raise ValueError('once cannot enable future cycles')
        return self


class Limits(Strict):
    max_dispatches_per_run: int = Field(strict=True, ge=1, le=20)


class Configuration(Strict):
    task_ids: list[PositiveInt] = Field(min_length=1, max_length=20)
    operations: list[Literal['onsite_ai']] = Field(min_length=1, max_length=1)
    cycle: Cycle
    limits: Limits
    stop_condition: Literal['drafts_ready_or_blocked']
    owner_user_id: PositiveInt

    @model_validator(mode='after')
    def unique_tasks(self):
        if len(set(self.task_ids)) != len(self.task_ids):
            raise ValueError('duplicate task IDs')
        return self


SafeCode = Annotated[str, Field(pattern=r'^[a-z][a-z0-9_]{0,39}$')]
Digest = Annotated[str, Field(pattern=r'^[0-9a-f]{64}$')]


class SourceVersion(Strict):
    revision: int = Field(strict=True, ge=0)
    sha256: Digest


class SourceBinding(SourceVersion):
    kind: SafeCode
    object_id: PositiveInt


class Target(Strict):
    operation: SafeCode
    object_type: SafeCode
    object_id: PositiveInt
    source_revision: int = Field(strict=True, ge=0)
    source_hash: Digest
    variant: SafeCode | None = None


class LimitsV2(Limits):
    max_external_calls_per_run: int = Field(strict=True, ge=1, le=100)


class ConfigurationV2(Strict):
    contract_version: Literal[2]
    operations: list[SafeCode] = Field(min_length=1,max_length=20)
    targets: list[Target] = Field(min_length=1,max_length=20)
    service_plan: SourceVersion
    source_bindings: list[SourceBinding] = Field(default_factory=list,max_length=8)
    cycle: Cycle
    limits: LimitsV2
    stop_condition: Literal['drafts_ready_or_blocked']
    owner_user_id: PositiveInt

    @model_validator(mode='after')
    def consistent_targets(self):
        if len(set(self.operations))!=len(self.operations) or set(self.operations)!={t.operation for t in self.targets}:
            raise ValueError('operations must uniquely match target operations')
        identities=[(t.operation,t.object_type,t.object_id,t.variant) for t in self.targets]
        if len(identities)!=len(set(identities)):
            raise ValueError('duplicate targets')
        bindings=[(b.kind,b.object_id) for b in self.source_bindings]
        if len(bindings)!=len(set(bindings)):
            raise ValueError('duplicate source bindings')
        return self


def parse_configuration(value):
    return (ConfigurationV2 if value.get('contract_version')==2 else Configuration).model_validate(value)


class Write(Strict):
    tenant_id: PositiveInt
    request_id: UUID
    expected_version: int = Field(strict=True, ge=0)


class Configure(Write):
    configuration: Configuration | ConfigurationV2


class Control(Write):
    action: Literal['start', 'pause', 'resume', 'takeover', 'end', 'disable_cycle', 'end_project']
