/**
 * X投稿のNGワード/誇大表現/PRラベル チェッカー
 *
 * 生成API/CLIスクリプトの保存直前に必ず実行する。
 * 違反検出時は呼び出し側で:
 *   - status="draft" を強制（自動承認をブロック）
 *   - validationErrors フィールドにメッセージを記録
 *
 * 規則の根拠:
 *   - 薬機法/医療法: 効能効果の暗示・治療を匂わせる表現
 *   - 景表法: 「最安」「No.1」など根拠のない優良誤認
 *   - 政治・差別・センシティブ: 炎上回避
 *   - 誇大表現: Lake & Sky トーンと矛盾
 */

// === NGワード辞書 ===

/** 政治・宗教・差別・センシティブ系 */
const NG_POLITICAL = [
  "自民党", "立憲", "共産党", "公明党", "維新", "選挙",
  "韓国人", "中国人", "在日",
  "天皇", "創価", "統一教会",
];

/** 災害・事故・センシティブニュース系（news_comment 生成時に混入防止） */
const NG_NEWS_SENSITIVE = [
  "地震", "津波", "台風", "噴火", "洪水", "土砂崩れ",
  "死亡", "死者", "行方不明", "負傷", "重傷",
  "逮捕", "事件", "炎上", "スキャンダル", "謝罪",
];

/** 薬機法・医療法 系（健康効果・治療効果を匂わせる表現） */
const NG_MEDICAL = [
  "効きます", "効く", "治る", "治す", "痩せる",
  "ガンに", "病気が", "病気を", "アレルギーが治",
  "副作用なし", "医師推奨",
];

/** 景表法 系（根拠のない優良誤認） */
const NG_LANDMARK = [
  "業界No.1", "日本一", "世界一", "圧倒的No.1",
  "最安値保証", "返金保証", "効果保証",
];

/** 誇大表現（Lake & Sky トーンと矛盾） */
const NG_HYPE = [
  "最高",
  "最強",
  "絶対",
  "神",
  "完全",
  "100%",
  "必ず",
  "今すぐ",
  "間違いなく",
  "革命",
  "奇跡",
  "ヤバい",
  "神ギア",
];

/** AI臭い定型表現 */
const NG_TEMPLATE = [
  "してみてはいかがでしょうか",
  "をご紹介します",
  "についてまとめました",
  "おすすめ", // 「おすすめ◯選」を弾くため厳しめ
  "徹底比較",
  "完全ガイド",
];

const CATEGORIES = [
  { name: "政治・宗教・差別", list: NG_POLITICAL, level: "block" },
  { name: "薬機法/医療法", list: NG_MEDICAL, level: "block" },
  { name: "景表法", list: NG_LANDMARK, level: "block" },
  // 誇大表現は Lake & Sky トーン徹底のため block 扱い（draft強制）
  { name: "誇大表現", list: NG_HYPE, level: "block" },
  // ニュース系センシティブ（news_comment 生成時の混入防止）
  { name: "災害・事故・炎上", list: NG_NEWS_SENSITIVE, level: "block" },
  // AI定型は warn のみ（一字一致だと拾いすぎる可能性があるため）
  { name: "AI定型", list: NG_TEMPLATE, level: "warn" },
];

/**
 * 投稿テキストをチェック
 * @param {string} text
 * @returns {{ ok: boolean, errors: string[], warnings: string[] }}
 */
export function checkXPostContent(text) {
  const errors = [];
  const warnings = [];
  if (!text || typeof text !== "string") {
    return { ok: false, errors: ["text が空です"], warnings: [] };
  }

  for (const cat of CATEGORIES) {
    for (const word of cat.list) {
      if (text.includes(word)) {
        const msg = `[${cat.name}] "${word}" を検出`;
        if (cat.level === "block") errors.push(msg);
        else warnings.push(msg);
      }
    }
  }

  // 文字数チェック (X 280字制限)
  // ※ 厳密な weighted character count ではないが概算
  const len = [...text].length;
  if (len > 280) {
    errors.push(`文字数オーバー: ${len}/280`);
  }

  return { ok: errors.length === 0, errors, warnings };
}

/**
 * アフィリエイト/外部リンクを含むかどうか
 * @param {string} text
 */
export function containsAffiliate(text) {
  if (!text) return false;
  return (
    text.includes("hb.afl.rakuten.co.jp") ||
    text.includes("amzn.to") ||
    text.includes("amazon.co.jp/dp/") ||
    /tag=nao78-22/.test(text)
  );
}

/**
 * 必要に応じて "*広告を含みます" ラベルを末尾に付与
 * @param {string} text
 * @param {{ hasAffiliate?: boolean, articleUrl?: string|null }} opts
 * @returns {{ text: string, prLabel: boolean }}
 */
export function ensurePrLabel(text, opts = {}) {
  const hasAffiliate =
    opts.hasAffiliate ?? containsAffiliate(text + (opts.articleUrl || ""));
  if (!hasAffiliate) return { text, prLabel: false };
  if (text.includes("広告を含みます") || text.includes("*広告")) {
    return { text, prLabel: true };
  }
  return { text: text + "\n\n*広告を含みます", prLabel: true };
}

/**
 * 生成済み投稿配列にチェックとPRラベル付与をまとめて適用
 * @param {Array<{text: string, url?: string|null, type?: string}>} posts
 * @returns {Array<{text: string, prLabel: boolean, validationErrors?: string, _checkOk: boolean}>}
 */
export function applyChecksAndLabels(posts) {
  return posts.map((p) => {
    // PRラベル
    const labeled = ensurePrLabel(p.text, {
      articleUrl: p.url,
      hasAffiliate:
        p.type === "rakuten_sale" || p.type === "amazon_deal"
          ? true
          : undefined,
    });
    // バリデーション
    const check = checkXPostContent(labeled.text);
    const errs = [...check.errors, ...check.warnings];
    return {
      ...p,
      text: labeled.text,
      prLabel: labeled.prLabel,
      validationErrors: errs.length > 0 ? errs.join(" / ") : undefined,
      _checkOk: check.ok,
    };
  });
}
