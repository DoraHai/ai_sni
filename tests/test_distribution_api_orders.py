"""Focused contract safety tests; no actual supplier, DB, AI, or publication calls."""
from dataclasses import replace
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.distribution_api_contract import BatchPlan,PublishIntent,SupplierReceipt
from app.distribution_api_orders import CurrentAuthorization,SupplierOrderError,admit,match_receipt,next_state,recovery_action,directory


def intent(**change):
    return PublishIntent.model_validate({'module':'seo','tenant_id':15,'scope_id':6,'variant_id':1,
        'source_revision':'v4','content_digest':'a'*64,'approval_id':str(uuid4()),
        'channel':'news-source','supplier_id':'supplier-test','media_id':'media-test',
        'budget_limit_minor':10000,'request_id':str(uuid4()),**change})


def authorization(i):
    return CurrentAuthorization(i.module,i.tenant_id,i.scope_id,i.variant_id,i.source_revision,
        i.content_digest,str(i.approval_id),i.channel,i.supplier_id,True,True,True,True,True,i.media_id,10000)


def receipt(i,**change):
    return SupplierReceipt.model_validate({'request_id':str(i.request_id),'supplier_order_id':'order-test',
        'state':'accepted','code':'ACCEPTED','source_revision':i.source_revision,'content_digest':i.content_digest,**change})


def test_batch_mixed_clients_and_duplicate_targets_rejected():
    i=intent();j=intent(tenant_id=16)
    with pytest.raises(ValidationError):BatchPlan(batch_id=uuid4(),items=[i,j])
    with pytest.raises(ValidationError):BatchPlan(batch_id=uuid4(),items=[i,i])
    same=i.model_copy(update={'request_id':uuid4()})
    with pytest.raises(ValidationError):BatchPlan(batch_id=uuid4(),items=[i,same])
    other=i.model_copy(update={'media_id':'another-media','request_id':uuid4()})
    assert len(BatchPlan(batch_id=uuid4(),items=[i,other]).items)==2
    assert isinstance(BatchPlan(batch_id=uuid4(),items=[i,other]).items,tuple)


@pytest.mark.parametrize('key,value',[('module','sem'),('tenant_id',True),('budget_limit_minor',-1),
    ('channel','wechat-article'),('source_revision','https://example.invalid/')])
def test_invalid_intent(key,value):
    with pytest.raises(ValidationError):intent(**{key:value})


@pytest.mark.parametrize('change',[{'tenant_id':16},{'scope_id':7},{'source_revision':'v5'},
    {'content_digest':'b'*64},{'approval_id':str(uuid4())},{'project_running':False},
    {'current_advisor':False},{'supplier_enabled':False},{'channel_enabled':False},
    {'adapter_verified':False},{'approved_media_id':'other'}, {'supplier_id':'other-supplier'},
    {'channel':'backlink'},{'supplier_enabled':'false'}])
def test_fresh_authority_required(change):
    i=intent();c=authorization(i)
    admit(i,c,1000)
    with pytest.raises(SupplierOrderError):admit(i,replace(c,**change),1000)


def test_budget_amounts_are_minor_integer_units():
    i=intent();c=authorization(i)
    for quote in (True,10001,-1,1.5):
        with pytest.raises(SupplierOrderError):admit(i,c,quote)
    with pytest.raises(SupplierOrderError):admit(i,replace(c,available_budget_minor=50),51)


def test_acceptance_is_not_publication_and_unknown_does_not_resubmit():
    assert next_state('ready','begin-submit')=='submitting'
    assert next_state('submitting','accepted')=='accepted'
    assert next_state('submitting','unknown')=='unknown'
    for state in ('submitting','accepted','pending','unknown','published','rejected'):
        with pytest.raises(SupplierOrderError):next_state(state,'begin-submit')
    assert recovery_action('unknown',supplier_order_id=None)=='advisor-investigation'
    assert recovery_action('submitting',supplier_order_id=None,lookup_by_request_id=True)=='query-order'
    assert recovery_action('unknown',supplier_order_id='order-test')=='query-order'


def test_only_current_order_and_source_can_resolve_unknown():
    i=intent();r=receipt(i,state='published',code='PUBLISHED',published_url='https://media.example/article/1',charged_minor=11000)
    match_receipt(i,r,existing_order_id='order-test',approved_publication_hosts=frozenset({'media.example'}))
    assert next_state('unknown',r.state)=='published'
    assert r.charged_minor==11000
    for wrong in [r.model_copy(update={'request_id':uuid4()}),r.model_copy(update={'source_revision':'v5'}),
                  r.model_copy(update={'content_digest':'b'*64})]:
        with pytest.raises(SupplierOrderError):match_receipt(i,wrong,existing_order_id='order-test',approved_publication_hosts=frozenset({'media.example'}))
    with pytest.raises(SupplierOrderError):match_receipt(i,r,existing_order_id='different-order',approved_publication_hosts=frozenset({'media.example'}))
    with pytest.raises(SupplierOrderError):match_receipt(i,r,existing_order_id='order-test',approved_publication_hosts=frozenset({'other.example'}))


def test_receipt_privacy_shape_and_missing_publication_evidence():
    i=intent()
    for change in ({'state':'published','code':'PUBLISHED'},
                   {'state':'pending','code':'PUBLISHED'},
                   {'published_url':'https://media.example/article/1'},
                   {'supplier_order_id':None},{'credential':'SECRET'}):
        with pytest.raises(ValidationError):receipt(i,**change)
    r=receipt(i);assert r.charged_minor is None and r.published_url is None


def test_unconfigured_channels_do_not_grant_automatic_publication():
    assert all(not row['configured'] and not row['adapter_verified'] and not row['automatic_publish'] for row in directory())
