# SEO publication and page-check evidence contract

This contract is the phase-one, read-only bridge from SEO publication records to
stored page-check evidence. It does not publish content, crawl a page, refresh a
task, or infer that search performance improved.

## Request

`GET /api/v1/seo/workbench/publication-page-evidence`

Required query parameters are `tenant_id` and `site_id`. Optional `content_id`
and `publication_id` filters are combined with AND. `page` starts at 1;
`page_size` defaults to 20 and is limited to 100. The authenticated identity
must belong to the tenant, have both `seo.content` and `seo.site` view access, and the
tenant must have an available SEO module. The site must belong to that tenant.

The endpoint returns only stored rows from `seo_content_assets`,
`seo_content_publications`, `seo_publish_attempts`, `seo_site_pages`, and
`seo_page_snapshots`. Reading it has no collection or write side effect.

## URL association rule

A publication is associated with a page only when exactly one page in the same
tenant and site has the same normalized URL. Normalization is deliberately
limited:

- lowercase the HTTP/HTTPS scheme and host;
- remove port 80 for HTTP and port 443 for HTTPS;
- ignore the fragment;
- retain the path exactly, including an empty path, a trailing slash, path
  escapes, and letter case;
- retain the complete query exactly, including parameter order, repeated
  parameters, blank values, and escape spelling;
- retain every non-default port.

Malformed URLs, credentials in URLs, and non-HTTP schemes are not eligible.
Title, keyword, similar path, canonical URL, query reordering, trailing-slash
guessing, and newest page are never used as fallback associations. A future
canonical or redirect evidence source may establish additional equivalence,
but this endpoint does not infer it from the current rows.

`association_status` has these values:

- `exact_unique`: one normalized URL match; page evidence may be returned.
- `no_match`: no match or the publication URL cannot be safely normalized.
- `multiple_matches`: more than one normalized match; candidates are returned,
  but none is selected.
- `publication_url_missing`: the publication has no public URL.
- `page_inventory_incomplete`: the site has more than 5,000 stored pages, so a
  unique result cannot be proven from the bounded read.

Candidate summaries are limited to five. `candidate_count` is `null` when page
inventory coverage is incomplete.

## Evidence and dates

Publication state, latest attempt state, and page-check state are separate.
`published` does not mean the page was crawled successfully; a successful page
check does not mean the article gained search traffic.

For a unique page, the latest stored snapshot is selected by `fetched_at`, then
snapshot ID. Crawl outcome, HTTP observation, body observation, link counts, and
image-alt summary have separate response objects. Link coverage is
`counts_only`; the snapshot does not embed individual link edges. Missing
snapshots and crawl failures carry explicit `coverage` and `reason` values.

Application action times such as `published_at` are UTC instants. Database
generated `created_at`, `updated_at`, `started_at`, and snapshot `fetched_at`
retain the database wall-clock convention with an explicit `+08:00` offset.
`read_at` is generated in UTC for this response.

## Example

```json
{
  "tenant_id": 7,
  "site_id": 9,
  "page": 1,
  "page_size": 20,
  "total": 1,
  "read_at": "2026-09-07T12:00:00Z",
  "coverage": {
    "state": "complete",
    "returned_publications": 1,
    "association_counts": {"exact_unique": 1}
  },
  "items": [
    {
      "content": {"id": 31, "site_id": 9, "title": "Example", "status": "approved"},
      "publication": {
        "id": 51,
        "platform_code": "zhihu",
        "status": "published",
        "public_url": "https://example.com/article?from=seo"
      },
      "latest_attempt": {"id": 61, "action": "publish", "status": "succeeded"},
      "page_association": {
        "association_status": "exact_unique",
        "normalized_publication_url": "https://example.com/article?from=seo",
        "candidate_count": 1
      },
      "page_check": {
        "source": "seo_page_snapshots",
        "coverage": "available",
        "fetched_at": "2026-09-07T19:55:00+08:00",
        "crawl": {"snapshot_id": 71, "fetch_error": null},
        "http": {"status_code": 200},
        "body": {"main_content_extractable": true, "indexable": true},
        "links": {"coverage": "counts_only", "internal_count": 8, "external_count": 2},
        "images": {"coverage": "summary", "count": 4, "missing_alt_count": 0}
      }
    }
  ],
  "read_only": true
}
```

An empty `items` array with `total: 0` is an authorized empty result. Tenant,
module, permission, and site failures use the existing 403/404 SEO error
contracts and never fall back to another tenant or site.
