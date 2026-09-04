# SEO image remediation worklist

Image crawl evidence remains immutable. Human decisions and editable Alt drafts
are stored separately in `seo_image_alt_reviews`, scoped by tenant, site, page,
snapshot and image position. A new crawl therefore cannot silently approve a
different image: writes carry `expected_snapshot_id` and stale writes return 409.

The workflow is deliberately human-owned:

- program evidence identifies missing, empty, or whitespace-only Alt attributes;
- a reviewer marks each candidate as undecided, decorative, or informative;
- decorative images retain an empty Alt; informative images require an editable
  Alt draft before approval;
- approval records the real user and time, but never changes the customer site;
- the current snapshot worklist can be exported as UTF-8 CSV for implementation.

This phase does not infer image purpose or generate text with AI because the
collector stores HTML attributes but does not download or visually inspect the
image. AI suggestion requires a later, explicitly reviewed image-input flow; it
must remain draft-only and must never auto-approve or publish.

## Snapshot history and safe reuse

The page dialog can read recent evidence snapshots and their saved review counts.
Historic snapshots are read-only and remain exportable; selecting one never makes
it the writable current snapshot. A reviewer may explicitly copy approved records
from the most recent reviewed historic snapshot into the current snapshot.

Reuse is deliberately conservative. The server matches the complete stored HTML
evidence fingerprint (address attributes, srcset, semantic region, element ID,
link/role context and observed Alt state), and only copies fingerprints that are
unique in both snapshots. Existing current-snapshot records are never overwritten.
Every copied record is reset to `draft`, records its source snapshot in the note,
and requires a new human approval. The operation carries the expected current
snapshot ID, locks the page and returns 409 if a newer crawl appeared.

This enhancement reuses the 0088 table and does not add a migration, call AI,
download an image, modify the customer site or publish content.

Schema revision `0088_seo_image_alt_reviews` must be reviewed and applied in the
separate migration process before application release. Ordinary deployment must
continue to record `migration=not-run`.
