#!/usr/bin/env node

import { existsSync, mkdirSync, readFileSync, renameSync, rmSync, writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { google } from "googleapis";

import { createWeeklySnapshot, weekForReportDate } from "../src/lib/affiliate-weekly-ga4.mjs";
import { selectDateRangeMetricValues } from "../src/lib/ga4-date-range.mjs";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ENV_PATH = path.join(__dirname, "..", ".env.local");

const REPORT_PROPERTIES = [
  { site: "camp-gear-lab.com", propertyId: "531022117" },
  { site: "japan-shop-helper.com", propertyId: "531253544" },
  { site: "kodomo-care-lab.com", propertyId: "534615698" },
];

function loadEnv() {
  if (!existsSync(ENV_PATH)) return;

  for (const line of readFileSync(ENV_PATH, "utf8").split("\n")) {
    const match = line.match(/^([^#=]+)=(.*)$/);
    if (match && !process.env[match[1].trim()]) {
      process.env[match[1].trim()] = match[2].trim().replace(/^['"]|['"]$/g, "");
    }
  }
}

function parseArguments(argv) {
  const valueFor = (name) => {
    const index = argv.indexOf(name);
    return index === -1 ? undefined : argv[index + 1];
  };
  const reportDate = valueFor("--report-date");
  const output = valueFor("--output");

  if (!reportDate || !output) {
    throw new Error("使い方: --report-date YYYY-MM-DD --output /absolute/path.json");
  }
  if (!path.isAbsolute(output)) {
    throw new Error("--output は絶対パスで指定してください");
  }

  return { reportDate, output };
}

function nowJST() {
  const jst = new Date(Date.now() + 9 * 60 * 60 * 1000);
  return `${jst.toISOString().slice(0, 19)}+09:00`;
}

function metricValues(items) {
  return {
    pageViews: Number(items[0]?.value || 0),
    users: Number(items[1]?.value || 0),
    sessions: Number(items[2]?.value || 0),
  };
}

async function collectProperty(analyticsData, property, ranges) {
  const response = await analyticsData.properties.runReport({
    property: `properties/${property.propertyId}`,
    requestBody: {
      dateRanges: [
        { startDate: ranges.startDate, endDate: ranges.endDate },
        { startDate: ranges.previousStartDate, endDate: ranges.previousEndDate },
      ],
      metrics: [
        { name: "screenPageViews" },
        { name: "totalUsers" },
        { name: "sessions" },
      ],
    },
  });
  const { current, previous } = selectDateRangeMetricValues(response.data.rows);
  if (current.length !== 3 || previous.length !== 3) {
    throw new Error(`${property.site} のGA4日付範囲データが不完全です`);
  }

  return {
    site: property.site,
    current: metricValues(current),
    previous: metricValues(previous),
  };
}

export function writeSnapshotAtomically(output, snapshot) {
  mkdirSync(path.dirname(output), { recursive: true });
  const temporary = `${output}.${process.pid}.tmp`;
  try {
    writeFileSync(temporary, `${JSON.stringify(snapshot, null, 2)}\n`, "utf8");
    renameSync(temporary, output);
  } finally {
    if (existsSync(temporary)) rmSync(temporary, { force: true });
  }
}

async function main() {
  const { reportDate, output } = parseArguments(process.argv.slice(2));
  const ranges = weekForReportDate(reportDate);
  loadEnv();

  const credentialsText = process.env.INDEXING_CREDENTIALS || process.env.GOOGLE_CREDENTIALS;
  if (!credentialsText) {
    throw new Error("INDEXING_CREDENTIALS または GOOGLE_CREDENTIALS が未設定です");
  }

  const auth = new google.auth.GoogleAuth({
    credentials: JSON.parse(credentialsText),
    scopes: ["https://www.googleapis.com/auth/analytics.readonly"],
  });
  const analyticsData = google.analyticsdata({ version: "v1beta", auth });
  const properties = await Promise.all(
    REPORT_PROPERTIES.map((property) => collectProperty(analyticsData, property, ranges)),
  );
  const snapshot = createWeeklySnapshot({
    reportDate,
    generatedAtJST: nowJST(),
    properties,
  });

  writeSnapshotAtomically(output, snapshot);
  console.log(`GA4週次スナップショット保存: ${output}`);
}

const isDirectRun = process.argv[1]
  && path.resolve(process.argv[1]) === path.resolve(fileURLToPath(import.meta.url));

if (isDirectRun) {
  main().catch((error) => {
    console.error(`エラー: ${error.message}`);
    process.exit(1);
  });
}
