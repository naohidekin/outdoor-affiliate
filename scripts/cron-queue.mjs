#!/usr/bin/env node
/**
 * queue-to-sheets → post-to-x のラッパー（Node.js版）
 * cron-queue.sh の代替。bash の Desktop実行制限を回避するために Node.js で実装。
 *
 * 08:00 → 平日かつ非祝日のみ実行
 * 10:00 → 土日 or 祝日のみ実行
 * 19:00 → 毎日実行（FORCE_SLOT=evening）
 *
 * 環境変数:
 *   FORCE_SLOT=morning|morning_holiday|evening  強制実行
 */

import { execSync } from "child_process";
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const PROJECT_DIR = path.join(__dirname, "..");
const LOG_DIR = path.join(PROJECT_DIR, "logs");

fs.mkdirSync(LOG_DIR, { recursive: true });

const today = new Date();
const dateStr = today.toISOString().slice(0, 10);
const LOG_FILE = path.join(LOG_DIR, `cron-queue-${dateStr.replace(/-/g, "")}.log`);

function log(msg) {
  const line = `[${new Date().toISOString().replace("T", " ").slice(0, 19)}] ${msg}`;
  console.log(line);
  fs.appendFileSync(LOG_FILE, line + "\n");
}

function isHoliday() {
  try {
    const holidays = JSON.parse(fs.readFileSync(path.join(PROJECT_DIR, "data/jp-holidays.json"), "utf-8"));
    const year = String(today.getFullYear());
    return (holidays[year] || []).includes(dateStr);
  } catch {
    return false;
  }
}

function isWeekend() {
  const dow = today.getDay(); // 0=Sun, 6=Sat
  return dow === 0 || dow === 6;
}

function isOffDay() {
  return isWeekend() || isHoliday();
}

// スロット判定
const hour = today.getHours();
const forceSlot = process.env.FORCE_SLOT;
let slot;
if (forceSlot) {
  slot = forceSlot;
} else if (hour < 9) {
  slot = "morning_weekday";   // 08:00 トリガー
} else if (hour < 12) {
  slot = "morning_holiday";   // 10:00 トリガー
} else {
  slot = "evening";           // 19:00 トリガー
}

log(`スロット判定: slot=${slot} dow=${today.getDay()} today=${dateStr}`);

if (slot === "morning_weekday" && isOffDay()) {
  log("土日祝のため朝08:00スロットをスキップ");
  process.exit(0);
}
if (slot === "morning_holiday" && !isOffDay()) {
  log("平日のため朝10:00スロットをスキップ");
  process.exit(0);
}

// Kill switch チェック
const killSwitchPath = path.join(PROJECT_DIR, "data/kill-switch.json");
if (fs.existsSync(killSwitchPath)) {
  const ks = JSON.parse(fs.readFileSync(killSwitchPath, "utf-8"));
  if (ks.enabled) {
    log("KILL SWITCH 有効。投稿をスキップします。");
    process.exit(0);
  }
}

const NODE = process.execPath;

// Step 1: queue-to-sheets
log("queue-to-sheets.js 実行開始（--max=1 --random-delay=59）");
try {
  const out = execSync(
    `"${NODE}" scripts/queue-to-sheets.js --max=1 --random-delay=59`,
    { cwd: PROJECT_DIR, encoding: "utf-8" }
  );
  process.stdout.write(out);
  fs.appendFileSync(LOG_FILE, out);
} catch (err) {
  log(`queue-to-sheets.js エラー終了: ${err.message}`);
  process.exit(1);
}

// Step 2: post-to-x
log("post-to-x.js 実行開始（--max=1）");
try {
  const out = execSync(
    `"${NODE}" scripts/post-to-x.js --max=1`,
    { cwd: PROJECT_DIR, encoding: "utf-8" }
  );
  process.stdout.write(out);
  fs.appendFileSync(LOG_FILE, out);
  log("正常完了");
} catch (err) {
  log(`post-to-x.js エラー終了: ${err.message}`);
  process.exit(1);
}
