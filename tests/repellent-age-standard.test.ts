import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { MEDICAL_ADVICE_MAP } from "../src/lib/medicalAdviceData.ts";

// docs/repellent-age-standard.md がサイト内の唯一の正。
//
// 策定前、ディートの下限が3種類（2ヶ月／6ヶ月／2歳）、イカリジンが2種類
// （年齢制限なし／6ヶ月以上）サイト内に同居していた。読者が買うのは日本の
// 製品なので、添付文書基準に統一した。ここでは、その統一が崩れたことを
// 検出する。記事は編集画面からも書き換えられるので、機械で見張る。

const articlesRaw = JSON.parse(
  fs.readFileSync(path.join(process.cwd(), "data", "articles.json"), "utf8")
);
const allArticles: Array<{ slug: string; status: string; content: string }> =
  Array.isArray(articlesRaw) ? articlesRaw : articlesRaw.articles;

const published = allArticles.filter((a) => a.status === "published");

/** 記事本文＋その記事に紐づく医師アドバイスを合わせた検査対象 */
function blobOf(a: { slug: string; content: string }): string {
  const adv = MEDICAL_ADVICE_MAP[a.slug];
  return a.content + (adv ? adv.title + adv.body + adv.bullets.join("。") : "");
}

const DEET = /ディート|DEET/;

test("基準ドキュメントが存在する", () => {
  const p = path.join(process.cwd(), "docs", "repellent-age-standard.md");
  assert.ok(fs.existsSync(p), "docs/repellent-age-standard.md が無い");
  const doc = fs.readFileSync(p, "utf8");
  for (const must of ["生後6ヶ月未満", "12%", "年齢制限なし", "2歳未満"]) {
    assert.ok(doc.includes(must), `基準ドキュメントに「${must}」が無い`);
  }
});

test("ディートの下限月齢がサイト内で1種類になっている", () => {
  // 「2ヶ月」「2歳未満は使用禁止」など、6ヶ月以外の下限が書かれていないか
  const bad: string[] = [];
  for (const a of published) {
    const blob = blobOf(a);
    if (!DEET.test(blob)) continue;
    for (const s of blob.split(/[。\n]/)) {
      if (!DEET.test(s)) continue;
      // 「AAPは2ヶ月以上を認めるが、当サイトは従わない」という説明文まで
      // 拾ってしまったので、海外基準に言及している文は対象外にする。
      // 検査が「使用」と「言及」を区別できていなかった
      if (/AAP|CDC|EPA|米国|海外/.test(s)) continue;
      if (/2\s*[かヶケ]月以上|2\s*[かヶケ]月から/.test(s))
        bad.push(`${a.slug}: 米国基準（2ヶ月）が残っている「${s.trim().slice(0, 60)}」`);
      if (/2歳未満は使用禁止|2歳未満.*使用しない/.test(s))
        bad.push(`${a.slug}: 下限を2歳としている「${s.trim().slice(0, 60)}」`);
    }
  }
  assert.deepEqual(bad, [], bad.join("\n"));
});

test("イカリジンに誤った年齢制限を付けていない", () => {
  // 「イカリジンは6ヶ月以上から」はディートの制限を誤って当てたもの
  const bad: string[] = [];
  for (const a of published) {
    for (const s of blobOf(a).split(/[。\n]/)) {
      if (!/イカリジン/.test(s)) continue;
      if (/イカリジン[^。]*6\s*[かヶケ]月以上/.test(s))
        bad.push(`${a.slug}: 「${s.trim().slice(0, 70)}」`);
    }
  }
  assert.deepEqual(bad, [], bad.join("\n"));
});

test("12歳未満の濃度に「30%以下」という紛らわしい表現を使っていない", () => {
  // 「30%以下」は30%を含むと読める。子ども向けは12%以下と書く
  const bad: string[] = [];
  for (const a of published) {
    for (const s of blobOf(a).split(/[。\n]/)) {
      if (!/12歳未満|子ども|子供/.test(s)) continue;
      // 「『30%以下』という書き方は紛らわしいので12%以下と覚えて」という
      // 注意書き自体を拾ってしまった。正しい値へ誘導している文は対象外
      if (/12\s*[%％]以下/.test(s)) continue;
      if (/30\s*[%％]以下/.test(s))
        bad.push(`${a.slug}: 「${s.trim().slice(0, 70)}」`);
    }
  }
  assert.deepEqual(bad, [], bad.join("\n"));
});

test("ハッカ油を乳幼児の虫よけとして可としていない", () => {
  // ハッカ油は虫よけとして承認された有効成分ではなく、乳幼児では
  // メントールによる反射性無呼吸・喉頭けいれんの懸念がある
  const bad: string[] = [];
  for (const a of published) {
    for (const s of blobOf(a).split(/[。\n]/)) {
      if (!/ハッカ油/.test(s)) continue;
      if (/(乳児|乳幼児|赤ちゃん|0〜2歳|2歳未満)[^。]*(使用可|使える|大丈夫|おすすめ)/.test(s))
        bad.push(`${a.slug}: 「${s.trim().slice(0, 70)}」`);
    }
    // 表形式で「| 2ヶ月〜6ヶ月 | ... | ○ 使用可 |」のような行も見る
    for (const row of a.content.split("\n")) {
      if (!/^\|/.test(row)) continue;
      if (!/[かヶケ]月|歳/.test(row)) continue;
      if (/ハッカ油/.test(a.content) && /○\s*使用可/.test(row) && /2\s*[かヶケ]月/.test(row))
        bad.push(`${a.slug}: 表の行「${row.trim().slice(0, 70)}」`);
    }
  }
  assert.deepEqual(bad, [], bad.join("\n"));
});

test("ハッカ油を扱う記事に、虫よけとして推奨しない旨が書かれている", () => {
  const missing: string[] = [];
  for (const a of published) {
    const blob = blobOf(a);
    // 商品として掲載しているか、成分比較で扱っている記事だけを対象にする
    if ((blob.match(/ハッカ油/g) ?? []).length < 3) continue;
    if (!/推奨しません|推奨しない|主役にはしない/.test(blob))
      missing.push(a.slug);
  }
  assert.deepEqual(
    missing,
    [],
    `ハッカ油を扱うのに非推奨の明示が無い: ${missing.join(", ")}`
  );
});

test("ディートの回数制限を書いている記事は、添付文書の区分に沿っている", () => {
  const bad: string[] = [];
  for (const a of published) {
    const blob = blobOf(a);
    if (!DEET.test(blob)) continue;
    // 具体的な回数を書いている記事だけを対象にする。「回数制限があります
    // （詳細は別記事）」で済ませる総まとめ記事まで区分を要求すると厳しすぎる
    if (!/1日1回|1日1〜3回|1日3回/.test(blob)) continue;
    // 区分を書くなら「6ヶ月」「2歳」「12歳」の3つの境界が揃っているはず
    const hasAll =
      /6\s*[かヶケ]月/.test(blob) && /2歳/.test(blob) && /12歳/.test(blob);
    if (!hasAll) bad.push(`${a.slug}: 回数制限を書いているが年齢区分が不完全`);
  }
  assert.deepEqual(bad, [], bad.join("\n"));
});
