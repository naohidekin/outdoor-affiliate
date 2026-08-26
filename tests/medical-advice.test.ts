import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { MEDICAL_ADVICE_MAP } from "../src/lib/medicalAdviceData.ts";

const articlesRaw = JSON.parse(
  fs.readFileSync(path.join(process.cwd(), "data", "articles.json"), "utf8")
);
const allArticles: Array<{
  slug: string;
  status: string;
  categoryId: string;
  content: string;
}> = Array.isArray(articlesRaw) ? articlesRaw : articlesRaw.articles;

const bySlug = new Map(allArticles.map((a) => [a.slug, a]));

test("医師アドバイスは実在する公開記事だけを指している", () => {
  // slugを打ち間違えても何も表示されないだけで、静かに効かないまま残る
  const bad: string[] = [];
  for (const slug of Object.keys(MEDICAL_ADVICE_MAP)) {
    const a = bySlug.get(slug);
    if (!a) bad.push(`${slug}: 記事が存在しない`);
    else if (a.status !== "published") bad.push(`${slug}: ${a.status}`);
  }
  assert.deepEqual(bad, [], bad.join("\n"));
});

test("医師アドバイスの中身が空でない", () => {
  for (const [slug, adv] of Object.entries(MEDICAL_ADVICE_MAP)) {
    assert.ok(adv.title.trim(), `${slug}: title が空`);
    assert.ok(adv.body.trim().length >= 40, `${slug}: body が短すぎる`);
    assert.ok(adv.bullets.length >= 3, `${slug}: bullets が3つ未満`);
    for (const b of adv.bullets) {
      assert.ok(b.trim(), `${slug}: 空の bullet がある`);
    }
  }
});

test("医師アドバイスの注入位置にフォールバックがある", () => {
  // 以前は "\n## まとめ" しか探しておらず、見つからないと描画側が丸ごと
  // 通常表示に落ちて、医師アドバイスが1文字も出なかった。
  // oniyamma-shinrinka-review がまさにこれで、登録されているのに
  // 一度も表示されていなかった。安全に関する内容が、記事の書き方ひとつで
  // 静かに消えるのは筋が悪いので、代替アンカーと末尾フォールバックを入れた
  const PAGE = fs.readFileSync(
    path.join(process.cwd(), "src", "app", "articles", "[slug]", "page.tsx"),
    "utf8"
  );
  assert.ok(
    /anchors = \[[\s\S]*?"\\n## 関連記事"/.test(PAGE),
    "代替アンカーが無い。まとめが無い記事で医師アドバイスが消える"
  );
  assert.ok(
    /contentSummaryOnward = " ";/.test(PAGE),
    "末尾フォールバックが無い。見出しが無い記事で医師アドバイスが消える"
  );
});

test("登録済みの医師アドバイスが、実際に注入位置を持っている", () => {
  const anchors = ["\n## まとめ", "\n## 関連記事", "\n## よくある質問"];
  const orphan = Object.keys(MEDICAL_ADVICE_MAP).filter((slug) => {
    const c = bySlug.get(slug)?.content ?? "";
    return !anchors.some((a) => c.includes(a));
  });
  // フォールバックがあるので表示自体は保証されるが、位置が末尾になる。
  // 記録として出しておく
  if (orphan.length > 0) {
    console.log(`  [注意] 末尾表示になる記事: ${orphan.join(", ")}`);
  }
  assert.ok(true);
});

test("暖房カテゴリの記事に医師アドバイスが付いている", () => {
  // 燃焼・一酸化炭素・低温やけどを扱う暖房カテゴリは、このサイトが掲げる
  // 「現役小児科医監修」が最も効くべき場所。2026-08-26時点で1本も
  // 登録されていなかったため、明示的に守る
  const heaters = allArticles.filter(
    (a) => a.status === "published" && a.categoryId === "heater"
  );
  assert.ok(heaters.length > 0, "暖房カテゴリの公開記事が0本。検証になっていない");

  const missing = heaters
    .filter((a) => !MEDICAL_ADVICE_MAP[a.slug])
    .map((a) => a.slug);
  assert.deepEqual(
    missing,
    [],
    `暖房記事に医師アドバイスが無い: ${missing.join(", ")}`
  );
});

test("やけどと一酸化炭素の両方が、暖房記事のどこかで扱われている", () => {
  // 暖房ハブは一酸化炭素を11回書いていた一方、やけどの記載が0回だった。
  // 初心者に電気毛布を勧める記事で、電気毛布で最も多い事故に触れないのは
  // 片手落ちになる。本文か医師アドバイスのどちらかで必ず扱う。
  //
  // 当初この検査は「低温やけど」という語を要求していたが、それは
  // 電気毛布に固有の事故で、石油ストーブで問題になるのは接触やけどのほう。
  // 語を決め打ちすると、正しく書いてある記事まで落ちる。やけど全般で見る
  const gaps: string[] = [];
  for (const a of allArticles) {
    if (a.status !== "published" || a.categoryId !== "heater") continue;
    const adv = MEDICAL_ADVICE_MAP[a.slug];
    const blob = a.content + JSON.stringify(adv ?? {});
    if (!/やけど|火傷/.test(blob)) gaps.push(`${a.slug}: やけどの記載なし`);
    if (!/一酸化炭素|CO中毒|COチェッカー/.test(blob))
      gaps.push(`${a.slug}: 一酸化炭素の記載なし`);
  }
  assert.deepEqual(gaps, [], gaps.join("\n"));
});

test("暖房記事の医師アドバイスは、子どもに固有の注意点に触れている", () => {
  // このサイトの差別化は「現役小児科医監修」。暖房で子どもが受ける害は
  // 大人と質が違う（体重あたりの呼吸量が多い／皮膚が薄い／熱いと言えない）。
  // 一般論だけの安全注意なら、医師が書く意味がない
  const missing: string[] = [];
  for (const a of allArticles) {
    if (a.status !== "published" || a.categoryId !== "heater") continue;
    const adv = MEDICAL_ADVICE_MAP[a.slug];
    if (!adv) continue; // 別のテストが未登録を検出する
    const blob = adv.title + adv.body + adv.bullets.join("");
    if (!/子ども|子供|小児|乳幼児|赤ちゃん/.test(blob))
      missing.push(a.slug);
  }
  assert.deepEqual(
    missing,
    [],
    `子どもへの言及が無い暖房記事の医師アドバイス: ${missing.join(", ")}`
  );
});

test("小児の一酸化炭素の記述が、総量ではなく体重あたりで書かれている", () => {
  // 2026-08-26 医師レビューでの指摘。
  // 「小児は一酸化炭素を早く多く取り込む」と書いていたが、これは不正確。
  // 体重あたりの分時換気量が多いことから言えるのは「体重あたりでは速く
  // 取り込む」までで、総量として大人より多いとは限らない。
  // 「体格が小さいから症状進行が早い」も機序の説明として誤り。
  const vague = ["早く多く", "多く取り込", "体格が小さく"];
  const hits: string[] = [];
  for (const [slug, adv] of Object.entries(MEDICAL_ADVICE_MAP)) {
    const blob = adv.title + adv.body + adv.bullets.join("");
    for (const w of vague) {
      if (blob.includes(w)) hits.push(`${slug}: 「${w}」`);
    }
    // 一酸化炭素に触れているなら、体重あたりの枠組みで書く
    if (/一酸化炭素/.test(blob) && /小児|子ども/.test(blob)) {
      assert.ok(
        /体重あたり|体重当たり/.test(blob),
        `${slug}: 小児の一酸化炭素を体重あたりの枠組みで書いていない`
      );
    }
  }
  assert.deepEqual(hits, [], hits.join("\n"));
});

test("体表面積と脱水を、同じ文で因果としてつないでいない", () => {
  // 2026-08-26 医師レビューでの指摘。
  // 「体表面積が大きいので、暑さ寒さの影響を受けやすく、脱水も早い」と
  // 書いていたが、2つは別の機序。体温調節は体表面積と調節機能の未熟さ、
  // 脱水は体重あたりの必要水分量の多さと水分予備量の少なさ（加えて
  // 腎の濃縮力の未熟さ、自分で補給できないこと）による。
  // 体表面積で脱水まで説明するのは不十分。
  const hits: string[] = [];
  for (const [slug, adv] of Object.entries(MEDICAL_ADVICE_MAP)) {
    const blob = adv.body + adv.bullets.join("。");
    for (const sentence of blob.split(/[。！？]/)) {
      if (/体表面積/.test(sentence) && /脱水/.test(sentence)) {
        hits.push(`${slug}: 「${sentence.trim()}」`);
      }
    }
    // 脱水に触れるなら、その機序を書く
    if (/脱水/.test(blob)) {
      assert.ok(
        /水分予備量|必要な水分量|水分量が多/.test(blob),
        `${slug}: 脱水に触れているが機序が書かれていない`
      );
    }
  }
  assert.deepEqual(hits, [], hits.join("\n"));
});

test("医師アドバイスに薬機法・医療法で問題になる表現が入っていない", () => {
  // docs/x-post-skill.md の方針をここにも適用する。
  // 効能効果の断定、診断行為、治療の指示は書かない
  const banned = [
    "治ります",
    "治る",
    "効果があります",
    "予防できます",
    "安全です",
    "副作用はありません",
    "診断",
    "処方",
  ];
  const hits: string[] = [];
  for (const [slug, adv] of Object.entries(MEDICAL_ADVICE_MAP)) {
    const blob = adv.title + adv.body + adv.bullets.join("");
    for (const w of banned) {
      if (blob.includes(w)) hits.push(`${slug}: 「${w}」`);
    }
  }
  assert.deepEqual(hits, [], hits.join("\n"));
});
