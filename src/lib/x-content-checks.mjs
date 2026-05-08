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

import fs from "fs";
import path from "path";

// === NGワード辞書（account-config.json から読み込み + ハードコード補完）===

function loadNgWords() {
  const configPath = path.join(process.cwd(), "data", "account-config.json");
  if (fs.existsSync(configPath)) {
    const config = JSON.parse(fs.readFileSync(configPath, "utf-8"));
    return config.ngWords || {};
  }
  return {};
}

const _ng = loadNgWords();

/** 政治・宗教・差別・センシティブ系 */
const NG_POLITICAL = [
  ...(_ng.political || []),
  "選挙", "韓国人", "中国人", "在日", "天皇", "創価", "統一教会",
];

/** 薬機法・医療法 系 */
const NG_MEDICAL = [
  ...(_ng.medical || []),
  "ガンに", "病気が", "病気を", "アレルギーが治", "副作用なし", "医師推奨",
];

/** 景表法 系 */
const NG_LANDMARK = [
  ...(_ng.landmark || []),
  "圧倒的No.1", "最安値保証", "返金保証", "効果保証",
];

/** 誇大表現 */
const NG_HYPE = [
  ...(_ng.hype || []),
  "革命", "奇跡", "ヤバい", "神ギア",
];

/** 薬機法・医療法 厳格チェック用（doc_health_tip では block、他タイプでは warn） */
const NG_MEDICAL_STRICT = [
  "改善する", "改善できる", "予防できます",
  "診断", "処方", "投薬",
  "すべき",
  "飲んでください", "服用して",
  "治療法", "療法として",
];

/** AI臭い定型表現 */
const NG_TEMPLATE = [
  ...(_ng.template || []),
  "おすすめ",
];

/** 災害・事故・センシティブニュース系（news_comment 生成時に混入防止） */
const NG_NEWS_SENSITIVE = [
  "地震", "津波", "台風", "噴火", "洪水", "土砂崩れ",
  "死亡", "死者", "行方不明", "負傷", "重傷",
  "逮捕", "事件", "炎上", "スキャンダル", "謝罪",
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
 * @param {{ type?: string }} options - タイプ情報（doc_health_tip で厳格チェック）
 * @returns {{ ok: boolean, errors: string[], warnings: string[] }}
 */
export function checkXPostContent(text, options = {}) {
  const { type } = options;
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

  // 薬機法・医療法 厳格チェック
  for (const word of NG_MEDICAL_STRICT) {
    if (text.includes(word)) {
      if (type === "doc_health_tip") {
        errors.push(`[薬機法/医療法(厳格)] "${word}" を検出`);
      } else {
        warnings.push(`[医療表現注意] "${word}" を検出`);
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
 * gear_thread のスレッド全体をチェック
 * @param {string[]} tweets - ツイート配列
 * @param {{ type?: string }} options
 * @returns {{ ok: boolean, errors: string[], warnings: string[] }}
 */
export function checkThreadContent(tweets, options = {}) {
  const allErrors = [];
  const allWarnings = [];
  tweets.forEach((text, i) => {
    const check = checkXPostContent(text, options);
    for (const e of check.errors) allErrors.push(`[${i + 1}/${tweets.length}] ${e}`);
    for (const w of check.warnings) allWarnings.push(`[${i + 1}/${tweets.length}] ${w}`);
  });
  return { ok: allErrors.length === 0, errors: allErrors, warnings: allWarnings };
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
    /tag=camp78-22/.test(text)
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
    // URL除去: AIが指示を無視してtext内にURLを埋め込んだ場合に強制除去
    const cleanedText = (p.text || "")
      .replace(/https?:\/\/\S+/g, "")
      .replace(/\n{3,}/g, "\n\n")
      .trim();
    const hadUrl = cleanedText !== (p.text || "").trim();

    // PRラベル
    const labeled = ensurePrLabel(cleanedText, {
      articleUrl: p.url,
      hasAffiliate:
        p.type === "rakuten_sale" || p.type === "amazon_deal"
          ? true
          : undefined,
    });
    // バリデーション（タイプ情報を渡して厳格チェック対応）
    const check = checkXPostContent(labeled.text, { type: p.type });
    const errs = [...check.errors, ...check.warnings];
    if (hadUrl) errs.unshift("URL除去: text フィールドにURLが含まれていたため自動除去");
    return {
      ...p,
      text: labeled.text,
      prLabel: labeled.prLabel,
      validationErrors: errs.length > 0 ? errs.join(" / ") : undefined,
      _checkOk: check.ok,
    };
  });
}
