"""Server-side supplier adapter contract. No supplier transport is enabled here."""
from __future__ import annotations

from typing import Annotated, Literal
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

Identifier=Annotated[str,StringConstraints(pattern=r'^[A-Za-z0-9_-]{1,100}$')]
Digest=Annotated[str,StringConstraints(pattern=r'^[a-f0-9]{64}$')]
Uuid=Annotated[UUID,Field(strict=False)]
MinorAmount=Annotated[int,Field(ge=0,le=100_000_000)]


class Message(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True,frozen=True)


class PublishIntent(Message):
    """Derived from a current native approval, never an uploaded client article."""
    contract_version:Literal[1]=1
    module:Literal['seo','geo']
    tenant_id:Annotated[int,Field(gt=0)]
    scope_id:Annotated[int,Field(gt=0)]
    variant_id:Annotated[int,Field(gt=0)]
    source_revision:Identifier
    content_digest:Digest
    approval_id:Uuid
    channel:Literal['news-source','backlink']
    supplier_id:Identifier
    media_id:Identifier
    currency:Literal['CNY']='CNY'
    budget_limit_minor:MinorAmount
    request_id:Uuid


class BatchPlan(Message):
    """One client/project per reviewed batch; every target remains a separate order."""
    contract_version:Literal[1]=1
    batch_id:Uuid
    items:Annotated[tuple[PublishIntent,...],Field(min_length=1,max_length=100,strict=False)]

    @model_validator(mode='after')
    def one_scope(self):
        if len({(i.module,i.tenant_id,i.scope_id) for i in self.items})!=1:
            raise ValueError('API_BATCH_SCOPE_MISMATCH')
        if len({i.request_id for i in self.items})!=len(self.items):
            raise ValueError('API_DUPLICATE_REQUEST')
        targets={(i.supplier_id,i.media_id,i.channel,i.variant_id,i.source_revision,i.content_digest) for i in self.items}
        if len(targets)!=len(self.items):raise ValueError('API_DUPLICATE_TARGET')
        return self


class SupplierReceipt(Message):
    """Normalized, bounded metadata; providers must map their raw responses first."""
    contract_version:Literal[1]=1
    request_id:Uuid
    supplier_order_id:Identifier|None=None
    state:Literal['accepted','pending','published','rejected','unknown']
    code:Literal['ACCEPTED','PENDING','PUBLISHED','REJECTED','RESULT_UNKNOWN']
    source_revision:Identifier
    content_digest:Digest
    published_url:Annotated[str|None,Field(max_length=2048)]=None
    charged_minor:MinorAmount|None=None
    currency:Literal['CNY']='CNY'

    @model_validator(mode='after')
    def evidence(self):
        expected={'accepted':'ACCEPTED','pending':'PENDING','published':'PUBLISHED',
                  'rejected':'REJECTED','unknown':'RESULT_UNKNOWN'}
        if self.code!=expected[self.state]:raise ValueError('API_STATE_CODE_MISMATCH')
        if self.state in {'accepted','pending','published'} and self.supplier_order_id is None:
            raise ValueError('API_ORDER_REFERENCE_REQUIRED')
        if self.state=='published' and not self.published_url:
            raise ValueError('API_PUBLISHED_URL_REQUIRED')
        if self.state!='published' and self.published_url is not None:
            raise ValueError('API_PREMATURE_PUBLICATION_URL')
        if self.published_url:
            url=urlsplit(self.published_url)
            if (url.scheme!='https' or not url.hostname or url.username or url.password
                or url.fragment or url.port not in (None,443)
                or any(ord(c)<=32 or ord(c)==127 for c in self.published_url)):
                raise ValueError('API_PUBLICATION_URL_REJECTED')
        return self
