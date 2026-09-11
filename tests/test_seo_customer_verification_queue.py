from datetime import datetime, timezone
from types import SimpleNamespace

from app.api.seo_cockpit import (
    backlink_queue_item,
    image_queue_item,
    page_queue_item,
    publication_queue_item,
)
from app.security.auth import _required

NOW = datetime(2026, 9, 11, tzinfo=timezone.utc)

def row(**values):
    defaults = dict(id=1, site_id=7, updated_at=NOW, created_at=NOW, checked_at=None, last_checked_at=None)
    defaults.update(values)
    return SimpleNamespace(**defaults)

def test_image_queue_requires_crawl_evidence_before_verified():
    assert image_queue_item(row(status='unverified', page_id=8, evidence={'actual_alt': ''}))['state'] == 'pending_customer_action'
    assert image_queue_item(row(status='pending', page_id=8, evidence=None))['state'] == 'pending_system_check'
    assert image_queue_item(row(status='verified', page_id=8, evidence={'actual_alt': '减速机'}))['state'] == 'verified'
    assert image_queue_item(row(status='unavailable', page_id=8, evidence={'error': 'timeout'}))['state'] == 'failed_retry'

def test_publication_url_backfill_does_not_equal_verification():
    base = dict(platform_name='知乎', adapted_title='选型指南', published_at=NOW, last_error=None)
    assert publication_queue_item(row(status='manual_required', page_url=None, link_discovery=None, **base))['state'] == 'pending_customer_action'
    assert publication_queue_item(row(status='published', page_url='https://zhuanlan.zhihu.com/p/1', link_discovery=None, **base))['state'] == 'pending_system_check'
    assert publication_queue_item(row(status='published', page_url='https://zhuanlan.zhihu.com/p/1', link_discovery={'state':'readable','found':0}, **base))['state'] == 'verified'
    assert publication_queue_item(row(status='published', page_url='https://zhuanlan.zhihu.com/p/1', link_discovery={'state':'found','found':1}, **base))['state'] == 'verified'
    assert publication_queue_item(row(status='failed', page_url=None, link_discovery=None, **base))['state'] == 'failed_retry'

def test_page_and_backlink_use_observed_state():
    assert page_queue_item(row(status='approved', url='https://example.cn/a', title='A', http_status=200, audit_score=80, issue_codes=[], last_error=None))['state'] == 'pending_customer_action'
    assert page_queue_item(row(status='implemented', url='https://example.cn/a', title='A', http_status=200, audit_score=80, issue_codes=[], last_error=None))['state'] == 'pending_system_check'
    assert page_queue_item(row(status='verified', url='https://example.cn/a', title='A', http_status=200, audit_score=100, issue_codes=[], last_error=None))['state'] == 'verified'
    link = dict(status='active', source_url='https://source.cn/a', target_url='https://example.cn/a', source_domain='source.cn')
    assert backlink_queue_item(row(verification={'state':'found'}, **link))['state'] == 'verified'
    assert backlink_queue_item(row(verification={'state':'pending'}, **link))['state'] == 'pending_system_check'
    assert backlink_queue_item(row(verification={'state':'missing'}, **link))['state'] == 'failed_retry'

def test_queue_endpoint_is_dashboard_read_only():
    assert _required('/api/v1/seo/overview/customer-verification-queue', 'GET') == ({'seo.dashboard'}, False)
