# Affiliate GA4 Weekly Connection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generate a verified three-site GA4 weekly snapshot and append it to the same-date affiliate Markdown report produced every Monday.

**Architecture:** A focused collector in `outdoor-affiliate` reads the three mapped GA4 properties and writes an atomic JSON snapshot for a requested report date. The existing Notion-to-Markdown fetcher reads only that matching snapshot and appends a labelled GA4 section. A small launch wrapper runs the collector before the fetcher; either failure stops the run and prevents a stale report from being written.

**Tech Stack:** Node.js ESM, Google Analytics Data API, launchd, node:test.

**Spec:** User request in this conversation: connect three GA4 properties to the weekly affiliate report automatically while retaining the date-mismatch fail-closed behavior.

## Global Constraints

- All reporting dates use Asia/Tokyo and a Monday report date covers the preceding Monday through Sunday.
- The three fixed properties are camp-gear-lab.com, japan-shop-helper.com, and kodomo-care-lab.com.
- The collector uses the existing `INDEXING_CREDENTIALS` or `GOOGLE_CREDENTIALS` only; secrets must not be written to source, snapshots, logs, or reports.
- A missing, malformed, or different-date snapshot is a hard failure for the Markdown fetcher.
- The Notion source remains read-only; no API writes are introduced.

## Review Focus

- A GA4 response may return `date_range_1` before `date_range_0`; classify by label, never row order.
- A launchd process has a minimal environment; every executable and output path must be explicit.
- Running before Monday 09:15 must not label a partial current week as a completed weekly report.
- An interrupted write must not leave a valid-looking partial snapshot.
- The old Notion page must not be saved when the GA4 snapshot or its report date is absent/mismatched.

### Task 1: Pure weekly-date and report rendering helpers

**Files:**
- Create: `src/lib/affiliate-weekly-ga4.mjs`
- Create: `tests/affiliate-weekly-ga4.test.ts`

**Interfaces:**
- Produces `weekForReportDate(reportDate: string)` returning `{ startDate, endDate, previousStartDate, previousEndDate }`.
- Produces `summarizeProperties(properties)` returning totals for page views, users, and sessions.
- Produces `renderGa4Section(snapshot)` returning Markdown with aggregate and per-site values.

- [x] **Step 1: Write failing tests for Monday date boundaries, totals, and a mismatched snapshot date.**

```js
assert.deepEqual(weekForReportDate('2026-09-21'), {
  startDate: '2026-09-14', endDate: '2026-09-20',
  previousStartDate: '2026-09-07', previousEndDate: '2026-09-13',
});
assert.match(renderGa4Section(snapshot), /セッション.*1,691/);
```

- [x] **Step 2: Run the focused test and confirm it fails because the helper does not exist.**

Run: `node --test tests/affiliate-weekly-ga4.test.ts`

- [x] **Step 3: Implement the pure helpers using date-only UTC arithmetic and no current-time dependence.**

- [x] **Step 4: Run the focused test and confirm it passes.**

- [x] **Step 5: Commit with collector implementation in the next task.**

### Task 2: Read-only three-property collector with atomic snapshot output

**Files:**
- Create: `scripts/affiliate-ga4-weekly.mjs`
- Modify: `src/lib/ga4-date-range.mjs` only if a tested interface is needed
- Test: `tests/affiliate-weekly-ga4.test.ts`

**Interfaces:**
- CLI: `node scripts/affiliate-ga4-weekly.mjs --report-date YYYY-MM-DD --output /absolute/path`.
- Writes one JSON object with `reportDate`, `dateRange`, `previousDateRange`, `properties`, `totals`, and pre-rendered `markdown` only after all three API calls succeed.

- [x] **Step 1: Add a failing unit test for snapshot shape and total calculation.**
- [x] **Step 2: Implement CLI argument validation, existing credential loading, GA4 requests, and temp-file-then-rename output.**
- [x] **Step 3: Run the collector once against the three production GA4 properties with an explicit historical report date and a temporary output path; verify the snapshot date, ranges, and all three site keys.**
- [x] **Step 4: Remove the temporary validation file.**

### Task 3: Fail-closed Markdown integration and single launch entrypoint

**Files:**
- Modify: `/Users/NaohideKin/.claude/scripts/fetch-affiliate-report.mjs`
- Modify: `/Users/NaohideKin/.claude/scripts/tests/fetch-affiliate-report.test.mjs`
- Create: `/Users/NaohideKin/.claude/scripts/run-affiliate-report-fetch.sh`
- Modify: `/Users/NaohideKin/Library/LaunchAgents/com.naohide.affiliate-report-fetch.plist`

**Interfaces:**
- Fetcher reads `--ga4-snapshot /absolute/path`, validates its `reportDate` against the exact Notion title date, and appends the snapshot's pre-rendered Markdown section before saving.
- Wrapper calculates the report date in JST, invokes the collector with an explicit snapshot path, then invokes the fetcher with that same path.

- [x] **Step 1: Add failing tests: a same-date snapshot is accepted and a different-date/malformed snapshot throws before any destination write.**
- [x] **Step 2: Add snapshot parsing/validation and Markdown append functions to the fetcher; invoke them only after the exact Notion page title is selected.**
- [x] **Step 3: Implement the wrapper with `set -euo pipefail`, explicit Node paths, and a private state directory.**
- [x] **Step 4: Point the existing launchd plist to the wrapper and reload the agent without manually triggering the production Notion fetch.**
- [x] **Step 5: Run focused tests, shell syntax validation, plist validation, and a local collector run to a temporary path.**

### Task 4: Record and safely commit the implementation

**Files:**
- Modify: `docs/superpowers/plans/2026-09-23-affiliate-ga4-weekly-connection.md`

- [x] **Step 1: Mark completed implementation steps and record exact verification commands/results.**
- [x] **Step 2: Stage only the GA4 collector, tests, plan, fetcher, wrapper, and plist changes.**
- [x] **Step 3: Commit locally. Do not push a branch that contains an earlier unrelated unpushed commit.**

## Verification Record

- `node --test tests/affiliate-weekly-ga4.test.ts` — 6/6 passed.
- `node scripts/affiliate-ga4-weekly.mjs --report-date 2026-09-21 --output /private/tmp/affiliate-ga4-weekly-2026-09-21.json` — three site keys, target range 2026-09-14〜20, and total sessions 1,691 verified; the temporary file was removed.
- `node --test /Users/NaohideKin/.claude/scripts/tests/fetch-affiliate-report.test.mjs` — 6/6 passed.
- `bash -n /Users/NaohideKin/.claude/scripts/run-affiliate-report-fetch.sh` and `plutil -lint /Users/NaohideKin/Library/LaunchAgents/com.naohide.affiliate-report-fetch.plist` — passed.
- `npm test` — 236 passed and 6 pre-existing unrelated data/content failures remain; none involve the new GA4 collector.
