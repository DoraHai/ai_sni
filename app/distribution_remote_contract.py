"""Remote account-window control v1; no publishing, navigation or desktop API."""
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, StringConstraints, model_validator
from app.distribution_contract import Message, Scope, Digest, Identifier, Uuid

Millis = Annotated[int, Field(ge=0, le=4102444800000)]
Nonce = Annotated[str, StringConstraints(pattern=r'^[A-Za-z0-9_-]{43}$')]
Revision = Annotated[int, Field(ge=1, le=2147483647)]


class TaskBinding(Message):
    task_id: Uuid
    grant_id: Uuid
    lease_id: Uuid
    source_revision: Identifier
    content_digest: Digest


class TaskRequest(Message):
    task_id: Uuid
    expected_source_revision: Identifier
    expected_content_digest: Digest


class SessionCreate(Scope):
    binding_id: Uuid
    purpose: Literal['account-login', 'account-verification', 'task-intervention']
    task: TaskRequest | None = None
    request_id: Uuid

    @model_validator(mode='after')
    def exact_task(self):
        if (self.purpose == 'task-intervention') != (self.task is not None):
            raise ValueError('Only task intervention requires an exact task')
        return self


class Mouse(Message):
    kind: Literal['mouse']
    event: Literal['click']
    x: Annotated[int, Field(ge=0, le=1919)]
    y: Annotated[int, Field(ge=0, le=1079)]
    button: Literal['left']


class Key(Message):
    kind: Literal['key']
    key: Literal['Enter', 'Escape', 'Tab', 'Backspace', 'Delete', 'ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown']


class Text(Message):
    kind: Literal['text']
    text: Annotated[str, StringConstraints(min_length=1, max_length=1024)]

    @model_validator(mode='after')
    def no_controls(self):
        if any(ord(c) < 32 or ord(c) == 127 for c in self.text):
            raise ValueError('Control characters are not text input')
        return self


Input = Annotated[Mouse | Key | Text, Field(discriminator='kind')]


class SessionInput(Message):
    command_id: Uuid
    control_nonce: Nonce
    frame_seq: Revision
    control_revision: Revision
    input: Input


class SessionClose(Message):
    request_id: Uuid
    control_nonce: Nonce


class DevicePoll(Message):
    device_id: Identifier


class DeviceAck(Message):
    device_id: Identifier
    session_id: Uuid
    command_id: Uuid
    command_seq: Revision
    control_revision: Revision
    state: Literal['applied', 'rejected', 'unknown']
    code: Literal['INPUT_APPLIED', 'INPUT_REJECTED', 'WINDOW_UNAVAILABLE', 'AUTHORIZATION_CHANGED',
                  'VIEWPORT_CHANGED', 'EXECUTION_UNKNOWN']

    @model_validator(mode='after')
    def corresponding_code(self):
        if ((self.state == 'applied') != (self.code == 'INPUT_APPLIED')
                or (self.state == 'unknown') != (self.code == 'EXECUTION_UNKNOWN')):
            raise ValueError('Ack state/code mismatch')
        return self


class FrameHeaders(Message):
    device_id: Identifier
    session_id: Uuid
    frame_seq: Revision
    control_revision: Revision
    viewport_width: Annotated[int, Field(ge=1, le=1920)]
    viewport_height: Annotated[int, Field(ge=1, le=1080)]
    captured_at: Millis


class FrameView(Message):
    frame_seq: Revision
    control_revision: Revision
    viewport_width: Annotated[int, Field(ge=1, le=1920)]
    viewport_height: Annotated[int, Field(ge=1, le=1080)]
    captured_at: Millis
    uploaded_at: Millis


class SessionView(Scope):
    id: Uuid
    binding_id: Uuid
    device_id: Identifier
    account_id: Identifier
    platform: Literal['wechat-article']
    purpose: Literal['account-login', 'account-verification', 'task-intervention']
    task: TaskBinding | None
    controller_user_id: Annotated[int, Field(gt=0)]
    broker_epoch: Uuid
    state: Literal['requested', 'active', 'closed', 'expired', 'failed']
    code: Annotated[str, StringConstraints(pattern=r'^[A-Z0-9_]{1,64}$')]
    expires_at: Millis
    control_revision: Revision
    frame: FrameView | None
    last_command_id: Uuid | None
    last_command_state: Literal['queued', 'delivered', 'applied', 'rejected', 'unknown', 'canceled'] | None
    automatic_submit: Literal[False] = False
    publication_verified: Literal[False] = False
