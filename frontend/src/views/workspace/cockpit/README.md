# Workbench UI components

`MetricEvidenceCard.vue` renders data already validated and formatted by a module
adapter. It is not yet mounted on a route. Visual/browser acceptance remains pending.

The host passes an immutable `metric` with contextRevision, id, state, moduleLabel, label, display,
unit, periodLabel, sourceLabel, updatedLabel, optional changeLabel/reason, series
(`{label,value,display}`), and detail columns/rows. `null` samples create gaps rather
than zeroes or interpolated lines. Column values must already be presentation text.
Unknown source/period/time remains explicitly unknown.

On refresh, revocation or client invalidation, immediately replace the metric with
an empty/loading/denied value and remove its prior display, series and rows. Change
`contextRevision` on tenant/user/permission change; it closes open detail dialogs.
The metric's own contextRevision must strictly equal the current prop; otherwise
the component renders only a neutral loading placeholder with no old data or actions.
The `discuss` event carries only metricId and contextRevision, never cached evidence
or credentials. Revalidate those references against current context before adding
them to a conversation. The host also clears already copied conversation evidence.

The card does not call an AI, run an instruction or fetch any URL. Its retry event
may only be wired to the already-authorized read. Do not show unverified estimates
as confirmed changes, totals or customer inquiries.
