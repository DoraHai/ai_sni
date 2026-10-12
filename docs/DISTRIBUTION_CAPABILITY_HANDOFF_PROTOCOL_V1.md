# Authenticated manual delivery and handoff protocol

This protocol is independent of strict `/api/distribution/v1/device/exchange`. Existing task shapes, platform enums, receipt codes and published meaning are unchanged. It admits package preparation for two existing v1 platforms, not a real publisher, account identity verification or automatic submission. HTTPS and the already paired device Bearer token are required by the device transport. Credentials stay outside fixtures, request bodies, audit records and output.

## Registration

`POST /api/distribution/capabilities/v1/device/register`

Exact request keys: `capabilityVersion: 1`, `deviceId`, `adapterVersion: "reviewed-manual-handoff-v1"`, `manifestDigest`, complete `manifest`, `bindingIds` (1–100 unique UUIDs), `expiresAt` (milliseconds, future and at most 24 hours), `expectedRevision` (0 initially), `requestId` (UUID). No stages are accepted from the client. The full manifest must structurally equal the frozen fixture; its advertised publisher remains unavailable. Only deliveryAvailable=true + an existing v1Platform admits the fixed preflight/handoff stages, and only for active bindings belonging to the authenticated device. Project owner, source approval, handoff consent, channel/global permission, binding/device activity, canonical account policy and fresh expiry are checked again at dispatch and adoption.

Response: `capabilityVersion`, `deviceId`, `registrationId`, `revision`, `manifestDigest`, `attestationDigest`, `expiresAt`, `active`, `allowedBindings: [{bindingId, platform, stages:["preflight","handoff"]}]`, `automaticSubmit:false`, `publicationVerified:false`.

Shared fixture: `docs/fixtures/distribution-capability-registration-v1.json`, SHA-256 `b6a00e07905cc80f9b61fb8b4005cdd86ceac4dd86e5b878241397e0296fcbe8`. Replace synthetic IDs, expiry and request ID at runtime. Frozen MHT manifest SHA-256 is `d16ca1d08ab0eba00eef569ea014a55aa5c05f77ff443af983077338aea36136`, source commit `f271408e12c2569557e734029c720fb7f70a8903` (capability directory freeze `4705937312a765e72351e876ff1d783ae8fecfe7`).

Same device/request ID and identical request returns its original response without extending expiry or reactivating a revoked registration. Conflicting content returns 409. Fresh request ID + current revision renews; unchanged active proof/bindings keeps registration and attestation identity so active tasks are not invalidated merely by renewal. Changed bindings or registration after revocation gets a new identity, fences older task proof and never revives an old attempt. Expired proof cannot dispatch until valid renewal. Device or binding revocation still independently blocks tasks even if a historical registration response was acknowledged.

`POST /api/distribution/capabilities/v1/device/revoke`: exact request `capabilityVersion:1, deviceId, expectedRevision, requestId`. Response uses the same projection, active false and no allowedBindings. Revoke invalidates attestations; unexposed queued tasks are canceled/released when fenced, exposed attempts become unknown/held. `GET /api/distribution/capabilities/v1/device/{deviceId}/status` returns `capabilityVersion:1, deviceId, registration` (null if absent), with current revision and expiry. It is read-only and requires that device's token; query parameters are not accepted. Registration active is the saved state; callers must also compare expiry and current binding authority.

## Normal handoff closure

`POST /api/distribution/handoff/v1/device/receipt`

Exact request: `handoffVersion:1`, `deviceId`, `grantId`, `receipt` with the original receipt object fields. Device transport must route the following auxiliary human codes here, excluding them from strict v1 exchange batches. Do not send the same code to both endpoints.

| Code | Receipt status | Required current state | Result |
| --- | --- | --- | --- |
| HUMAN_HANDOFF_ACCEPTED | succeeded | awaiting-human / HUMAN_REQUIRED | HANDOFF_COMPLETE |
| HUMAN_INTERVENTION_COMPLETED | canceled | awaiting-human / LOGIN_REQUIRED or CAPTCHA | HANDOFF_TERMINATED |
| HUMAN_INVESTIGATED_FAILURE | failed | awaiting-human | HANDOFF_TERMINATED |

All require evidence human-reported and publicUrl null. Exact device/customer/project/account/platform/source revision/digest/grant/lease are pinned. A fresh increasing sequence, current native approval/owner, running project, source content, active binding/device, current consent/capability and unexpired grant/lease are required. The login/CAPTCHA pause permits closing that human node; it does not clear the account risk pause or allow a subsequent publish. The superadmin must explicitly restore the account policy before new work. Unknown is rejected with `handoff_investigation_required`; it is never released by a device normal closure.

Response: `handoffVersion:1`, `receiptAck` using the six original acknowledgement keys, `result` as above, `publicationVerified:false`. Identical receipt ID or task/lease/sequence and identical full payload is acknowledged once; conflicting payload returns 409. Completion consumes a handoff slot and termination releases it. Neither writes publication evidence, native publication status, a publication grant or a publish reservation. Historical task association is retained.

Shared fixture: `docs/fixtures/distribution-handoff-receipt-v1.json`, SHA-256 `f9ed7b8fa151ba560f6c76c97ddd17cf70e488b24e4571b48ad67896bc337a29`.

## Advisor investigation and bounded retry

`POST /api/distribution/handoff/v1/advisor/resolution` uses current named advisor JWT and native scope ownership, independent of the expired/revoked execution grant. Exact request: module/tenant_id/scope_id, task_id, source_revision, content_digest, outcome:"not-published", confirm_platform_checked:true, confirm_executor_stopped:true, confirm_no_publication:true, request_id. It accepts an old unknown handoff or a leased/running/awaiting-human handoff whose grant or lease has expired, with its exact stored version/digest. The latter is first fenced unknown and audited inside the write transaction. No device exchange is required; GET `/tasks` only describes `handoff_investigable` and never fences or releases anything. An unexpired normal awaiting-human task is rejected. The current owner must have native scope authority. It can investigate after execution/device revocation or later source editing, but does not grant execution or verify a public publication. Audit/resolution is append-only. It terminates the old task as failed/revoked and releases its slot only after these explicit negative-publication confirmations. Response: handoffVersion:1, task_id, outcome:"not-published", checked_at, evidence:"advisor-reported", result:"HANDOFF_NOT_PUBLISHED", publicationVerified:false.

`POST /api/distribution/handoff/v1/advisor/retry` request uses the same fixed scope/task/version/digest, confirm_executor_stopped:true, confirm_no_publication:true and request_id. It accepts only canceled/failed linked handoffs; unknown requires investigation first. Current owner, running project, handoff consent, unchanged queue/version/binding, a due planned suggestion, current native source/capability and account policy must still pass. A blocked old advisory plan may need the normal worker to produce a fresh plan after the account is restored. Success creates a fresh task/grant/lease and execution intent, linked append-only to the prior intent. Maximum three attempts per exact queue/source/digest/stage. It never deletes old attempts or automatically retries a failed/unknown result. Identical advisor request ID is idempotent. Response: handoffVersion:1, task_id (new), previous_task_id, attempt (2 or 3), result:"HANDOFF_REDISPATCHED", publicationVerified:false.

Advisor UI requires separate confirmation checkboxes for investigation and retry, fixed current task metadata, current-owner/busy gates, and rejects stale replies when session/scope changes. Published handoff completion is never inferred. No website/video/post/answer task is added to strict v1.

## Device resolution synchronization

`POST /api/distribution/handoff/v1/device/resolution` is an independently versioned read operation with device Bearer authentication and no query parameters. Exact request keys: handoffVersion:1, deviceId, taskId, grantId, leaseId, customerId, projectId, accountId, platform, contentVersion, contentDigest. All must equal the original stored handoff task; the project target follows the actual envelope (for example seo-19), not the bare native scope number.

The active original device and binding, exact target/scope, current project owner and native scope authority are rechecked in device→scope→canonical account→native entitlement lock order. The old execution grant/lease need not remain unexpired: this is narrowly authorized reading of a historical negative investigation, not execution. Revoked devices/bindings and reassigned scope ownership are denied; no historical-binding read override is introduced. Caller identity cannot select another device's task even with guessed task/version/digest values. Later source editing does not alter the immutable investigated version.

Response echoes all request keys and adds resolution:null if no explicit central investigation exists, or resolution:{id, outcome:"not-published", checkedAt, evidence:"advisor-reported"}. It always returns publicationVerified:false. A non-null proof must match the immutable resolution/task version and digest, and the central old task must be failed/revoked after investigation. Grant withdrawal, ordinary canceled/failed status and normal handoff completion alone never produce this proof. Repeated reads return the same proof without modifying any task, receipt, slot or audit. The device must validate the entire echoed tuple and persist the proof separately before treating the old unknown/awaiting-human lane as cleared; its original unknown receipt/audit remains unchanged. A fresh retry task/grant/lease remains required; no old task replay or publication can be inferred.

Shared fixture: `docs/fixtures/distribution-handoff-resolution-read-v1.json`, SHA-256 `7c82ccf7431efa1aab42915a9c3c5ddda299fbb8b7ab6fce974eaac5a7bfa8fc`. The closure fixture's fictional project target has been corrected to seo-19, giving the revised closure SHA above; historical evidence preserves its original byte hash.

## Candidate schema and proof scope

Apply control/scheduling/publication/queue/planning/execution, then `scripts/distribution_capability_registration_schema.sql` to a separately reviewed candidate database. The additive upgrade replaces the prior intent uniqueness with uniqueness including attempt (1–3), preserving all rows; it adds registration/request/resolution/retry lineage tables. No runtime migration is performed. Production migration remains outside this work.

Offline integration uses real loopback TLS, Node HTTPS registration transport, PostgreSQL/JWT, the durable dispatcher and the independent MHT HumanHandoffExecutor. Synthetic native source/account/provider fixtures are explicitly identified. Current stage result is a reviewed package awaiting human work, not verified platform publication. Actual MHT closure-transport adoption must be exercised once its independent implementation is frozen.
