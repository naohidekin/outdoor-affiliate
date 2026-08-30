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

test("医師アドバイスは実在する記事を指している", () => {
  // slugを打ち間違えても何も表示されないだけで、静かに効かないまま残る。
  //
  // 当初は「公開記事だけ」を条件にしていたが、循環していた。
  // 医学リスクを扱う下書きは医師アドバイスが無いと公開できず
  // （medical-review-gate）、その医師アドバイスは公開記事にしか
  // 書けない、という組み合わせで身動きが取れなくなる。
  // 下書きも認める。archived と存在しないslugは引き続き弾く
  const bad: string[] = [];
  for (const slug of Object.keys(MEDICAL_ADVICE_MAP)) {
    const a = bySlug.get(slug);
    if (!a) bad.push(`${slug}: 記事が存在しない`);
    else if (a.status !== "published" && a.status !== "draft")
      bad.push(`${slug}: ${a.status}`);
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

// 以下は 2026-08-26 の医師レビューで指摘を受けた点。いずれも「間違いでは
// ないが、そのまま実行すると危ない」種類の不足だった。表現を戻すと危険が
// 復活するので、テストで固定する。

test("やけどの冷却時間を、乳幼児・広範囲へ一律に適用していない", () => {
  // 「流水15〜20分」を条件なしで書くと、乳幼児や広範囲熱傷で冷やしすぎに
  // よる低体温を招く。時間を書くなら範囲の限定と低体温の注意が要る
  for (const [slug, adv] of Object.entries(MEDICAL_ADVICE_MAP)) {
    const blob = adv.body + adv.bullets.join("。");
    if (!/15〜20分|15分|20分/.test(blob)) continue;
    assert.ok(
      /小範囲|狭い範囲/.test(blob),
      `${slug}: 冷却時間を書いているが、小範囲に限定していない`
    );
    assert.ok(
      /低体温/.test(blob),
      `${slug}: 冷却時間を書いているが、冷やしすぎ（低体温）の注意が無い`
    );
  }
});

test("灯油の誤飲で、催吐禁忌だけでなく水・牛乳も与えないと書いている", () => {
  for (const [slug, adv] of Object.entries(MEDICAL_ADVICE_MAP)) {
    const blob = adv.body + adv.bullets.join("。");
    if (!/灯油/.test(blob) || !/飲/.test(blob)) continue;
    if (!/吐かせ/.test(blob)) continue;
    assert.ok(
      /水や牛乳|牛乳も/.test(blob),
      `${slug}: 灯油の誤飲で「水や牛乳も飲ませない」が抜けている`
    );
  }
});

test("一酸化炭素の警報時に、換気ではなく退避と書いている", () => {
  for (const [slug, adv] of Object.entries(MEDICAL_ADVICE_MAP)) {
    const blob = adv.body + adv.bullets.join("。");
    if (!/警報/.test(blob)) continue;
    assert.ok(
      /屋外|外に出/.test(blob),
      `${slug}: 警報時の退避が書かれていない`
    );
    assert.ok(
      /戻らない|安全が確認/.test(blob),
      `${slug}: 「安全確認まで戻らない」が抜けている`
    );
  }
});

test("子どもの皮膚とやけどの関係を断定していない", () => {
  // 熱傷の深さは温度・接触時間・部位に左右される。皮膚が薄いことだけで
  // 「深いやけどになります」と断定するのは不正確
  const bad: string[] = [];
  for (const [slug, adv] of Object.entries(MEDICAL_ADVICE_MAP)) {
    const blob = adv.body + adv.bullets.join("。");
    for (const s of blob.split(/[。]/)) {
      // 対象は「皮膚が薄いこと」を根拠にした記述。当初は皮膚とやけどを含む
      // 全文を見ていたが、「水蒸気は皮膚の上で水に戻るときに熱を放出する」
      // のような物理の説明まで拾った。あれは皮膚の厚さの話ではない
      if (!/皮膚[^、。]*薄/.test(s) || !/やけど/.test(s)) continue;
      // 「ことがあります」も条件付きの言い方として認める
      if (!/なりやすく|なりやすい|やすくなります|ことがあります/.test(s)) {
        bad.push(`${slug}: 「${s.trim()}」`);
      }
    }
  }
  assert.deepEqual(bad, [], bad.join("\n"));
});

test("救急要請の基準に「受け答え」が含まれている", () => {
  // 「意識がはっきりしない」だけだと、受け答えがおかしい・反応が鈍い
  // 段階を見逃す
  for (const [slug, adv] of Object.entries(MEDICAL_ADVICE_MAP)) {
    const blob = adv.body + adv.bullets.join("。");
    if (!/救急要請|救急車/.test(blob)) continue;
    assert.ok(
      /受け答え/.test(blob),
      `${slug}: 救急要請の基準に「受け答え」が無い`
    );
  }
});

test("虫よけを塗らない部位を、手のひらに限定していない", () => {
  // 2026-08-26 医師レビューでの指摘。「手のひらには塗らない」と書いていたが
  // 範囲が狭すぎる。子どもは手全体を口に運ぶので「子どもの手」が正しい
  for (const [slug, adv] of Object.entries(MEDICAL_ADVICE_MAP)) {
    const blob = adv.body + adv.bullets.join("。");
    if (!/塗らない/.test(blob)) continue;
    assert.ok(
      !/手のひらには塗らない/.test(blob),
      `${slug}: 「手のひらには塗らない」は範囲が狭い。「子どもの手」にする`
    );
  }
});

test("虫よけブレスレットの効果範囲を肯定的に断定していない", () => {
  // 2026-08-26 医師レビューでの指摘。「守れるのは装着部の周囲だけ」と
  // 書いていたが、これは「装着部の周囲は守れる」と読める。
  // CDCはリストバンドを有効な防蚊対策と評価していない。
  // 効果があるかのような線引きをせず「限定的」に留める
  const adv = MEDICAL_ADVICE_MAP["insect-repellent-bracelet-ranking"];
  if (!adv) return;
  const blob = adv.title + adv.body + adv.bullets.join("。");
  assert.ok(/限定的/.test(blob), "「効果は限定的」という表現が無い");
  assert.ok(
    !/装着部の周囲だけ|装着したその周りだけ/.test(blob),
    "効果範囲を肯定的に断定している"
  );
});

// ─── 本文側の医学記述 ─────────────────────────────────
//
// 2026-08-26。医師レビューの指摘を医師アドバイス（MEDICAL_ADVICE_MAP）にだけ
// 反映して、記事本文を見ていなかった。その結果、同じページに矛盾する2つの
// 指示が並んでいた。
//   kids-camp-first-aid-kit  本文「流水で最低10分間」/ ボックス「小範囲なら15〜20分」
//   family-camp-safety-guide 本文「流水で最低15〜20分」（条件なし）
// ボックスだけ守っても意味がない。本文も同じ基準で見張る。

test("記事本文のやけど冷却時間に、小範囲の限定と低体温の注意がある", () => {
  const bad: string[] = [];
  for (const a of allArticles) {
    if (a.status !== "published") continue;
    // 冷却の文脈での「◯分」だけを対象にする。「冷凍庫で10分で凍る」のような
    // 製品の説明まで拾うと機能しない
    const cooling = (a.content.match(/[^。\n]*流水[^。\n]*\d+\s*[〜~]?\s*\d*\s*分[^。\n]*/g) ?? [])
      // やけどの応急処置の文だけを対象にする。当初は「冷やし」を含む文を
      // 拾っていたが、保冷剤の「流水なら15〜20分で凍るので冷やし直せる」まで
      // 引っかかった。冷却時間という同じ形をしていても別の話
      .filter((s) => /やけど|火傷|患部/.test(s))
      .filter((s) => !/凍る|再凍結|凍結|溶け/.test(s));
    if (cooling.length === 0) continue;
    const blob = a.content;
    if (!/小範囲|狭い範囲/.test(blob))
      bad.push(`${a.slug}: 冷却時間を書いているが小範囲に限定していない`);
    if (!/低体温/.test(blob))
      bad.push(`${a.slug}: 冷却時間を書いているが冷やしすぎ（低体温）の注意が無い`);
  }
  assert.deepEqual(bad, [], bad.join("\n"));
});

test("記事本文で「体が小さいから」を機序として使っていない", () => {
  // 体格そのものは機序ではない。体重に対する体表面積の比、体温調節機能の
  // 未熟さ、体重あたりの呼吸量の多さ、が正しい説明
  const bad: string[] = [];
  for (const a of allArticles) {
    if (a.status !== "published") continue;
    for (const s of a.content.split(/[。\n]/)) {
      if (/体(が|格が)小さい/.test(s) && /冷え|体温|熱|呼吸|吸収|受け取/.test(s))
        bad.push(`${a.slug}: 「${s.trim().slice(0, 60)}」`);
    }
  }
  assert.deepEqual(bad, [], bad.join("\n"));
});

test("記事本文がディートの回避を安全策として勧めていない", () => {
  // 「ディート不使用のものが安心」は、年齢と回数を守れば使える成分を
  // 避けさせる書き方で、docs/repellent-age-standard.md と矛盾する
  const bad: string[] = [];
  for (const a of allArticles) {
    if (a.status !== "published") continue;
    for (const s of a.content.split(/[。\n]/)) {
      if (/ディート不使用[^。]*(安心|安全)|ディートを避け[^。]*(安心|安全)/.test(s))
        bad.push(`${a.slug}: 「${s.trim().slice(0, 60)}」`);
    }
  }
  assert.deepEqual(bad, [], bad.join("\n"));
});

test("冷却材による障害を「低温やけど」と呼んでいない", () => {
  // 2026-08-28 医師レビューでの指摘。用語の誤り。
  // 「低温やけど」は湯たんぽなど比較的低温の熱源による熱傷を指す。
  // 保冷剤や冷却プレートによる障害は「凍傷」「寒冷障害」であって、
  // やけどではない。冷やす道具の説明でこの語を使うと、対処も変わってくる
  const bad: string[] = [];
  for (const [slug, adv] of Object.entries(MEDICAL_ADVICE_MAP)) {
    const blob = adv.title + adv.body + adv.bullets.join("。");
    for (const s of blob.split(/[。]/)) {
      if (!/低温やけど/.test(s)) continue;
      if (/保冷剤|冷却プレート|冷やす|クーラー|凍/.test(s))
        bad.push(`${slug}: 冷却の文脈で「低温やけど」を使っている「${s.trim().slice(0, 60)}」`);
    }
  }
  assert.deepEqual(bad, [], bad.join("\n"));
});

test("低体温の対応に、着替えが無い場合の逃げ道が書かれている", () => {
  // 2026-08-28 医師レビューでの指摘。
  // 「濡れた衣類は最優先で脱がせる」だけだと、乾いた着替えが無い屋外で
  // 脱がせてさらに冷やすことになる。上から防水・保温する選択肢が要る
  for (const [slug, adv] of Object.entries(MEDICAL_ADVICE_MAP)) {
    const blob = adv.body + adv.bullets.join("。");
    if (!/低体温/.test(blob)) continue;
    if (!/濡れ/.test(blob)) continue;
    assert.ok(
      /着替えが無い|着替えがない|上から防水|上から保温/.test(blob),
      `${slug}: 濡れた衣類の扱いに、乾いた着替えが無い場合の指示が無い`
    );
  }
});

test("温かい飲み物を与える条件が書かれている", () => {
  // 意識障害や強い眠気があるときは誤嚥の危険がある。
  // 「意識がはっきりしているときだけ」では足りず、自分で飲み込めるかまで見る
  for (const [slug, adv] of Object.entries(MEDICAL_ADVICE_MAP)) {
    const blob = adv.body + adv.bullets.join("。");
    if (!/温かい.*飲み物|温かいノンアルコール/.test(blob)) continue;
    assert.ok(
      /飲み込め|むせず|誤嚥/.test(blob),
      `${slug}: 温かい飲み物を与える条件に、自分で飲み込めるかの確認が無い`
    );
  }
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
