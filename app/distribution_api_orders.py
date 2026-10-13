"""Pure order admission/receipt rules. No network, keys, or native writeback.

A future durable worker must commit its claim before calling a registered,
reviewed supplier. This module cannot submit or declare an article indexed.
"""
from dataclasses import dataclass
from typing import Literal

from app.distribution_api_contract import PublishIntent,SupplierReceipt


class SupplierOrderError(ValueError):
    """Fixed codes only; never wrap raw supplier errors or response bodies."""


@dataclass(frozen=True)
class CurrentAuthorization:
    module:str
    tenant_id:int
    scope_id:int
    variant_id:int
    source_revision:str
    content_digest:str
    approval_id:str
    channel:str
    supplier_id:str
    project_running:bool
    current_advisor:bool
    supplier_enabled:bool
    channel_enabled:bool
    adapter_verified:bool
    approved_media_id:str
    available_budget_minor:int


def admit(intent:PublishIntent,current:CurrentAuthorization,quote_minor:int)->None:
    """Require fresh authoritative scope, approval, channel and budget proof."""
    keys=('module','tenant_id','scope_id','variant_id','source_revision','content_digest','channel','supplier_id')
    if any(getattr(intent,k)!=getattr(current,k) for k in keys) or str(intent.approval_id)!=current.approval_id:
        raise SupplierOrderError('API_SOURCE_OR_SCOPE_CHANGED')
    if not all(flag is True for flag in (current.project_running,current.current_advisor,current.supplier_enabled,
                current.channel_enabled,current.adapter_verified)):
        raise SupplierOrderError('API_AUTHORIZATION_UNAVAILABLE')
    if intent.media_id!=current.approved_media_id:raise SupplierOrderError('API_MEDIA_NOT_APPROVED')
    if (type(quote_minor) is not int or quote_minor<0 or type(current.available_budget_minor) is not int
        or current.available_budget_minor<0 or quote_minor>min(intent.budget_limit_minor,current.available_budget_minor)):
        raise SupplierOrderError('API_BUDGET_EXCEEDED')


def match_receipt(intent:PublishIntent,receipt:SupplierReceipt,*,existing_order_id:str|None,
                  approved_publication_hosts:frozenset[str])->None:
    if (receipt.request_id!=intent.request_id or receipt.source_revision!=intent.source_revision
        or receipt.content_digest!=intent.content_digest):
        raise SupplierOrderError('API_RECEIPT_MISMATCH')
    if existing_order_id is not None and receipt.supplier_order_id!=existing_order_id:
        raise SupplierOrderError('API_ORDER_REFERENCE_CHANGED')
    if receipt.published_url:
        from urllib.parse import urlsplit
        host=urlsplit(receipt.published_url).hostname
        if host not in approved_publication_hosts:raise SupplierOrderError('API_PUBLICATION_HOST_NOT_APPROVED')
    # Actual cost may exceed an estimate: keep the real charge, surface it, and
    # block more work at the budget layer. Never rewrite it to an approved cap.


def next_state(current:Literal['ready','submitting','accepted','pending','published','rejected','unknown','canceled'],
               event:Literal['begin-submit','accepted','pending','published','rejected','unknown','cancel'])->str:
    allowed={
        'ready':{'begin-submit':'submitting','cancel':'canceled'},
        'submitting':{'accepted':'accepted','pending':'pending','published':'published','rejected':'rejected','unknown':'unknown'},
        'accepted':{'accepted':'accepted','pending':'pending','published':'published','rejected':'rejected','unknown':'unknown'},
        'pending':{'accepted':'pending','pending':'pending','published':'published','rejected':'rejected','unknown':'unknown'},
        # Unknown can only be resolved by matching query evidence, never submit.
        'unknown':{'accepted':'accepted','pending':'pending','published':'published','rejected':'rejected','unknown':'unknown'},
        'published':{'published':'published'},'rejected':{'rejected':'rejected'},'canceled':{}
    }
    result=allowed[current].get(event)
    if result is None:raise SupplierOrderError('API_ORDER_TRANSITION_REJECTED')
    return result


def recovery_action(state:str,*,supplier_order_id:str|None,lookup_by_request_id:bool=False)->str:
    if state in {'submitting','unknown'}:
        return 'query-order' if supplier_order_id or lookup_by_request_id else 'advisor-investigation'
    if state in {'accepted','pending'}:return 'query-order'
    return 'none'


def directory():
    return [{'channel':channel,'platform_id':channel,
             'label':{'news-source':'新闻源接口发布','backlink':'外链接口发布'}[channel],
             'content_types':['article'],'v1_platform':None,'native_intake':False,
             'real_channel_verified':False,'status':'not-integrated',
             'missing':['尚未选择供应商','原生渠道稿与审批接线','接口与真实发布验收'],
             'execution_type':'server-api','configured':False,
             'adapter_verified':False,'automatic_publish':False,'reason':'SUPPLIER_NOT_CONNECTED'}
            for channel in ('news-source','backlink')]
