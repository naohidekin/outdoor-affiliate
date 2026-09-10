import fs from "node:fs/promises";
import path from "node:path";
import { CHECKPOINT_DAYS, isSettledObservation } from "./state.mjs";

const JST = new Intl.DateTimeFormat("ja-JP", { timeZone: "Asia/Tokyo", year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false });
function jst(instant) { return instant ? `${JST.format(new Date(instant)).replaceAll("/", "-")} JST` : "不明"; }
function metric(value) { return value === undefined ? "不明" : value === null ? "未取得" : String(value); }
function latestObservation(experiment) { return [...(experiment.observations || [])].filter(isSettledObservation).sort((a, b) => Date.parse(b.observedAt) - Date.parse(a.observedAt))[0]; }
function change(before, after) {
  if (typeof before !== "number" || typeof after !== "number") return "算出不可";
  return `${after - before >= 0 ? "+" : ""}${after - before}`;
}
function total(runs, key) {
  if (!runs.length || runs.some((run) => typeof run[key] !== "number")) return null;
  return runs.reduce((sum, run) => sum + run[key], 0);
}
function costLines(usage) {
  const runs = Array.isArray(usage?.runs) ? usage.runs : [];
  if (!runs.length) return ["- Codex credits 推定: 不明（利用実績ファイルなし）", "- 実 USD: 不明", "- API 比較推定: 不明（実費ではない）"];
  const operations = runs.filter((run) => run.kind === "operations");
  const implementation = runs.filter((run) => run.kind === "implementation");
  const credits = (label, values) => { const value = total(values, "codexCreditsEstimate"); return `- Codex credits 推定（${label}）: ${value == null ? "不明" : value.toFixed(2)}`; };
  const actual = total(runs, "actualUsd"); const api = total(runs, "apiUsdEstimate");
  return [credits("operations", operations), credits("implementation", implementation), `- 実 USD: ${actual == null ? "不明" : `$${actual.toFixed(2)}`}`, `- API 比較推定: ${api == null ? "不明" : `$${api.toFixed(2)}`}（実費ではない）`];
}
function cohortSummary(experiment) {
  const observation = latestObservation(experiment); const comparison = observation?.comparison; const cohort = comparison?.queryCohort;
  if (!cohort) return `${experiment.urls.canonical}: 未測定（固定 query/page/device cohort が未記録）`;
  if (Array.isArray(cohort.rows)) {
    const previous=comparison.beforeMetrics,current=observation.metrics;
    return `${experiment.urls.canonical}: 固定 query/device ${cohort.size}組、比較可能 ${cohort.comparable}組、観測欠損 ${cohort.missingAfter}組。GSC平均掲載順位3位以内 ${cohort.top3.before}→${cohort.top3.after}組、1位以内 ${cohort.top1.before}→${cohort.top1.after}組。${comparison.days}日間、${comparison.beforeStart}〜${comparison.beforeEnd} / ${observation.periodStart}〜${observation.periodEnd}（PT）。クリック ${metric(previous?.clicks)}→${metric(current?.clicks)}（差 ${change(previous?.clicks,current?.clicks)}）。ライブ検索順位・因果効果の証明ではない。`;
  }
  const count = (value) => Array.isArray(value) ? value.length : 0;
  const previous = comparison.previousPeriod?.pageMetrics || comparison.previousPeriod?.metrics;
  const current = comparison.pageMetrics || comparison.currentPeriod?.pageMetrics || comparison.currentPeriod?.metrics;
  const beforeWindow = comparison.previousPeriod?.startDate && comparison.previousPeriod?.endDate ? `${comparison.previousPeriod.startDate}〜${comparison.previousPeriod.endDate}` : "未記録";
  const afterWindow = comparison.startDate && comparison.endDate ? `${comparison.startDate}〜${comparison.endDate}` : comparison.currentPeriod?.startDate && comparison.currentPeriod?.endDate ? `${comparison.currentPeriod.startDate}〜${comparison.currentPeriod.endDate}` : "未記録";
  const matched = previous && current ? `一致期間の clicks: ${metric(previous.clicks)} → ${metric(current.clicks)} (${change(previous.clicks, current.clicks)})` : "一致期間の変化: 未測定";
  return `${experiment.urls.canonical}: query ${count(cohort.queries)}件、page ${count(cohort.pages)}件、device ${count(cohort.devices)}件。${comparison.days ?? "不明"}日、比較窓 ${beforeWindow} / ${afterWindow}。${matched}`;
}

/** Records describe observations, not causal proof. This renderer never declares a winner automatically. */
/** @param {{generatedAt?: string, experiments?: any[], due?: any, usage?: any}} [input] */
export function renderReport({ generatedAt, experiments = [], due = {}, usage } = {}) {
  const observing = experiments.filter((item) => ["observing", "published", "verification_pending", "publishing", "approved", "paused"].includes(item.status));
  const actions = experiments.flatMap((item) => (item.history || []).map((event) => ({ ...event, experiment: item }))).sort((a, b) => Date.parse(b.at) - Date.parse(a.at));
  const lines = [
    "# SEO実験 週次レポート",
    "",
    `生成: ${jst(generatedAt)}`,
    "",
    "## 実施状況",
    "",
  ];
  if (!experiments.length) lines.push("今週の実験・観測・公開イベントはありません。");
  else {
    const recent = actions.slice(0, 12);
    lines.push(recent.length ? recent.map((event) => `- ${jst(event.at)}: ${event.experiment.urls.canonical} — ${event.type}`).join("\n") : "記録済みのアクションはありません。");
  }
  lines.push("", "## 観測中のページとチェックポイント", "");
  if (!observing.length) lines.push("観測中または公開待ちのページはありません。");
  else lines.push(...observing.map((item) => {
    const pending = (due.due || []).filter((entry) => entry.experimentId === item.id).map((entry) => `${entry.day}日目 (${jst(entry.dueAt)}${entry.late ? "、期限超過" : ""})`).join("、");
    const future = item.publishedAt ? CHECKPOINT_DAYS.filter((day) => !(item.observations || []).some((entry) => isSettledObservation(entry) && entry.checkpointDay === day)).join(" / ") : "公開確認待ち";
    return `- ${item.urls.canonical}: ${item.status}。${pending ? `対応待ち: ${pending}` : `未完了チェックポイント: ${future}`}`;
  }));
  lines.push("", "## 指標（ベースライン / 最新観測）", "");
  if (!experiments.length) lines.push("比較できる指標はありません。");
  else lines.push("| ページ | ベースライン | 最新有効観測 | ソース |", "| --- | --- | --- | --- |");
  for (const item of experiments) {
    const observation = latestObservation(item); const before = item.baseline?.metrics || {}; const after = observation?.metrics || {};
    lines.push(`| ${item.urls.canonical} | clicks ${metric(before.clicks)} / impressions ${metric(before.impressions)} / position ${metric(before.position)} | clicks ${metric(after.clicks)} / impressions ${metric(after.impressions)} / position ${metric(after.position)} | GSC（基準・観測とも PT） |`);
  }
  lines.push("", "## 判断と次の対応", "");
  if (due.awaitingPublication?.length) lines.push(...due.awaitingPublication.map((item) => `- ${item.urls.canonical}: 公開の検証完了後にのみ観測時計を開始する。`));
  if (due.late?.length) lines.push(...due.late.map((item) => `- ${item.url}: ${item.day}日目の観測が期限超過。GSCの有効な値を確認して記録する。`));
  if (!due.awaitingPublication?.length && !due.late?.length) lines.push("- 次回チェックポイントまで継続観測する。終端判断には Astra の根拠付き明示決定が必要。 ");
  lines.push("", "## 固定コホート KPI", "");
  if (!experiments.length) lines.push("固定コホートは未測定。");
  else lines.push(...experiments.map((experiment) => `- ${cohortSummary(experiment)}`));
  lines.push("", "## 信頼度と費用", "", "- GSCは太平洋時間（America/Los_Angeles）を明記した観測値。sourceValid=false・期間未確定・欠損データはチェックポイント達成や比較に含めない。遅延・季節性・他施策の影響があるため、相関を因果と扱わない。", ...costLines(usage), "");
  return lines.join("\n");
}

export async function readUsage(root) {
  try { return JSON.parse(await fs.readFile(path.join(root, "usage.json"), "utf8")); }
  catch (error) { if (error.code === "ENOENT") return undefined; throw error; }
}

export async function writeReport(root, markdown, generatedAt = new Date().toISOString()) {
  const dir = path.join(root, "reports"); await fs.mkdir(dir, { recursive: true });
  const date = new Intl.DateTimeFormat("sv-SE", { timeZone: "Asia/Tokyo" }).format(new Date(generatedAt));
  const filename = path.join(dir, `weekly-${date}.md`);
  const temporary = `${filename}.${process.pid}.tmp`;
  await fs.writeFile(temporary, markdown, { mode: 0o600 }); await fs.rename(temporary, filename);
  return filename;
}
