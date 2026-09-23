import test from "node:test";
import assert from "node:assert/strict";
import { existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import {
  createWeeklySnapshot,
  renderGa4Section,
  summarizeProperties,
  weekForReportDate,
} from "../src/lib/affiliate-weekly-ga4.mjs";
import { writeSnapshotAtomically } from "../scripts/affiliate-ga4-weekly.mjs";

const properties = [
  {
    site: "camp-gear-lab.com",
    current: { pageViews: 959, users: 760, sessions: 860 },
    previous: { pageViews: 1297, users: 945, sessions: 1102 },
  },
  {
    site: "japan-shop-helper.com",
    current: { pageViews: 659, users: 499, sessions: 533 },
    previous: { pageViews: 669, users: 524, sessions: 565 },
  },
  {
    site: "kodomo-care-lab.com",
    current: { pageViews: 294, users: 250, sessions: 298 },
    previous: { pageViews: 366, users: 278, sessions: 324 },
  },
];

test("週次レポート日から直前の月曜から日曜を導く", () => {
  assert.deepEqual(weekForReportDate("2026-09-21"), {
    startDate: "2026-09-14",
    endDate: "2026-09-20",
    previousStartDate: "2026-09-07",
    previousEndDate: "2026-09-13",
  });
});

test("月曜日以外を週次レポート日として拒否する", () => {
  assert.throws(
    () => weekForReportDate("2026-09-20"),
    /月曜日/,
  );
});

test("3サイト全ての現在値と前週値を合算する", () => {
  assert.deepEqual(summarizeProperties(properties), {
    current: { pageViews: 1912, users: 1509, sessions: 1691 },
    previous: { pageViews: 2332, users: 1747, sessions: 1991 },
  });
});

test("GA4節に期間、合計、サイト別セッションを表示する", () => {
  const markdown = renderGa4Section({
    reportDate: "2026-09-21",
    dateRange: { startDate: "2026-09-14", endDate: "2026-09-20" },
    properties,
    totals: summarizeProperties(properties),
  });

  assert.match(markdown, /## GA4（3サイト合算）/);
  assert.match(markdown, /対象期間：2026-09-14〜2026-09-20（JST）/);
  assert.match(markdown, /セッション \| 1,691 \| 1,991 \| -15\.1% \|/);
  assert.match(markdown, /camp-gear-lab\.com \| 860 \| 1,102 \|/);
});

test("収集済みの3サイト値を日付付きスナップショットへまとめる", () => {
  const snapshot = createWeeklySnapshot({
    reportDate: "2026-09-21",
    generatedAtJST: "2026-09-21T09:15:00+09:00",
    properties,
  });

  assert.deepEqual(snapshot.dateRange, {
    startDate: "2026-09-14",
    endDate: "2026-09-20",
  });
  assert.deepEqual(snapshot.previousDateRange, {
    startDate: "2026-09-07",
    endDate: "2026-09-13",
  });
  assert.equal(snapshot.totals.current.sessions, 1691);
  assert.equal(snapshot.properties.length, 3);
  assert.match(snapshot.markdown, /GA4（3サイト合算）/);
});

test("スナップショットは一時ファイルを残さず置き換える", () => {
  const directory = mkdtempSync(join(tmpdir(), "affiliate-ga4-weekly-"));
  const output = join(directory, "2026-09-21.json");
  writeFileSync(output, '{"reportDate":"old"}', "utf8");

  try {
    writeSnapshotAtomically(output, { reportDate: "2026-09-21", properties });

    assert.deepEqual(JSON.parse(readFileSync(output, "utf8")), {
      reportDate: "2026-09-21",
      properties,
    });
    assert.equal(existsSync(`${output}.tmp`), false);
  } finally {
    rmSync(directory, { recursive: true, force: true });
  }
});
