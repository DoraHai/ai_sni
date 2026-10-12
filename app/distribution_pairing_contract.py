"""One-time device bootstrap; no account, project or publication authority."""
from typing import Annotated, Literal

from pydantic import Field, StringConstraints, field_validator
from app.distribution_contract import Message, Identifier, Uuid

Millis = Annotated[int, Field(ge=0, le=4102444800000)]
Label = Annotated[str, StringConstraints(min_length=1, max_length=80)]
PairingCode = Annotated[str, StringConstraints(pattern=r'^[A-Za-z0-9_-]{32}$')]
Credential = Annotated[str, StringConstraints(pattern=r'^[A-Za-z0-9_-]{64}$')]


class PairingCreate(Message):
    label: Label
    expires_in_seconds: Annotated[int, Field(ge=60, le=600)] = 300
    request_id: Uuid

    @field_validator('label')
    @classmethod
    def printable_label(cls, value):
        if not value.strip() or any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError('Printable label required')
        return value


class PairingClaim(Message):
    pairing_code: PairingCode = Field(repr=False)
    request_id: Uuid


class PairingRevoke(Message):
    request_id: Uuid


class PairingView(Message):
    id: Uuid
    request_id: Uuid
    device_id: Identifier
    label: Label
    state: Literal['pending', 'claimed', 'expired', 'revoked']
    created_at: Millis
    expires_at: Millis
    claimed_at: Millis | None
    revoked_at: Millis | None
    automatic_submit: Literal[False] = False
    bindings_configured: Literal[False] = False


class PairingCreated(Message):
    schema: Literal[1] = Field(...)
    pairing: PairingView
    pairing_code: PairingCode = Field(repr=False)
    code_once: Literal[True]


class DeviceClaimed(Message):
    id: Identifier
    label: Label
    active: Literal[True]
    credential: Credential = Field(repr=False)
    credential_once: Literal[True]


class PairingClaimed(Message):
    schema: Literal[1] = Field(...)
    pairing_id: Uuid
    claimed_at: Millis
    device: DeviceClaimed
    bindings_configured: Literal[False] = False
    automatic_submit: Literal[False] = False


class DeviceBindingsRequest(Message):
    device_id: Identifier


class DeviceBindingView(Message):
    binding_id: Uuid
    device_id: Identifier
    module: Literal['seo', 'geo']
    tenant_id: Annotated[int, Field(gt=0)]
    scope_id: Annotated[int, Field(gt=0)]
    account_id: Identifier
    external_account_id: Identifier
    platform: Literal['wechat-article']
    login_state: Literal['unverified'] = 'unverified'


class DeviceBindingsResponse(Message):
    schema: Literal[1] = Field(...)
    device_id: Identifier
    as_of: Millis
    items: Annotated[list[DeviceBindingView], Field(max_length=50)]
    automatic_submit: Literal[False] = False
