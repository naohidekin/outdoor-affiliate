# Editorial publication recovery, 2026-11-09 JST

## Confirmed defects
1. `publish.mjs` top-level `await main()` dynamically imported revision/correction publishers which import its shared exports. CLI actions exited 13 with no JSON (unresolved top-level await). Import-only tests did not exercise the CLI. Entry now invokes `void main()`; subprocess regression tests cover all three dynamic entry actions.
2. Affected-article lookup used PostgreSQL array overlap (`ov`) on JSONB `product_ids`. Production read returned HTTP 404, SQLSTATE 42883 (`jsonb && unknown`). Lookup now ORs JSONB containment predicates and preserves the 501-row safety bound.

## Recovery
The three already-approved revisions were reconciled against complete production article/product rows, exact approval hashes, images and presentation context under runtime/publication locks. Unknown effects were never blindly replayed.
- Single burner: article and all 11 product changes were applied once. A subsequent verification failed; later full read-only verification succeeded. The existing publication was recorded as successful without republishing.
- Firepit and shelter comparison: normal publisher completed and verified.
All three ledger entries are published/success with no error. In-flight markers were archived with reconciliation evidence, never removed based on age.

## Evidence limitation
The original handler erased exception detail. The single burner's post-write failure cannot retrospectively be attributed to a specific cache/image/readback error. A transient readback is possible, not established.

## Prevention
- Strictly allowlisted diagnostics: phase, DB operation, HTTP status, SQLSTATE, subprocess exit or timeout. No exception text, URLs, credentials, HTTP body, or headers.
- Runtime persists this sanitized diagnostic in unknown effect records.
- Public HTML readback can make three bounded read-only attempts after invalidation. Product/article mutations are not retried.
- Existing exact approval, complete-row baseline, xmin CAS, durable fence and unknown-effect protections remain.

## Verification
Node publisher, revision, correction, CLI and diagnostic tests; Python runtime, revision workflow and diagnostic tests. Tests use synthetic data/mocks and do not publish production content.
Private reconciliation evidence remains in the runtime state's `reconciliations/` directory.
