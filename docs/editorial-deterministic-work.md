# Camp editorial: deterministic execution implementation

Owner instruction: implement the approved separation of deterministic progression and AI editorial work; preserve all quality gates and separate exact-version article/SNS approvals. Do not restart automations or deploy into the active runtime.

## Plan and acceptance

1. Establish an isolated branch and offline baseline. Preserve all unrelated dirty files in both original checkouts.
2. Implement deterministic dispatch and a fail-closed suspension policy without falling into legacy automatic generation.
3. Persist dependency-bound AI stage results, measured usage and bounded retry reservations in the existing SQLite ledger. Unknown outcomes require reconciliation, never replay.
4. Package repeated status, planning, bounded recovery and verification procedures as a skill over maintained program entrypoints.
5. Run meaningful offline integration/regression checks and an independent whole-change review. Verify no provider calls, Slack sends, publication or scheduler reactivation occurred.
6. Commit and synchronize the isolated feature branch to both Macs. Keep production checkout/configuration and paused Codex automations unchanged. Report integration/deployment prerequisites separately.

## Rulings

- The live worktrees contain concurrent safety/display/approval changes. This feature starts from committed e70fe2a in a separate worktree; it must not overwrite or commit the concurrent work. Integration with those changes is a separate verification step.
- Cached AI output is not a quality or owner approval. Current source, rendering and publication gates remain mandatory. Actual publication checks cannot be replaced by successful preview checks.
- Do not reuse a model result when a material dependency changes. Do not globally strip timestamps; explicit source observation clocks may be normalized only when current sources have been revalidated.
- Keep existing model routes, source safeguards, final review, independent Astra requirements and publication/social effect journals. Preserve historical failures, counters and receipts.
- No new scheduled monitor or independent producer daemon. The existing single-runner lock remains the execution boundary.

## Verification log

- Initial isolated baseline: 627 tests, 3 errors due to absent worktree Node dependencies. Original checkout dependency directory linked into the isolated worktree; no dependency install or production modification.
- Baseline after dependency setup: 627 tests PASS (14.841 seconds). All model, merchant, Slack and publication boundaries are mocked/offline in this suite.
- Stage journal focused tests: 12 PASS. Unknown outcomes, input changes, output integrity, bounded retry and SQLite reservation concurrency covered.
- Parent skill/CLI forward check: status succeeds with a nonexistent config path; plan and retry-stage --execute return suspended using a config with an unreadable credential path. All three commands exited successfully and the SQLite bytes remained unchanged. No real Runtime/provider/publication was invoked.
- Both skill entrypoints passed the skill-creator static validator. Runtime behavior is proven by tests separately, not by the validator.
- Parent full feature suite: 665 tests PASS (14.390 seconds).
- Concurrent existing safety/display/approval changes copied to a second isolated worktree: baseline 688 tests PASS (15.754 seconds). Feature patch merged there with Git three-way application without conflicts; combined suite 726 tests PASS (21.083 seconds). Those other changes remain uncommitted and untouched in their original checkouts.
- Existing Node publication/social contracts: 129 PASS, 3 SKIP, 0 failures (132 tests). These are offline contracts, not actual publication/authentication checks.
- Independent review found seven blockers despite the green initial suite: Astra-wait candidate starvation; blocked health marked completed; revision-specific stage retry; direct private article entry during suspension; corrupt old journal bypass; provider timeout classified as retryable failure; benign provider usage extensions rejected. All findings accepted for a bounded correction pass with regression tests. Earlier test counts remain historical until corrected code is reverified.
- Corrected feature: parent full suite 674 PASS (14.237 seconds); implementer full suite 674 PASS and focused 133 PASS. Corrected patch merged cleanly into the concurrent-change verification copy; parent combined suite 735 PASS (14.050 seconds). Independent delta recheck remains the final review gate.
- Independent corrected-delta review: PASS, all seven findings resolved; reviewer ran 133 focused regressions and whitespace validation. No reviewer file edits, production effects or scheduler changes.
- Implementation and final validation results are recorded below after actual execution.
