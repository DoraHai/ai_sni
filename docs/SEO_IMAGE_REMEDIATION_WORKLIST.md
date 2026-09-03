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

Schema revision `0088_seo_image_alt_reviews` must be reviewed and applied in the
separate migration process before application release. Ordinary deployment must
continue to record `migration=not-run`.
