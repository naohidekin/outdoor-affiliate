import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import {
  ALLOWED_EVENT_FIELDS,
  EN_EVENTS,
  sanitizeEventPayload,
} from "../../../src/lib/experiments/snow-peak-igt/analytics.ts";
import { FORBIDDEN_PHRASES } from "../../../src/lib/experiments/snow-peak-igt/core.ts";

const ROOT = process.cwd();
const read = (p: string) => fs.readFileSync(path.join(ROOT, p), "utf8");

const EN_SOURCE_FILES = [
  "src/app/en/layout.tsx",
  "src/app/en/page.tsx",
  "src/app/en/tools/snow-peak-igt-model-finder/page.tsx",
  "src/app/en/guides/snow-peak-igt-model-numbers/page.tsx",
  "src/app/en/methodology/page.tsx",
  "src/app/en/affiliate-disclosure/page.tsx",
  "src/components/en/EnChrome.tsx",
  "src/components/en/EnClientBits.tsx",
  "src/components/en/ModelFinder.tsx",
  "src/components/en/ModelRequest.tsx",
];

// ─── イベント定義 ─────────────────────────────────────

test("必要な8イベントが定義されている", () => {
  assert.deepEqual(
    [...EN_EVENTS].sort(),
    [
      "affiliate_click",
      "english_hub_view",
      "finder_complete",
      "finder_start",
      "finder_view",
      "model_request_submit",
      "result_found",
      "result_unknown",
    ]
  );
});

test("イベントに載せてよい項目は6つだけ", () => {
  assert.deepEqual(
    [...ALLOWED_EVENT_FIELDS].sort(),
    ["market", "merchant", "model_id", "page", "placement", "result_status"]
  );
});

// ─── payload のサニタイズ ─────────────────────────────

test("自由入力テキストは payload に載らない", () => {
  const out = sanitizeEventPayload({
    page: "finder",
    query: "I need a CK-080 for my kitchen setup",
    purpose: "connecting a burner",
    notes: "free text",
  });
  assert.deepEqual(out, { page: "finder" });
});

test("メールアドレスは payload に載らない", () => {
  const out = sanitizeEventPayload({
    market: "us",
    email: "someone@example.com",
    userEmail: "someone@example.com",
  });
  assert.deepEqual(out, { market: "us" });
  assert.ok(!JSON.stringify(out).includes("@"));
});

test("氏名・完全なアフィリエイトURLは payload に載らない", () => {
  const out = sanitizeEventPayload({
    merchant: "Fixture Store",
    name: "Jane Doe",
    link_url: "https://example.invalid/buy?tag=camp78-22",
    url: "https://example.invalid/buy",
  });
  assert.deepEqual(out, { merchant: "Fixture Store" });
});

test("文字列以外の値は落とす（オブジェクトを渡されても展開されない）", () => {
  const out = sanitizeEventPayload({
    page: "finder",
    market: { country: "us", raw: "free text" },
    model_id: 1234,
  });
  assert.deepEqual(out, { page: "finder" });
});

test("空文字・空白のみの値は落とす", () => {
  assert.deepEqual(sanitizeEventPayload({ page: "", market: "   " }), {});
});

test("payload でないものを渡しても落ちない", () => {
  assert.deepEqual(sanitizeEventPayload(null), {});
  assert.deepEqual(sanitizeEventPayload("string"), {});
  assert.deepEqual(sanitizeEventPayload(undefined), {});
});

test("送信は必ず sanitize を通る", () => {
  const src = read("src/lib/experiments/snow-peak-igt/analytics.ts");
  assert.ok(
    /const clean = sanitizeEventPayload\(payload\)/.test(src),
    "trackEnEvent が sanitize を通していない"
  );
  assert.ok(!/gtag\("event", name, payload\)/.test(src), "生の payload を送っている");
});

test("フォームの入力値を analytics へ渡していない", () => {
  const src = read("src/components/en/ModelRequest.tsx");
  // trackEnEvent の呼び出しに、フォーム項目名が現れないこと
  const calls = src.match(/trackEnEvent\([\s\S]*?\)\;/g) ?? [];
  assert.ok(calls.length > 0, "model_request_submit を送っていない");
  for (const call of calls) {
    for (const field of ["modelNumber", "productName", "purpose", "email", "data.get"]) {
      assert.ok(!call.includes(field), `analytics 呼び出しに ${field} が含まれている`);
    }
  }
});

test("finder_start は表示ではなく入力操作で発火する", () => {
  const src = read("src/components/en/ModelFinder.tsx");
  const idx = src.indexOf('trackEnEvent("finder_start"');
  assert.ok(idx > 0, "finder_start を送っていない");
  const handler = src.slice(src.indexOf("function handleChange"), idx);
  assert.ok(
    handler.includes("value.trim() !== \"\""),
    "finder_start が入力内容を条件にしていない"
  );
  // useEffect（表示時）の中で送っていないこと
  assert.ok(
    !/useEffect\([\s\S]*?finder_start/.test(src),
    "finder_start が表示タイミングで発火している"
  );
});

test("検索語そのものはイベントに載せない", () => {
  const src = read("src/components/en/ModelFinder.tsx");
  const calls = src.match(/trackEnEvent\([\s\S]*?\}\);/g) ?? [];
  for (const call of calls) {
    assert.ok(!call.includes("query"), `イベントに検索語が載っている: ${call}`);
  }
});

// ─── アフィリエイトリンク ─────────────────────────────

test("アフィリエイトリンクに sponsored nofollow noopener が付く", () => {
  const src = read("src/components/en/EnClientBits.tsx");
  const match = src.match(/affiliate\s*\?\s*"([^"]+)"/);
  assert.ok(match, "アフィリエイト時の rel が見つからない");
  const rel = match[1].split(/\s+/);
  for (const token of ["sponsored", "nofollow", "noopener"]) {
    assert.ok(rel.includes(token), `rel に ${token} が無い（実際: ${match[1]}）`);
  }
});

test("アフィリエイトでないリンクには sponsored を付けない", () => {
  const src = read("src/components/en/EnClientBits.tsx");
  const match = src.match(/:\s*"(nofollow[^"]*)"/);
  assert.ok(match, "非アフィリエイト時の rel が見つからない");
  assert.ok(!match[1].includes("sponsored"), "非アフィリエイトに sponsored が付いている");
  assert.ok(match[1].includes("noopener"));
});

test("最初の販売リンクより前に開示が出る", () => {
  const src = read("src/components/en/ModelFinder.tsx");
  const disclosure = src.indexOf("<EnInlineDisclosure />");
  const link = src.indexOf("<EnPurchaseLink");
  assert.ok(disclosure > 0, "インライン開示が無い");
  assert.ok(link > 0, "購入リンクが無い");
  assert.ok(disclosure < link, "開示が販売リンクより後にある");
});

// ─── 表現の禁止 ───────────────────────────────────────

test("推測・保証の表現を使っていない", () => {
  for (const file of EN_SOURCE_FILES) {
    const src = read(file).toLowerCase();
    for (const phrase of FORBIDDEN_PHRASES) {
      // FORBIDDEN_PHRASES 自体を定義している core.ts は対象外
      assert.ok(!src.includes(phrase), `${file} に禁止表現「${phrase}」がある`);
    }
  }
});

test("価格・在庫・レビュー評価を表示していない", () => {
  for (const file of EN_SOURCE_FILES) {
    const src = read(file);
    for (const token of ["itemPrice", "★", "reviewAverage", "reviewCount", "inStock"]) {
      assert.ok(!src.includes(token), `${file} に ${token} がある`);
    }
  }
});

// ─── 送信先の設定 ─────────────────────────────────────

test("フォーム未設定なら壊れたフォームを描かない", () => {
  const src = read("src/components/en/ModelRequest.tsx");
  assert.ok(src.includes("if (!enabled)"), "未設定時の分岐が無い");
});

test("送信先URLをブラウザへ渡していない", () => {
  const page = read("src/app/en/tools/snow-peak-igt-model-finder/page.tsx");
  assert.ok(
    page.includes("Boolean(process.env.MODEL_REQUEST_FORM_URL)"),
    "設定の有無ではなく値を渡している可能性がある"
  );
  const client = read("src/components/en/ModelRequest.tsx");
  // コメントでの言及は許す。実際に値を読んでいないことを見る
  assert.ok(
    !client.includes("process.env.MODEL_REQUEST_FORM_URL"),
    "クライアント側で送信先URLを読んでいる"
  );
  assert.ok(
    client.includes('fetch("/api/en/model-request"'),
    "クライアントが自前のAPI経由で送っていない"
  );
});

test("言語やIPによる強制リダイレクトを実装していない", () => {
  // src/proxy.ts は 2026-08-02 から存在する管理画面の認証ガード。
  // 消すのではなく「英語セクションに手を出していないこと」を確かめる
  const proxyPath = path.join(ROOT, "src/proxy.ts");
  if (fs.existsSync(proxyPath)) {
    const proxy = fs.readFileSync(proxyPath, "utf8");
    assert.ok(
      !/accept-language/i.test(proxy),
      "proxy がブラウザ言語を見ている"
    );
    const matcher = proxy.match(/matcher:\s*"([^"]+)"/);
    assert.ok(matcher, "proxy の matcher が読めない");
    assert.ok(
      !matcher[1].includes("/en"),
      `proxy の matcher が英語セクションを含んでいる: ${matcher[1]}`
    );
  }
  for (const f of ["middleware.ts", "src/middleware.ts"]) {
    assert.ok(!fs.existsSync(path.join(ROOT, f)), `${f} が作られている`);
  }
  for (const file of EN_SOURCE_FILES) {
    const src = read(file);
    assert.ok(!src.includes("accept-language"), `${file} が言語判定している`);
    assert.ok(!src.includes("redirect("), `${file} がリダイレクトしている`);
  }
});

// ─── gtag 未ロード時の取りこぼし ──────────────────────
//
// 2026-08-24、ここで2回失敗している。
//   ① gtag が無ければイベントを捨てていた
//   ② dataLayer に積んだが config より前に入るため届かなかった
// どちらも画面上は何も起きず、実データを見て初めて分かった。
// ソースを読む検査では見つからないので、実際に呼んで確かめる。

type FakeWindow = { gtag?: (...args: unknown[]) => void };

const g = globalThis as unknown as { window?: FakeWindow };

/** window を差し替えて実行し、必ず後始末する */
async function withWindow<T>(fake: FakeWindow, fn: (send: typeof import("../../../src/lib/experiments/snow-peak-igt/analytics.ts").trackEnEvent) => Promise<T> | T): Promise<T> {
  const had = "window" in g;
  const previous = g.window;
  g.window = fake;
  try {
    const { trackEnEvent } = await import(
      "../../../src/lib/experiments/snow-peak-igt/analytics.ts"
    );
    return await fn(trackEnEvent);
  } finally {
    if (had) g.window = previous;
    else delete g.window;
  }
}

const wait = (ms: number) => new Promise((r) => setTimeout(r, ms));

test("gtag があればすぐ送る", async () => {
  const calls: unknown[][] = [];
  const fake: FakeWindow = { gtag: (...args) => calls.push(args) };

  await withWindow(fake, (send) => {
    send("english_hub_view", { page: "hub", market: "us" });
  });

  assert.equal(calls.length, 1, "即時に送られていない");
  assert.deepEqual(calls[0], [
    "event",
    "english_hub_view",
    { page: "hub", market: "us" },
  ]);
});

test("gtag が後から現れてもイベントを捨てない", async () => {
  const calls: unknown[][] = [];
  const fake: FakeWindow = {}; // 初回ロード直後：gtag はまだ無い

  await withWindow(fake, async (send) => {
    send("english_hub_view", { page: "hub" });
    assert.equal(calls.length, 0, "gtag が無いのに送っている");

    // GA4 が afterInteractive で読み込まれた状況を再現
    await wait(400);
    fake.gtag = (...args) => calls.push(args);

    await wait(700);
  });

  assert.equal(calls.length, 1, "後から現れた gtag に届いていない");
  assert.deepEqual(calls[0], ["event", "english_hub_view", { page: "hub" }]);
});

test("待っている間も sanitize は効く（自由入力とメールは届かない）", async () => {
  const calls: unknown[][] = [];
  const fake: FakeWindow = {};

  await withWindow(fake, async (send) => {
    send("model_request_submit", {
      market: "us",
      email: "someone@example.com",
      purpose: "free text",
    } as never);
    await wait(400);
    fake.gtag = (...args) => calls.push(args);
    await wait(700);
  });

  const sent = JSON.stringify(calls);
  assert.ok(sent.includes('"market":"us"'), "許可された項目が届いていない");
  assert.ok(!sent.includes("@"), "メールアドレスが送られている");
  assert.ok(!sent.includes("free text"), "自由入力が送られている");
});

test("dataLayer に直接積まない（config より前に入ると捨てられるため）", () => {
  const src = read("src/lib/experiments/snow-peak-igt/analytics.ts");
  assert.ok(
    !src.includes("dataLayer.push"),
    "dataLayer に積んでいる。config より前に入ると GA4 に処理されない"
  );
});

// ─── リクエスト導線を出す条件 ─────────────────────────
//
// 2026-08-25: データが入ったので、検索せずに送信できる状態をやめた。
// 検索を経ずに送信されると model_request_submit ÷ result_unknown の
// 分母を経ずに分子だけ増え、需要の強さが測れなくなる。

test("データがあるときは、検索して見つからなかった場合だけリクエスト導線を出す", () => {
  const src = read("src/components/en/ModelFinder.tsx");
  assert.ok(
    src.includes('{datasetEmpty || result.status === "not_found" ? ('),
    "リクエスト導線の表示条件が not_found 限定になっていない"
  );
  assert.ok(
    !src.includes('{result.status !== "found" ? ('),
    "検索前でもフォームが出る条件が残っている"
  );
});
