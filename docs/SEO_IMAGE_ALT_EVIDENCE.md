# Image Alt evidence

Scope: static HTML evidence only. No AI calls, image downloads, customer-page
writes, publication actions, new schedules, or automated semantic judgments.

## Data and UI

- `analyze_html` records a bounded JSON object on each new successful HTML
  snapshot. Counts separate absent `alt`, empty `alt=""`, and whitespace-only
  values. Existing combined count and scoring remain unchanged in this slice.
- Each candidate includes its image occurrence number, nearest semantic region,
  element ID, address attribute, optional srcset, link context, and declared role.
  Repeated images are separate occurrences. At most 200 candidates are stored;
  total counts remain complete and the UI explicitly indicates truncation.
- Addresses are text evidence, not verified URLs or the browser's selected
  resource. No preview, clickable link, `v-html`, or external-resource request is
  created by the new dialog. Long addresses/srcsets are bounded and labeled.
- The read-only `GET /api/v1/seo/site-pages/image-evidence` requires tenant/site,
  page ownership, SEO subscription (parent router), and `seo.site` view access.
  It returns the newest matching snapshot, not an older successful fallback.
- In the site diagnostics panel, use **图片 Alt 明细**. Refresh reads stored
  observations only. Missing historic evidence is unknown, not zero. Failed
  snapshots and empty successful observations have distinct explanations.
- Collection excludes the crawler's removed inactive/script/SVG subtrees; it
  does not execute JavaScript. No claim of full browser-rendered image coverage.
- Empty Alt and `role=presentation` are not definitive evidence of decorative
  intent. Product owners/editors must determine semantics before changes.

## Schema and release boundary

Prepared revision: `0087_seo_image_alt_evidence`; one nullable JSONB column on
`seo_page_snapshots`, no backfill, no data rewrite. NULL means never recorded.
Existing successful rows are not retroactively upgraded to zero candidates.

This is NOT a frontend-only release. Do not deploy code requiring this field
before separately reviewing and authorizing its database migration. The normal
SEO workflow must continue recording `migration=not-run`; no deployment script
was changed to apply schema automatically. Health and CI require the new head.

Development starts from main (`0085_seo_page_index_reviews`). Production has
the additional `0086_seo_index_review_merge` head. During the independent
production promotion PR, reconcile the 0087 parent to the approved production
head, preserving its lineage, then revalidate a single head and upgrade plan.
Do not ship the main migration graph directly into production or stamp past it.
Recheck the production crawler's snapshot construction and pinned transport;
do not replace its newer runtime code with main's older implementation.

DB revision changes also affect strict health checks on an old app release.
Before migration approval, plan the deployment/rollback window and verify the
old/new application's schema checks; do not assume an additive column alone
guarantees health-check compatibility. A downgrade drops evidence, so a rollback
must preserve newly collected evidence or receive explicit deletion approval.

## Acceptance

Offline cases: missing/empty/whitespace; repeated assets; lazy attributes/base URL;
unsupported or credential-bearing URL; malformed base; long/capped results;
historic/empty/failed observations; tenant/page scoping; late response after
switch/close/unmount; filter; error/retry; timezone; ORM field; offline DDL.

After authorized migration and SEO deployment, first confirm old records show
“未记录逐图明细”. Then use one separately authorized crawl against a controlled
fixture site to verify database persistence and the new dialog after refresh.
Do not trigger a NORD crawl or alter task #10/#11 to obtain acceptance data.

The local migration test emits PostgreSQL DDL without a connection. The existing
real-PostgreSQL migration test remains required in CI; it is not replaced by the
offline test and must not use a production database.
