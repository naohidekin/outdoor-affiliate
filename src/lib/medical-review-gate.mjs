// 医学的リスクを扱う記事が、医師の確認を経ずに公開されるのを防ぐ。
//
// 背景（2026-08-26）:
// このサイトは「現役小児科開業医 ギア男」を信頼の核にしている。一方で記事は
// 自動パイプラインが生成し、article-publisher-agent.js が自動公開している。
// その公開前チェックは「本文2,000字以上」「FAQ2問以上」の2つだけで、
// 医学的な内容は素通りしていた。生成プロンプトにも医学的な指示は無かった。
//
// 実際に起きていたこと:
//   - 暖房ハブは一酸化炭素を11回書きながら、やけどに一度も触れていなかった
//   - 虫よけ記事でディートの下限月齢が3種類（2ヶ月／6ヶ月／2歳）に分裂していた
// どちらも自動生成の産物で、医師のレビューで初めて見つかった。
//
// X投稿には薬機法・医療法のチェッカー（x-content-checks.mjs）があるのに、
// 記事側にだけ無かった。ここで埋める。

/**
 * 医学的リスクの語。ここに当たる記事は、医師アドバイス（MEDICAL_ADVICE_MAP）
 * を持っているべき、という判定にする。
 *
 * 語を増やすときの基準: 「読者が真似したときに健康被害が起こりうるか」。
 * 単に体の部位が出てくる、程度では入れない（誤検知が増えて機能しなくなる）。
 */
export const MEDICAL_RISK_TERMS = [
  { key: "一酸化炭素", re: /一酸化炭素|CO中毒|COチェッカー/ },
  { key: "やけど", re: /やけど|火傷|低温やけど/ },
  { key: "熱中症", re: /熱中症/ },
  { key: "低体温", re: /低体温|凍傷/ },
  { key: "誤飲", re: /誤飲|誤食/ },
  { key: "アナフィラキシー", re: /アナフィラキシー/ },
  { key: "マダニ", re: /マダニ/ },
  { key: "虫よけ成分", re: /ディート|DEET|イカリジン/ },
  { key: "乳幼児", re: /乳幼児|赤ちゃん/ },
];

/**
 * medicalAdviceData.ts に登録されている slug を、ソースを読んで取り出す。
 *
 * スクリプトは .mjs で動くため .ts をそのまま import できない。かといって
 * 登録slugの一覧を別ファイルに複製すると必ずズレる。ソースを唯一の正とし、
 * ここでは読み取るだけにする。
 *
 * 正規表現が実装とズレたら黙って「登録なし」になってしまうので、
 * tests/medical-review-gate.test.ts が実際の MEDICAL_ADVICE_MAP と
 * 一致することを検証している。
 */
export function readMedicalAdviceSlugs(fs, sourcePath) {
  const src = fs.readFileSync(sourcePath, "utf8");
  const slugs = new Set();
  for (const m of src.matchAll(/^ {2}"([a-z0-9-]+)":\s*\{/gm)) slugs.add(m[1]);
  return slugs;
}

/** 記事が触れている医学リスクの一覧を返す */
export function detectMedicalRisks(content) {
  const text = String(content || "");
  return MEDICAL_RISK_TERMS.filter((t) => t.re.test(text)).map((t) => t.key);
}

/**
 * 公開してよいかを判定する。
 *
 * @param {{slug:string, content:string}} article
 * @param {(slug:string)=>boolean} hasMedicalAdvice 医師アドバイスの有無
 * @param {Set<string>} grandfathered 猶予中のslug（既存記事）
 * @returns {{ ok:boolean, risks:string[], reason?:string, grandfathered?:boolean }}
 */
export function reviewArticleForPublish(article, hasMedicalAdvice, grandfathered) {
  const risks = detectMedicalRisks(article.content);
  if (risks.length === 0) return { ok: true, risks };
  if (hasMedicalAdvice(article.slug)) return { ok: true, risks };

  // 既存記事は止めない。止めると、既に公開済みのものを更新するたびに
  // パイプラインが詰まり、「とりあえず猶予リストに足す」運用に流れる
  if (grandfathered && grandfathered.has(article.slug)) {
    return {
      ok: true,
      risks,
      grandfathered: true,
      reason: `医師アドバイス未登録（猶予中）: ${risks.join("・")}`,
    };
  }

  return {
    ok: false,
    risks,
    reason:
      `医学的リスクを扱っているのに医師アドバイスが未登録です（${risks.join("・")}）。` +
      `src/lib/medicalAdviceData.ts に "${article.slug}" を追加してください。` +
      `内容は医師の確認を経てから公開してください。`,
  };
}
