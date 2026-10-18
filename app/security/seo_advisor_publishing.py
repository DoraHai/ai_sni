"""Exact operational publishing routes. Connection/authorization edits stay shut."""
PUBLISHING = (
    ('POST', '/content-assets/offline-handoff/export', 'tenant_id site_id articles target_platform target_account scheduled_at'),
    ('POST', '/content-assets/offline-handoff/import-receipts', ''),
    ('POST', '/content-assets/import-published-links', ''),
    ('POST', '/content-distribution/preflight', 'tenant_id site_id content_ids connection_ids action'),
    ('POST', '/content-distribution/publish', 'tenant_id site_id content_id connection_id action confirm variant_id source_version adapted_title adapted_content'),
    ('POST', '/content-distribution/publications/manual', 'tenant_id site_id content_id platform_name page_url published_at source_version payload_hash'),
    ('POST', '/content-distribution/publications/{publication_id}/complete', 'tenant_id site_id page_url published_at source_version'),
    ('POST', '/content-distribution/publications/{publication_id}/sync', ''),
    ('POST', '/content-distribution/publications/{publication_id}/retry', 'tenant_id site_id confirm manual_check_outcome'),
    ('POST', '/content-distribution/publications/{publication_id}/materials', 'tenant_id site_id source_version'),
    ('POST', '/qa/placements/{placement_id}/receipt', 'tenant_id site_id version answer_url'),
    ('POST', '/qa/placements/{placement_id}/assistant-receipt', 'tenant_id site_id version answer_url kind schema_version placement_id content_version platform question_url'),
    ('POST', '/content-distribution/video/upload', 'tenant_id site_id connection_id content_id source_version request_id title'),
    ('POST', '/content-distribution/video/publications/{publication_id}/publish', 'tenant_id site_id connection_id confirmed'),
    ('POST', '/content-distribution/video/publications/{publication_id}/recover', 'tenant_id site_id connection_id item_id'),
    ('POST', '/content-distribution/video/publications/{publication_id}/sync', 'tenant_id site_id connection_id'),
)


def publishing_rules(rule_type):
    return [rule_type(method, '/api/v1/seo' + path, frozenset(fields.split()),
                      frozenset(), ('seo.content',), 'site', True)
            for method, path, fields in PUBLISHING]
