const DAY_MS = 24 * 60 * 60 * 1000;

function parseDateOnly(value) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) {
    throw new Error(`レポート日が YYYY-MM-DD 形式ではありません: ${value}`);
  }

  const date = new Date(`${value}T00:00:00.000Z`);
  if (Number.isNaN(date.getTime()) || date.toISOString().slice(0, 10) !== value) {
    throw new Error(`存在しないレポート日です: ${value}`);
  }

  return date;
}

function dateString(date) {
  return date.toISOString().slice(0, 10);
}

function metricTotals(properties, period) {
  return properties.reduce(
    (totals, property) => ({
      pageViews: totals.pageViews + Number(property[period].pageViews || 0),
      users: totals.users + Number(property[period].users || 0),
      sessions: totals.sessions + Number(property[period].sessions || 0),
    }),
    { pageViews: 0, users: 0, sessions: 0 },
  );
}

export function weekForReportDate(reportDate) {
  const date = parseDateOnly(reportDate);
  if (date.getUTCDay() !== 1) {
    throw new Error(`週次レポート日は月曜日である必要があります: ${reportDate}`);
  }

  const end = new Date(date.getTime() - DAY_MS);
  const start = new Date(end.getTime() - 6 * DAY_MS);
  const previousEnd = new Date(start.getTime() - DAY_MS);
  const previousStart = new Date(previousEnd.getTime() - 6 * DAY_MS);

  return {
    startDate: dateString(start),
    endDate: dateString(end),
    previousStartDate: dateString(previousStart),
    previousEndDate: dateString(previousEnd),
  };
}

export function summarizeProperties(properties) {
  if (!Array.isArray(properties) || properties.length === 0) {
    throw new Error("GA4プロパティがありません");
  }

  return {
    current: metricTotals(properties, "current"),
    previous: metricTotals(properties, "previous"),
  };
}

function formatNumber(value) {
  return new Intl.NumberFormat("en-US").format(value);
}

function percentChange(current, previous) {
  if (previous === 0) return current === 0 ? "0.0%" : "—";
  return `${(((current - previous) / previous) * 100).toFixed(1)}%`;
}

export function renderGa4Section(snapshot) {
  const totals = snapshot.totals || summarizeProperties(snapshot.properties);
  const { startDate, endDate } = snapshot.dateRange;
  const rows = [
    ["PV", totals.current.pageViews, totals.previous.pageViews],
    ["ユーザー", totals.current.users, totals.previous.users],
    ["セッション", totals.current.sessions, totals.previous.sessions],
  ];

  let markdown = "## GA4（3サイト合算）\n\n";
  markdown += `対象期間：${startDate}〜${endDate}（JST）\n\n`;
  markdown += "| 指標 | 今週 | 前週 | 前週比 |\n";
  markdown += "|---|---:|---:|---:|\n";
  for (const [label, current, previous] of rows) {
    markdown += `| ${label} | ${formatNumber(current)} | ${formatNumber(previous)} | ${percentChange(current, previous)} |\n`;
  }

  markdown += "\n### GA4サイト別セッション\n\n";
  markdown += "| サイト | 今週セッション | 前週セッション | 前週比 |\n";
  markdown += "|---|---:|---:|---:|\n";
  for (const property of snapshot.properties) {
    markdown += `| ${property.site} | ${formatNumber(property.current.sessions)} | ${formatNumber(property.previous.sessions)} | ${percentChange(property.current.sessions, property.previous.sessions)} |\n`;
  }

  return markdown;
}

export function createWeeklySnapshot({ reportDate, generatedAtJST, properties }) {
  const {
    startDate,
    endDate,
    previousStartDate,
    previousEndDate,
  } = weekForReportDate(reportDate);
  const totals = summarizeProperties(properties);
  const snapshot = {
    reportDate,
    generatedAtJST,
    dateRange: { startDate, endDate },
    previousDateRange: {
      startDate: previousStartDate,
      endDate: previousEndDate,
    },
    properties,
    totals,
  };

  return { ...snapshot, markdown: renderGa4Section(snapshot) };
}
