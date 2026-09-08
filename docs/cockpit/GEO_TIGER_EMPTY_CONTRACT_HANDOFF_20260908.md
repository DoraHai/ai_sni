# GEO Tiger empty-state contract handoff — 2026-09-08

## Scope and boundary

This change is offline test material only. It does not create a production object,
authenticate as a customer, collect an answer, generate content, publish content,
change a database, or deploy a release.

The fixture describes the already confirmed Tiger integration scope:

- tenant `4`, `SZ-老虎新材料`;
- canonical website `https://www.tiger-coatings.cn/`;
- an opened GEO module with no GEO observations yet;
- a safe foundation limited to one business profile, three manual questions and one
  disabled `manual_only` website candidate.

## PR 391 disposition

Draft PR 391 (`e757bcc83151bf94a80e521bcb3d8d6a29072044`) should be closed as
superseded, without merging it into `codex/production-geo`.

Evidence:

- Its intended behavior is to suppress direction/change values when the server says
  the two weeks are incomparable and to retain comparison reasons when a trend is
  missing.
- `main` contains the replacement sequence `6bd4bccc` and `d45d4c99`, followed by
  the unit-format and small-value fixes `69d4f43a` and `00a6e9af`.
- The currently deployed acquisition-workbench source on `codex/production-sem`
  contains the complete replacement behavior and is the only production consumer of
  `officialMetricDisplay` through `integrations/geo-workbench/readonly-client.mjs`.
- `codex/production-geo` defines `officialMetricDisplay` but has no import or call site
  for that helper. Merging the old two-file branch there would not change the current
  acquisition workbench and would copy an older formatter without the later fixes.

## Contract coverage

`tiger-empty-insufficient.synthetic.json` and the read-only consumer test prove that:

- the authorized tenant context stays usable when questions and answers are empty;
- a complete week with `0/0/0` qualified samples/questions/engines is
  `insufficient`;
- all three official metrics remain `null` and display as `—`, never fabricated zero;
- trends remain incomparable and contain no invented direction;
- only the five reviewed GET resources are called and every request is `GET` with
  `cache: no-store`.

`tiger-safe-foundation.synthetic.json` is data, not an executable script. Its Node and
Python tests prove that:

- every payload is tenant 4 scoped and accepted by the current production Pydantic
  request schema;
- there are exactly three unique manual questions and no optimization unit;
- the website candidate is `manual_only` and disabled;
- no credential or token material is present;
- the fixture explicitly prohibits engine writes, patrol enablement/runs, content
  tasks, generation, channel accounts/variants and publication.

The fixture does not prove that production remains empty. That requires a separate,
authorized, authenticated GET-only acceptance run. It must not be inferred from this
offline contract.

## Validation

- `python -m pytest tests/test_geo_tiger_safe_foundation_contract.py -q`: 2 passed.
- `node --test integrations/geo-workbench/readonly-client.test.mjs integrations/geo-workbench/tiger-safe-foundation.test.mjs`: 24 passed.
- `git diff --check`: passed (Git reports only the repository's Windows LF/CRLF
  checkout warning for the existing JavaScript test).

## Review and release state

- Branch: `codex/geo-tiger-empty-contract-20260908`.
- Base: `main@62f12ed7fdc49d06428f382f47232c04de7b8e3a`.
- This handoff intentionally does not authorize merge or deployment. The exact head
  SHA is recorded after the commit and must be used for independent review.
