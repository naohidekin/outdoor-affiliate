import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

// このリポジトリは GitHub 上で公開されている。
// 鍵の置き場所を docs/local-files.md に書いた以上、そこへ値そのものを
// 書き足してしまう事故が起こりうる。1行足すだけで起きるので、機械で止める。

const ROOT = process.cwd();
const DOC = path.join(ROOT, "docs", "local-files.md");

/** .env.local に入っている鍵。値がコミットされたら即座に露出する */
const SECRET_KEYS = [
  "ADMIN_PASSWORD",
  "ADMIN_SESSION_SECRET",
  "SUPABASE_SERVICE_ROLE_KEY",
  "RAKUTEN_ACCESS_KEY",
  "RAKUTEN_APP_ID",
  "AMAZON_SECRET_KEY",
  "AMAZON_ACCESS_KEY",
  "AMAZON_CREDENTIAL_SECRET",
  "ANTHROPIC_API_KEY",
  "OPENAI_API_KEY",
  "TWITTER_BEARER_TOKEN",
  "THREADS_ACCESS_TOKEN",
  "NOTION_TOKEN",
  "BRAVE_API_KEY",
  "UNSPLASH_ACCESS_KEY",
  "REVALIDATE_SECRET",
  "BLOB_READ_WRITE_TOKEN",
  "GOOGLE_CREDENTIALS",
  "INDEXING_CREDENTIALS",
];

test("docs/local-files.md がある", () => {
  assert.ok(fs.existsSync(DOC), "docs/local-files.md が消えている");
});

test("CLAUDE.md が docs/local-files.md を読み込んでいる", () => {
  // @ 参照が外れると毎セッション自動で読まれなくなり、
  // 「envの場所が分からない」状態に戻る
  const md = fs.readFileSync(path.join(ROOT, "CLAUDE.md"), "utf8");
  assert.ok(
    /^@docs\/local-files\.md$/m.test(md),
    "CLAUDE.md の @docs/local-files.md 参照が外れています"
  );
});

/** テキストを読む対象。data/ と node_modules は除く */
function collect(dir: string, out: string[] = []): string[] {
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    if (e.name.startsWith(".")) continue;
    if (["node_modules", "data", "scratch", "logs"].includes(e.name)) continue;
    const p = path.join(dir, e.name);
    if (e.isDirectory()) collect(p, out);
    else if (/\.(md|ts|tsx|js|mjs|json)$/.test(e.name)) out.push(p);
  }
  return out;
}

test("鍵の値がコミットされていない", () => {
  // 行頭の `KEY=なにか` だけを違反とする。
  // `process.env.ADMIN_PASSWORD` や、docs 内の
  // `sed -n 's/^ADMIN_PASSWORD=//p'` のような行中の出現は拾わない
  const files = [
    ...collect(path.join(ROOT, "docs")),
    ...collect(path.join(ROOT, "src")),
    ...collect(path.join(ROOT, "scripts")),
    path.join(ROOT, "CLAUDE.md"),
    path.join(ROOT, "AGENTS.md"),
  ].filter((f) => fs.existsSync(f));

  // 手順書は `KEY={"type":"service_account",...}` のように書式を示す。
  // これは値ではないので違反にしない。省略記号・山括弧・ダミー語のどれかが
  // 入っていれば本物ではないと見なす（本物の鍵に `...` は入らない）。
  // docs/seo/indexing-runbook.md が実際にこの形で、最初の実行時に拾われた
  const PLACEHOLDER = /\.\.\.|[<>]|xxx|your[_-]|ここに|省略|例:/i;

  const bad: string[] = [];
  for (const f of files) {
    const text = fs.readFileSync(f, "utf8");
    for (const key of SECRET_KEYS) {
      const m = text.match(new RegExp(`^${key}=(.+)$`, "m"));
      if (m && !PLACEHOLDER.test(m[1]))
        bad.push(`${path.relative(ROOT, f)}: ${key}= に値が書かれている`);
    }
  }
  assert.deepEqual(
    bad,
    [],
    `公開リポジトリに鍵の値が入っています:\n${bad.join("\n")}`
  );
});

test(".env.local が .gitignore に入っている", () => {
  const gi = fs.readFileSync(path.join(ROOT, ".gitignore"), "utf8");
  for (const f of [".env.local", ".env.production"]) {
    assert.ok(
      new RegExp(`^${f.replace(".", "\\.")}$`, "m").test(gi),
      `${f} が .gitignore に無い`
    );
  }
});

test(".env.local がリポジトリに存在しない", () => {
  // ローカルにあるのは正常（Macでは必ずある）。
  // 検査するのは「Gitが追跡していないこと」なので .gitignore 側で見る。
  // ここでは追跡対象に紛れ込む典型のコピーを禁じる
  for (const name of ["env.local", "env.local.txt", "env-backup.txt"]) {
    assert.ok(
      !fs.existsSync(path.join(ROOT, name)),
      `${name} がリポジトリ直下にあります。.env.local のコピーなら削除してください`
    );
  }
});
