// 本文に直書きされたFAQセクションから Q&A を取り出す。
//
// 背景: 記事の faqs フィールドと本文のFAQセクションが二重表示になる問題があり、
// articles/[slug]/page.tsx では本文側を優先して faqs を空にしている。ただし
// その実装は表示とあわせて FAQPage JSON-LD も捨てていたため、本文にFAQを
// 直書きした47本（公開記事の44%）から構造化データが出ていなかった。
//
// 「ページに見えている内容と構造化データの不一致」を避けるという元の判断は
// 正しいので、不一致を消す方向を変える。本文から拾えば、出力される JSON-LD は
// 定義上まさに画面に見えている内容そのものになる。
//
// 表記は3通りある（2026-08-26時点の実データを全件確認した結果）。
//   ### 質問文              … 40本
//   **Q. 質問文**           …  6本
//   Q. 質問文               …  1本（field-rack-ranking）

export type ExtractedFaq = { question: string; answer: string };

// 本文中のFAQセクション見出し。
//
// 以前は「よくある質問」しか見ていなかった。そのため本文の見出しが「## FAQ」
// だった16本（最大収益記事の portable-cooler-fan-guide を含む）は判定から漏れ、
// 本文のFAQとシステム生成FAQが画面に二重で出ていた。ビルド出力のh2を数えて確認
// 済み。表記ゆれを全部拾う。
//
// 「## FAQサイトの作り方」のような別物を巻き込まないよう、FAQ語のあとは
// 行末か区切り文字であることを条件にする。
export const FAQ_HEADING_RE =
  /^##+ *(?:よくある(?:ご)?質問|よくある疑問|FAQ|Q ?& ?A)(?:$|[\s：:・\-–—ー～〜（()|｜、。]).*$/im;

// 「短すぎる回答はノイズだろう」と10字の下限を置いたら、「使えます。」のような
// 正当な短答が消えた。日本語の回答は5字でも成立する。ここで落としたいのは
// 回答が付いていない見出しだけなので、空でないことだけを条件にする。
const MIN_QUESTION_LENGTH = 2;
const MIN_ANSWER_LENGTH = 1;

/** Markdownの装飾を落として、構造化データに入れられる素のテキストにする */
function toPlainText(markdown: string): string {
  return markdown
    .replace(/\{\{[^}]*\}\}/g, " ") // {{product:id}} 等のショートコード
    .replace(/!\[[^\]]*\]\([^)]*\)/g, " ") // 画像
    .replace(/\[([^\]]*)\]\([^)]*\)/g, "$1") // リンクはテキストだけ残す
    .replace(/`([^`]*)`/g, "$1")
    .replace(/\*\*([^*]*)\*\*/g, "$1")
    .replace(/(^|[^*])\*([^*]+)\*/g, "$1$2")
    .replace(/^\s*[-*+]\s+/gm, "") // 箇条書きの記号
    .replace(/^\s*>\s?/gm, "")
    .replace(/\s*\n\s*/g, " ")
    .replace(/\s{2,}/g, " ")
    .trim();
}

/** 質問行から、飾りと通し番号（Q1. / Q. / 1. ）を取り除く */
function normalizeQuestion(raw: string): string {
  return toPlainText(raw)
    .replace(/^#+\s*/, "")
    .replace(/^Q\s*[0-9]*\s*[.．:：、]?\s*/i, "")
    .replace(/^[0-9]+\s*[.．:：、]\s*/, "")
    .trim();
}

/** 本文からFAQセクション本体（見出しの次行から、次のH2または区切り線まで）を切り出す */
function sliceFaqSection(content: string): string | null {
  const start = content.search(FAQ_HEADING_RE);
  if (start === -1) return null;

  const afterHeading = content.slice(start);
  const firstBreak = afterHeading.indexOf("\n");
  if (firstBreak === -1) return null;

  const body = afterHeading.slice(firstBreak + 1);

  // 次のH2、または水平線で終わり。どちらか早いほうを採る
  const candidates = [body.search(/^## /m), body.search(/^---\s*$/m)].filter(
    (i) => i !== -1
  );
  const end = candidates.length > 0 ? Math.min(...candidates) : body.length;
  return body.slice(0, end);
}

/**
 * 本文のFAQセクションから Q&A を取り出す。
 * FAQセクションが無い、または1件も取れなかった場合は空配列を返す。
 */
export function extractFaqsFromContent(content: string): ExtractedFaq[] {
  const section = sliceFaqSection(content || "");
  if (!section) return [];

  const lines = section.split("\n");
  const faqs: ExtractedFaq[] = [];
  let question: string | null = null;
  let answerLines: string[] = [];

  const flush = () => {
    if (question === null) return;
    // 「A. 〜」で書き始める記事があり、そのままだと構造化データの本文が
    // 「A. 同一シリーズです」のように始まってしまうので回答側の記号も落とす
    const answer = toPlainText(answerLines.join("\n")).replace(
      /^A\s*[0-9]*\s*[.．:：、]\s*/i,
      ""
    );
    if (
      question.length >= MIN_QUESTION_LENGTH &&
      answer.length >= MIN_ANSWER_LENGTH
    ) {
      faqs.push({ question, answer });
    }
    question = null;
    answerLines = [];
  };

  for (const line of lines) {
    const trimmed = line.trim();

    // 表記3通りのいずれか。1行まるごとが質問になっている行だけを見出しとみなす
    const isH3 = /^###+\s+\S/.test(trimmed);
    const isBoldQ = /^\*\*\s*Q\s*[0-9]*\s*[.．:：、]?[\s\S]*\*\*$/i.test(trimmed);
    const isPlainQ = /^Q\s*[0-9]*\s*[.．:：、]\s*\S/i.test(trimmed);

    if (isH3 || isBoldQ || isPlainQ) {
      flush();
      question = normalizeQuestion(trimmed);
      continue;
    }

    if (question !== null) answerLines.push(line);
  }
  flush();

  return faqs;
}
