# Distribution execution candidate, 2026-10-12

Runtime freeze: `1e74a9812f0ef36122371151c9a9eb9af17326f1`, feature implementation `4a648a3c5baa8f7a461d32bef8c786df9d0ce1b6`. This is a **partial integration candidate**, not a delivery or real-channel acceptance. Previous controlled-runtime evidence remains historical and unchanged. Machine-readable provenance is in `DISTRIBUTION_EXECUTION_CANDIDATE_EVIDENCE_20261012.json`.

## Implemented and verified locally

One project/binding consent records preflight or human handoff permission. The bounded worker binds the exact queue, plan, draft/source version, digest, binding, canonical account, permission revision, capability digest and task in a durable execution intent. Concurrent workers cannot create duplicate intents. Existing strict v1 platforms and receipt codes remain unchanged; no automatic publish action, publication grant or publication reservation is inferred. GET remains read-only; customer delivery permissions remain separate.

Worker admissions require current native approval, project/channel/global permission, active device/binding, a current capability attestation, planned time and canonical account constraints. Device exchange, assets and receipt adoption recheck those gates. Unknown outcomes retain the account hold and are not retried. Pause preserves the existing v1 paused task envelope. A queued revoked task is canceled; an already exposed invalid task becomes unknown. Preflight success consumes only a handoff slot. HUMAN_REQUIRED keeps human handoff awaiting intervention and does not represent publication.

Planner fixes preserve attempted unknown costs even when business authorization changes, exclude existing publication tasks before the item limit, and prevent revoked bindings or active execution plans from starving bounded scans.

New advisor routes under `/api/distribution/v1`: GET `/platform-directory`, GET `/execution-progress`, POST `/handoff-permission`. The write requires native scope ownership, the current revision, request identity and `confirm_reviewed_handoff: true`; its stage is restricted to preflight/handoff. No device capability HTTP route was invented.

Candidate schema order extends the prior native/main-meter/main-controls/control/scheduling/publication/queue/planning order with `scripts/distribution_execution_schema.sql`. It creates permissions, attestations, intents, handoff slots and scan state. Apply only to a separately reviewed candidate database; no runtime or production DDL occurs. Rollback stops the worker, returns code to the previous runtime, and retains audit/task/fee history and additive tables.

## Exact MHT directory and execution boundary

Read-only MHT source commit: `f271408e12c2569557e734029c720fb7f70a8903`. Pinned fixture SHA-256: `d16ca1d08ab0eba00eef569ea014a55aa5c05f77ff443af983077338aea36136`. Git attributes preserve its exact bytes on Windows. Equality validation rejects missing/extra fields and capability promotion. **Its normalized executable stages are empty**: all channel adapters are unavailable, automaticSubmit and publicationVerified remain false. This descriptive manifest is consumed by the channel directory and never recorded as execution authorization.

| MHT channel | Frozen content types | Native central intake |
| --- | --- | --- |
| wechat-official | article | wechat-article |
| wechat-channels | video | absent |
| xiaohongshu | image-note, video | xiaohongshu-image for image-note only |
| zhihu | article, answer | absent |
| bilibili | article, video | absent |
| douyin | video | absent |
| weibo | post | absent |
| linkedin | article, post | absent |
| toutiao | article, video | absent |
| baijiahao | article, video | absent |
| kuaishou | video | absent |
| website-cms (central directory ID website) | article | reserved |

Generic reviewed-manual-handoff delivery metadata does not prove that a channel has an executable adapter. The normalized attestation store is an internal entrance exercised with explicitly synthetic attestations. Production admission remains unavailable until an authenticated, frozen executable adapter verifies its payload and device identity. The nine additional channel IDs never enter strict v1 task exchange.

## Verification and remaining work

Broad backend run: 138 passed; two HTTPS tests initially failed because the runner environment variable was omitted, then both passed with the existing independent runner configured. After the final planner query fix, planning/execution/manifest subset: 48 passed. Workbench contracts: 189 passed. Frozen distribution suite: 45 passed, including three headless browser checks. The owned PostgreSQL instance was stopped after verification. Counts overlap and must not be added. Actual SEO/GEO CLI subprocess entry proofs ran with controls and metering enabled against an empty isolated schema: no tasks, plan requests or AI usage events. These are entry smoke proofs, not full native execution proofs. Frozen build and CLI manifests bind the runtime commit and source hashes.

Remaining integration requirements: authenticated versioned executable capability intake; an explicit human handoff closure/transfer and audited unknown intervention before releasing an occupied account; combined native SEO/GEO queue-to-handoff-to-publication tests with actual metering; full acceptance against the independent MHT workflow. In particular, a HUMAN_REQUIRED or unknown handoff currently keeps its account occupied. No one-click unlock, formal publication or claimed end-to-end completion is supplied by this candidate.

No network, paid AI, real platform/account/GUI/publication, SEM funds changes, website edits, deployment, production migration, push or PR was performed. Other worktrees were read only. Historical mixed-newline worker hash discrepancy is not rewritten: old raw SHA was `2bce5d6d...`; replacing its single CRLF with LF equals the old Git blob SHA `e90377ee...`. Current evidence records raw worktree and Git blob hashes separately.
