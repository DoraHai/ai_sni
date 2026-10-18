"""Reviewed destructive operations; grant and credential deletion stay closed."""
DELETIONS = (
    ('DELETE', '/sites/{site_id}', '', 'seo.assets'),
    ('DELETE', '/keywords/{keyword_id}', '', 'seo.keywords'),
    ('DELETE', '/tasks/{task_id}', '', 'seo.content seo.site'),
    ('DELETE', '/workbench/executions/{task_id}', '', 'seo.content seo.site'),
    ('DELETE', '/site/reports/monthly-template', '', 'seo.site'),
    ('DELETE', '/site/publications/export-template', '', 'seo.site'),
    ('DELETE', '/site/tdk-review/template', '', 'seo.site'),
    ('POST', '/site-pages/non-html-assets/cleanup', 'tenant_id site_id dry_run page_ids', 'seo.site'),
)


def deletion_rules(rule_type):
    rows = DELETIONS + (
        ('PATCH', '/sites/{site_id}', 'name domain status', 'seo.assets'),
        ('POST', '/workbench/content-assets/{content_id}/conversation/read', 'tenant_id site_id last_read_message_id', 'seo.content'),
        ('POST', '/workbench/content-workflows/{task_id}/advance', 'tenant_id site_id publication_id', 'seo.content seo.site'),
        ('POST', '/content-distribution/connections/{connection_id}/test', '', 'seo.content'),
        ('POST', '/workbench/service-cycles/run', 'tenant_id site_id kind expected_revision request_id', 'seo.content seo.site'),
        ('POST', '/workbench/service-plan/run', 'tenant_id site_id expected_revision request_id', 'seo.content seo.site'),
        ('POST', '/workbench/executions/{task_id}/advance', 'tenant_id site_id retry_page_id explanation report_sha256 retry_analytics_source allow_incomplete_analytics', 'seo.content seo.site'),
    )
    return [rule_type(method, '/api/v1/seo' + path, frozenset(fields.split()),
                      frozenset(), tuple(permissions.split()), 'site', True)
            for method, path, fields, permissions in rows]
