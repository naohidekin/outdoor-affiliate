#!/usr/bin/env node
/**
 * 楽天APIが叩ける状態かを毎日確かめる
 *
 * 背景（2026-09-02）: 楽天APIが10日間止まっていたのに、誰も気づかなかった。
 * エンドポイントのバージョンが 20220601 のままで、楽天は 20260701 に
 * 移っていた。同じURLが12ファイルに直書きされていたので、価格監査
 * （audit-prices）・相場チェック（check-market-prices）・リンク検査
 * （verify-links）・記事生成の商品取得（article-product-agent）が
 * 全部同時に死んでいた。
 *
 * 実害はもう出ている。タトンカ Tarp 4 TC の登録価格は ¥80,233 だが、
 * 実売は ¥15,499（19%）。価格監査が生きていれば拾えていた。
 *
 * 止まった原因はもうひとつある。楽天APIはIP許可リスト方式で、
 * 回線や場所が変わると CLIENT_IP_NOT_ALLOWED で弾かれる。launchd の
 * 定期実行は黙って終わるので、外出中に切れても分からない。
 *
 * このスクリプトは1回だけAPIを叩いて、結果を data/rakuten-health.json に
 * 残す。落ちていたら「いまのグローバルIP」と「許可リストに貼る行」まで
 * 出す。次に同じことが起きたとき、原因の切り分けに1日かけずに済む。
 *
 * 使い方:
 *   npm run check:rakuten          # 疎通確認。落ちていたら終了コード1
 *   npm run check:rakuten -- --quiet   # 成功時は何も出さない（パイプライン用）
 *
 * 何も書き換えない（health ファイルを除く）。鍵の値は表示しない。
 */
import fs from "node:fs";
import path from "node:path";
import dns from "node:dns";
import { fileURLToPath } from "node:url";
import { loadEnv } from "../src/lib/x-agent-utils.mjs";

dns.setDefaultResultOrder("ipv4first");
loadEnv();

const ROOT = path.join(path.dirname(fileURLToPath(import.meta.url)), "..");
const HEALTH = path.join(ROOT, "data", "rakuten-health.json");
const QUIET = process.argv.includes("--quiet");

// 変えるときは webservice.rakuten.co.jp/documentation/ichiba-item-search の
// 「リクエストURL」を見ること。バージョンを間違えると
// API Configuration not found が返り、認証エラーに見える
const API = "https://openapi.rakuten.co.jp/ichibams/api/IchibaItem/Search/20260701";

/** 落ちたときだけ呼ぶ。原因がIPかどうかを人が判断できるようにする */
async function currentIp() {
  try {
    const res = await fetch("https://ifconfig.me/ip", {
      signal: AbortSignal.timeout(5000),
    });
    const ip = (await res.text()).trim();
    return /^\d+\.\d+\.\d+\.\d+$/.test(ip) ? ip : null;
  } catch {
    return null;
  }
}

async function probe() {
  const appId = process.env.RAKUTEN_APP_ID;
  const accessKey = process.env.RAKUTEN_ACCESS_KEY;
  if (!appId || !accessKey) {
    return {
      ok: false,
      kind: "env",
      message:
        ".env.local に RAKUTEN_APP_ID / RAKUTEN_ACCESS_KEY がありません。" +
        "同じ鍵が2回書かれていると後の行が勝つので、各1行にすること",
    };
  }

  const params = new URLSearchParams({
    applicationId: appId,
    accessKey,
    keyword: "テント",
    hits: "1",
    format: "json",
    formatVersion: "2",
  });

  let res, body;
  try {
    res = await fetch(`${API}?${params}`, {
      headers: {
        Origin: "https://camp-gear-lab.com",
        Referer: "https://camp-gear-lab.com/",
      },
      signal: AbortSignal.timeout(15_000),
    });
    body = await res.text();
  } catch (e) {
    return { ok: false, kind: "network", message: `通信エラー: ${e.message}` };
  }

  if (res.ok) {
    let hits = 0;
    try {
      hits = (JSON.parse(body).Items ?? []).length;
    } catch {
      /* 200なら疎通はしている */
    }
    return { ok: true, kind: "ok", message: `商品${hits}件を取得`, status: res.status };
  }

  const flat = body.replace(/\s+/g, " ").slice(0, 200);
  if (body.includes("CLIENT_IP_NOT_ALLOWED")) {
    return { ok: false, kind: "ip", message: flat, status: res.status };
  }
  if (body.includes("API Configuration not found")) {
    return { ok: false, kind: "endpoint", message: flat, status: res.status };
  }
  return { ok: false, kind: "other", message: flat, status: res.status };
}

const result = await probe();
const ip = result.ok ? null : await currentIp();

const record = {
  checkedAt: new Date().toISOString(),
  ok: result.ok,
  kind: result.kind,
  status: result.status ?? null,
  message: result.message,
  globalIp: ip,
  endpoint: API,
};
fs.mkdirSync(path.dirname(HEALTH), { recursive: true });
fs.writeFileSync(HEALTH, JSON.stringify(record, null, 2) + "\n");

if (result.ok) {
  if (!QUIET) console.log(`[rakuten] 疎通OK（${result.message}）`);
  process.exit(0);
}

// 失敗は必ず出す。10日間気づかなかったのはここが静かだったから
console.error("\n" + "!".repeat(64));
console.error(`[rakuten] 楽天APIが使えません（${result.status ?? "-"} / ${result.kind}）`);
console.error(`  ${result.message}`);

if (result.kind === "ip") {
  console.error("\n  回線か場所が変わってIP許可リストから外れています。");
  if (ip) {
    console.error(`  いまのグローバルIP: ${ip}`);
    console.error("  webservice.rakuten.co.jp/app/list → 該当アプリ → 編集 →");
    console.error("  「許可されたIPアドレス」に次の2行を足して保存（画像認証あり）:");
    console.error(`\n    ${ip}`);
    console.error(`    ${ip.split(".").slice(0, 3).join(".")}.0/24\n`);
    console.error("  /24 も入れておくと、同じ回線でIPが振り直されても通ります");
  } else {
    console.error("  現在のIPを取得できませんでした。curl -4 -s ifconfig.me で確認してください");
  }
} else if (result.kind === "endpoint") {
  console.error("\n  エンドポイントのバージョンが古い可能性があります。");
  console.error("  webservice.rakuten.co.jp/documentation/ichiba-item-search の");
  console.error("  「リクエストURL」と、このファイル冒頭の API 定数を突き合わせてください。");
  console.error("  同じURLがリポジトリ内の複数ファイルに直書きされています:");
  console.error("    grep -rn 'IchibaItem/Search' scripts/ src/");
}

console.error("\n  この状態だと次が黙って失敗します:");
console.error("    audit-prices / check-market-prices / check-duplicate-prices");
console.error("    verify-links / fix-search-affiliate-links / article-product-agent");
console.error("!".repeat(64) + "\n");
process.exit(1);
