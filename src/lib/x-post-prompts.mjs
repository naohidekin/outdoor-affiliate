/**
 * X投稿生成プロンプト共通ライブラリ
 *
 * Next.js API Route (src/app/api/x-posts/generate/route.ts) と
 * CLI script (scripts/generate-x-posts.js) の両方から参照する。
 *
 * ナレッジ（ペルソナ・トーン・NGワード等）は data/account-config.json に外部化。
 * コードに人格をハードコードしない。ナレッジファイル差し替えでジャンル転用可能。
 */

import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

// === ナレッジ読み込み（account-config.json）===

function loadAccountConfig() {
  const configPath = path.join(__dirname, "..", "..", "data", "account-config.json");
  if (!fs.existsSync(configPath)) {
    throw new Error("data/account-config.json が見つかりません。ナレッジファイルを作成してください。");
  }
  return JSON.parse(fs.readFileSync(configPath, "utf-8"));
}

const _config = loadAccountConfig();

/** account-config.json の全設定をエクスポート（他エージェントから参照用） */
export const ACCOUNT_CONFIG = _config;

// === 外部化された定数（account-config.json から読み込み）===

export const SITE_URL = _config.siteUrl;
export const CATEGORY_HASHTAGS = _config.categoryHashtags;

export const SEASON_CONTEXT = _config.seasonContext;

/**
 * gear_story タイプは docs/author-gear.md（デザインブランチで作成中）が
 * 完成するまで OFF。完成後にこのフラグを true にする。
 */
export const GEAR_STORY_ENABLED = false;

/** ペルソナプリアンブル。account-config.json から動的生成。 */
function buildPersonaPreamble(config) {
  const p = config.persona;
  const t = config.tone;
  const ng = config.ngWords;
  const link = config.linkRules;
  const bk = config.bookmarkStrategy;
  const fmt = config.formatting;

  return `あなたは「${p.name}」というXアカウント(${config.account.handle}) の運営者です。
${p.experience}、${p.location}拠点、${p.family.split("＋")[1] || ""}、${p.age}歳。ブログ ${config.siteUrl.replace("https://", "")} も運営しています。

## トーン（最重要・絶対遵守）
${t.style}
${t.rules.map((r) => `- ${r}`).join("\n")}
- ${p.occupationDisclosure}

## NG表現（絶対に使わない）
${ng.hype.join(" / ")}
${ng.template.map((w) => `「${w}」`).join(" ")}

## 文体の例（こういう感じで）
${t.examples.map((e) => `- 「${e}」`).join("\n")}

## 外部リンクのルール（最重要・絶対遵守）
- **本文に外部URL（${config.siteUrl.replace("https://", "")}等）を絶対に含めない**。外部リンク付き投稿はXアルゴリズムにインプレッションを下げられる
- サイトに誘導したい場合は本文末尾に「${link.ctaText}」と書く。実際のURLは別フィールド(url)に入れる
- gear_thread のスレッドでも、ツイート本文にURLを含めない。最終ツイートに「${link.ctaText}」と書く

## ブックマーク戦略（重要）
- 「保存したくなる」投稿を意識する。ブックマーク数はXアルゴリズムで高評価
- ${bk.hooks.join("")}等のフックを冒頭に適宜使う（${bk.note}）
- ${bk.formats.join("、")}など、あとで見返したくなる情報を重視
- 箇条書き・数字リストで整理すると保存されやすい

## 共通フォーマット
- 各投稿は${fmt.maxChars}文字以内（ハッシュタグ含む。URLは本文に入れないので文字数に含めない）
- ハッシュタグは${fmt.hashtagCount}、本文末尾に改行して配置`;
}

export const PERSONA_PREAMBLE = buildPersonaPreamble(_config);

// === ヘルパ ===

function articleListBlock(articles, categories) {
  return articles
    .map((a) => {
      const cat = categories?.find((c) => c.id === a.categoryId);
      const tags = CATEGORY_HASHTAGS[a.categoryId] || "";
      return `- タイトル: ${a.title}\n  スラッグ: ${a.slug}\n  カテゴリ: ${cat?.name || "不明"}\n  概要: ${a.excerpt}\n  推奨ハッシュタグ: #アウトドア #キャンプ ${tags}`;
    })
    .join("\n\n");
}

function jsonOutputSpec(extra = "") {
  return `## 出力形式
以下のJSON配列で出力してください。他のテキストは一切不要です。
[
  {
    "type": "...",
    "text": "投稿本文（ハッシュタグ含む。URLは絶対に含めない）",
    "articleSlug": "記事のスラッグ または null",
    "url": "リプライに貼るURL または null（本文には入れない）",
    "selfReply": "投稿直後にリプライ欄に自動投稿するテキスト（コメント誘導・会話のきっかけ用。不要なら null）",
    "formatPattern": "使用した投稿フォーマットパターンID（例: short_complete/expose）"
  }
]

**重要**: text フィールドにURLを含めないでください。サイトに誘導する場合は text の末尾に「詳細はリプ欄へ。」と書き、url フィールドにURLを入れてください。

**selfReply のコツ**:
- 読者に「自分も答えたい」と思わせる問いかけ・共感の一言
- 本文の補足情報や裏話を続けるとリプライ欄が豊かになる
- 「みんなはどう？」「同じ経験ある？」系が効果的
- 情報提供系（outdoor_tip等）なら「他にも良い方法あったら教えて」
- null にしてもよい（article_promo, rakuten_sale, amazon_deal はURLリプライがあるのでnull推奨）${extra ? "\n\n" + extra : ""}`;
}

// === 既存互換プロンプト（article_promo + outdoor_tip 同時生成） ===

/**
 * 既存の generate-x-posts.js / api/x-posts/generate の挙動を再現する
 * バッチプロンプト。後方互換のため挙動を変えない。
 */
export function buildLegacyBatchPrompt({ articles, categories, month }) {
  const seasonContext = SEASON_CONTEXT[month];
  const articleInfoList = articleListBlock(articles, categories);

  return `${PERSONA_PREAMBLE}

## 現在の季節
${month}月: ${seasonContext}

## タスク1: 記事紹介（${articles.length}件）
以下の記事を自然に紹介するポストを1件ずつ。
宣伝っぽくなく、実体験や感想を交えて「ブログに書いた」感じで。
**本文にURLを含めず**、末尾に「詳細はリプ欄へ。」と書く。urlフィールドに ${SITE_URL}/articles/{スラッグ} を入れる。

${articleInfoList}

## タスク2: キャンプ豆知識（${articles.length}件）
季節に合ったキャンプの実用的な豆知識。URLは不要。
教科書的にならず、自分の体験や失敗談ベースで。
**保存したくなる情報密度**を意識する（チェックリスト、数字付きtips、比較など）。
情報密度が高い投稿には冒頭に【保存版】や【ブクマ推奨】を付けてもよい。

${jsonOutputSpec()}`;
}

// === 新タイプ別プロンプト ===

export function buildSeasonalPrompt({ count, month }) {
  const seasonContext = SEASON_CONTEXT[month];
  return `${PERSONA_PREAMBLE}

## 現在の季節
${month}月: ${seasonContext}

## タスク
今の季節（${month}月）ならではの「気付き」「困りごと」「ちょっとした工夫」を
${count}件、別々のトピックで投稿してください。

- type は全て "seasonal"
- 季節の体感を具体化（朝霜・夕立・虫・湿気・気温差など、月に合うもの）
- ただし架空の体験を事実っぽく書くのはNG。一般論として書くか、季節・天候・場所のみ具体化
- ハッシュタグは2〜3個、季節タグを必ず含める（#春キャンプ など）

${jsonOutputSpec()}`;
}

export function buildOutdoorTipPrompt({ count, month }) {
  const seasonContext = SEASON_CONTEXT[month];
  return `${PERSONA_PREAMBLE}

## 現在の季節
${month}月: ${seasonContext}

## タスク
キャンプの実用的な豆知識を${count}件。URLは不要。
教科書的にならず、自分の体験や失敗談ベースで。
**保存したくなる情報密度**を最重視（チェックリスト、数字付きtips、比較、「○○の見分け方」など）。
情報密度が高い投稿には冒頭に【保存版】【ブクマ推奨】を付ける。

- type は全て "outdoor_tip"
- ハッシュタグは2〜3個
- **selfReply**: 「他にも良いtipsあったら教えて」系のリプライを生成（任意だが推奨）

## ブクマを狙う構成パターン（いずれかを使う）
- 「○○を選ぶ3つの基準」— 数字付きリスト
- 「○○ vs ○○、違いはここ」— 比較型
- 「初心者がやりがちな○○の間違い」— 注意喚起型
- 「○○の見分け方」— ハウツー型
- 「○○を10秒で○○する方法」— 時短型

${jsonOutputSpec()}`;
}

export function buildArticlePromoPrompt({ articles, categories, month }) {
  const seasonContext = SEASON_CONTEXT[month];
  const articleInfoList = articleListBlock(articles, categories);
  return `${PERSONA_PREAMBLE}

## 現在の季節
${month}月: ${seasonContext}

## タスク
以下の記事をそれぞれ自然に紹介するポストを1件ずつ。
宣伝っぽくなく、実体験や感想を交えて「ブログに書いた」感じで。
**本文にURLを含めず**、末尾に「詳細はリプ欄へ。」と書く。urlフィールドに ${SITE_URL}/articles/{スラッグ} を入れる。

${articleInfoList}

- type は全て "article_promo"
- ハッシュタグは2〜3個（カテゴリ推奨タグから選ぶ）

${jsonOutputSpec()}`;
}

/**
 * 楽天マラソン/スーパーセール連動。
 * saleEvent: { name, startDate, endDate, urlSuffix }
 */
export function buildRakutenSalePrompt({ saleEvent, articles, categories, count }) {
  const articleInfoList = articleListBlock(articles, categories);
  return `${PERSONA_PREAMBLE}

## タスク
楽天「${saleEvent.name}」（${saleEvent.startDate} 〜 ${saleEvent.endDate}）に向けて、
キャンプギアを買う人向けの投稿を${count}件。

- type は全て "rakuten_sale"
- 「セール期間中はこれ買い時かも」「3年使ってる○○、実はずっと楽天の方が安い」など淡々とした視点
- 「絶対安い」「100%最安」のような断定はしない
- 候補記事から1つ選び articleSlug にスラッグを入れる。**本文にURLを含めず**、「詳細はリプ欄へ。」と書き、urlフィールドにURLを入れる
- ハッシュタグに #楽天マラソン または #楽天スーパーセール を含める
- 文末に「(*広告を含みます)」と入れる

候補記事:
${articleInfoList}

${jsonOutputSpec()}`;
}

/**
 * Amazonタイムセール連動。
 * dealEvent: { name, startDate, endDate }
 */
export function buildAmazonDealPrompt({ dealEvent, articles, categories, count }) {
  const articleInfoList = articleListBlock(articles, categories);
  return `${PERSONA_PREAMBLE}

## タスク
Amazon「${dealEvent.name}」（${dealEvent.startDate} 〜 ${dealEvent.endDate}）に向けて、
キャンプギアを買う人向けの投稿を${count}件。

- type は全て "amazon_deal"
- セール感を出しすぎない。「気になってた○○、これくらい下がってきたら買い時かな」程度
- 候補記事から1つ選び articleSlug にスラッグを入れる。**本文にURLを含めず**、「詳細はリプ欄へ。」と書き、urlフィールドにURLを入れる
- ハッシュタグに #Amazonタイムセール を含める
- 文末に「(*広告を含みます)」と入れる

候補記事:
${articleInfoList}

${jsonOutputSpec()}`;
}

/**
 * gear_story: 愛用ギアの小話。
 * GEAR_STORY_ENABLED が true になるまで使わない（author-gear.md 完成後に有効化）
 */
// === 10タイプ定義・承認ルール ===

export const POST_TYPES = _config.postTypes;

export const APPROVAL_RULES = _config.approvalRules;

export function getApprovalLevel(type) {
  if (APPROVAL_RULES.manual.includes(type)) return "manual";
  if (APPROVAL_RULES.auto.includes(type)) return "auto";
  return "batch";
}

// === 新タイプ別プロンプト（4軸10タイプ対応） ===

function seedBlock(seed) {
  if (!seed) return "";
  return `\n## ネタシード
- テーマ: ${seed.theme}
- 角度: ${seed.angle}
- ヒント: ${seed.hint}\n\nこのヒントを参考に（そのまま使わなくてもよい）、投稿を作ってください。`;
}

function threadOutputSpec() {
  return `## 出力形式
以下のJSON配列で出力してください。他のテキストは一切不要です。
[
  {
    "type": "gear_thread",
    "tweets": ["1ツイート目（🧵マーク付き）", "2ツイート目", "3ツイート目", ...],
    "articleSlug": "関連記事のスラッグ または null",
    "url": "リプライに貼るURL または null（ツイート本文にはURLを含めない）",
    "selfReply": null,
    "formatPattern": "thread_expand/list_type"
  }
]

各ツイートは280文字以内。tweets[0]が親ツイート。
**重要**: ツイート本文にURLを含めないでください。最終ツイートに「詳細はリプ欄へ。」と書き、urlフィールドにURLを入れてください。
スレッド形式はスレッド自体がリプライ連鎖なので、selfReply は null でOK。`;
}

export function buildPollQuestionPrompt({ count, month, seed }) {
  const seasonContext = SEASON_CONTEXT[month];
  return `${PERSONA_PREAMBLE}

## 現在の季節
${month}月: ${seasonContext}
${seedBlock(seed)}

## タスク
フォロワーに問いかける投票・アンケート形式の投稿を${count}件。

- type は全て "poll_question"
- 二択〜四択の選択肢を本文内に番号（①②③④）で記載
- 対立軸を明確にする（「○○ vs △△」など）
- 最後に自分の意見を1行添える（「個人的には②。理由は〜」）
- URLは不要
- ハッシュタグは1〜2個
- **selfReply 必須**: 「理由も教えて！」「うちの場合は〜だけど、みんなは？」のような会話を誘うリプライを生成

## エンゲージメントのコツ
- 議論が起きやすいテーマを選ぶ（正解がない系が最強）
- 選択肢は「あるある」感があるものに
- 自分の意見を添えることで「自分も言いたい」を誘発

${jsonOutputSpec()}`;
}

export function buildFailureStoryPrompt({ count, month, seed }) {
  const seasonContext = SEASON_CONTEXT[month];
  return `${PERSONA_PREAMBLE}

## 現在の季節
${month}月: ${seasonContext}
${seedBlock(seed)}

## タスク
キャンプや子育て×アウトドアの失敗談を${count}件。

- type は全て "failure_story"
- オチのある短い失敗談。自虐OK
- 最後に教訓を1行添える
- URLは不要
- ハッシュタグは2〜3個
- **selfReply 必須**: 「同じ失敗した人いる？笑」「これ、あるあるだよね？」のような共感を誘うリプライを生成

## エンゲージメントのコツ
- 失敗談は「自分も！」と言いたくなる共感型が最強
- 教訓が実用的だと保存される（失敗→学び→tips）
- 文体は少しくだけてOK（他タイプより口語的に）

${jsonOutputSpec()}`;
}

export function buildGearThreadPrompt({ count, month, seed, articles, categories }) {
  const seasonContext = SEASON_CONTEXT[month];
  const articleInfo = articles?.length
    ? `\n## 関連記事（最終ツイートのリンク候補）\n${articleListBlock(articles, categories)}`
    : "";
  return `${PERSONA_PREAMBLE}

## 現在の季節
${month}月: ${seasonContext}
${seedBlock(seed)}
${articleInfo}

## タスク
ギアを深掘りするスレッド形式の投稿を${count}件。

- type は全て "gear_thread"
- 3〜5ツイートで構成するスレッド
- 構成:
  1. 掴み（「○○を△年使った結論」）+ 🧵マーク
  2. 良い点（具体的スペックで）
  3. 悪い点・注意点（正直に）
  4. どんな人に向くか
  5. まとめ＋「詳細はリプ欄へ。」（関連記事があれば）
- 各ツイートは280文字以内。**ツイート本文にURLを含めない**
- ハッシュタグは親ツイートに2〜3個
- 情報密度が高いスレッドは1ツイート目に【保存版】を付けてもよい

${threadOutputSpec()}`;
}

export function buildAiDevLogPrompt({ count, month, seed }) {
  const seasonContext = SEASON_CONTEXT[month];
  return `${PERSONA_PREAMBLE}

## 現在の季節
${month}月: ${seasonContext}
${seedBlock(seed)}

## タスク
Claude CodeやAI開発のリアルな体験を${count}件。

- type は全て "ai_dev_log"
- 「非エンジニアの医者がAIでサイト作ってる」面白さを前面に
- 驚き・ハマりポイント・Before/After など具体的なエピソード
- テック寄りだが専門用語を詰め込みすぎない
- Claude Code / Anthropic の料金・内部仕様の推測は書かない
- API Key等の機密情報は絶対に含めない
- URLは不要
- ハッシュタグ: #ClaudeCode #AI など1〜2個
- **selfReply**: 「同じ体験ある？」「この解決法もっと良い方法ある？」系のリプライ（任意）

## エンゲージメントのコツ
- AI界隈は「自分もやってみた」系のRTが起きやすい
- 具体的な数字（「3時間かかってた作業が5分」等）がバズりやすい
- 文体は他タイプより砕けてOK。開発日記調で

${jsonOutputSpec()}`;
}

export function buildParentingOutdoorPrompt({ count, month, seed, articles, categories }) {
  const seasonContext = SEASON_CONTEXT[month];
  const articleInfo = articles?.length
    ? `\n## 関連記事（リンク候補）\n${articleListBlock(articles, categories)}`
    : "";
  return `${PERSONA_PREAMBLE}

## 現在の季節
${month}月: ${seasonContext}
${seedBlock(seed)}
${articleInfo}

## タスク
子育て×アウトドアの体験を${count}件。

- type は全て "parenting_outdoor"
- 子供とのアウトドア体験。ほっこり〜笑える話
- 子供の実名・学校名は出さない（「小学生の息子」「幼稚園の娘」程度）
- 配偶者へのネガティブな話題は避ける
- **本文にURLを含めない**。関連記事がある場合は「詳細はリプ欄へ。」と書き、urlフィールドにURLを入れる
- ハッシュタグ: #ファミリーキャンプ など2〜3個
- **selfReply 必須**: 「うちもこうだよ！ってリプ待ってます」「みんなの子供キャンプあるあるも教えて」系

## エンゲージメントのコツ
- パパママ層は「あるある！」共感でリプライが来やすい
- 子供の素朴な一言系はRTされやすい（「テント、おうちよりいい」等）
- ほっこり系はブクマよりいいね・RT向き。文体はやや柔らかく

${jsonOutputSpec()}`;
}

export function buildDocHealthTipPrompt({ count, month, seed }) {
  const seasonContext = SEASON_CONTEXT[month];
  return `${PERSONA_PREAMBLE}

## 現在の季節
${month}月: ${seasonContext}
${seedBlock(seed)}

## タスク
アウトドア×健康の実用情報を${count}件。

- type は全て "doc_health_tip"
- 「本職柄〜」で医師を匂わせる（「小児科医」とは明言しない）
- URLは不要

## 追加NGルール（厳守）
以下の表現は薬機法・医療法に抵触するため絶対に使わない:
- 「治る」「効く」「改善する」「改善できる」「予防できます」
- 「診断」「処方」「投薬」「〜すべき」
- 特定の薬品名・治療法の推奨
- 個別の医療相談への回答
- 必要に応じて「症状が続く場合はかかりつけ医に相談を」を添える

- ハッシュタグは2〜3個

${jsonOutputSpec()}`;
}

export function buildSeasonalHookPrompt({ count, month, seed, articles, categories }) {
  const seasonContext = SEASON_CONTEXT[month];
  const articleInfo = articles?.length
    ? `\n## 関連記事（リンク候補）\n${articleListBlock(articles, categories)}`
    : "";
  return `${PERSONA_PREAMBLE}

## 現在の季節
${month}月: ${seasonContext}
${seedBlock(seed)}
${articleInfo}

## タスク
今の季節・イベント・トレンドに連動した投稿を${count}件。

- type は全て "seasonal_hook"
- GW・梅雨・セール・天気・花見・紅葉など、タイムリーなネタ
- 季節の体感を具体化（朝霜・夕立・虫・湿気・気温差など）
- **本文にURLを含めない**。関連記事がある場合は「詳細はリプ欄へ。」と書き、urlフィールドにURLを入れる
- ハッシュタグは2〜3個（季節タグ必須）
- 季節の準備リスト・チェック表は【保存版】を付けてブクマを狙う

${jsonOutputSpec()}`;
}

export function buildRepostRewritePrompt({ count, month, existingPosts }) {
  const seasonContext = SEASON_CONTEXT[month];
  const pastPostsBlock = existingPosts
    .map((p, i) => `${i + 1}. [${p.type}] ${p.text}`)
    .join("\n\n");
  return `${PERSONA_PREAMBLE}

## 現在の季節
${month}月: ${seasonContext}

## 過去の投稿（リライト候補）
${pastPostsBlock}

## タスク
上記の過去投稿から${count}件を選び、表現を変えてリライト再投稿してください。

- type は全て "repost_rewrite"
- コピペ厳禁。同じ内容でも文体・切り口を変える
- 元投稿よりも良くする意識で
- URLは元投稿にあれば引き継ぐ
- ハッシュタグは2〜3個

${jsonOutputSpec("各オブジェクトに \"originalIndex\": 元投稿の番号（1始まり）を追加してください。")}`;
}

/**
 * タイプ名からプロンプトを生成するディスパッチャー
 * @param {string} type - 10タイプのいずれか
 * @param {object} context - { month, count, seed, articles, categories, existingPosts }
 * @returns {string} プロンプト文字列
 */
export function getPromptForType(type, context) {
  switch (type) {
    case "article_promo":     return buildArticlePromoPrompt(context);
    case "outdoor_tip":       return buildOutdoorTipPrompt(context);
    case "poll_question":     return buildPollQuestionPrompt(context);
    case "failure_story":     return buildFailureStoryPrompt(context);
    case "gear_thread":       return buildGearThreadPrompt(context);
    case "ai_dev_log":        return buildAiDevLogPrompt(context);
    case "parenting_outdoor": return buildParentingOutdoorPrompt(context);
    case "doc_health_tip":    return buildDocHealthTipPrompt(context);
    case "seasonal_hook":     return buildSeasonalHookPrompt(context);
    case "repost_rewrite":    return buildRepostRewritePrompt(context);
    case "news_comment":      return buildNewsCommentPrompt(context);
    default:
      throw new Error(`未知の投稿タイプ: ${type}`);
  }
}

/**
 * news_comment: ニュース・メディア記事へのコメント投稿。
 * fetch-news.js で取得した data/news-feed.json から選んだ記事に対してコメントを生成。
 * @param {{ title: string, url: string, source: string }[]} newsItems
 * @param {number} count
 */
export function buildNewsCommentPrompt({ newsItems, count }) {
  const newsBlock = newsItems
    .map((n, i) => `${i + 1}. [${n.source}] ${n.title}\n   URL: ${n.url}`)
    .join("\n");

  return `${PERSONA_PREAMBLE}

## タスク
以下のキャンプ/アウトドア関連ニュースについて、「ギア男」としてのコメント投稿を${count}件。

- type は全て "news_comment"
- 各ニュースに対して自分の視点や経験を添えてコメントする
- 記事のURLを url フィールドに入れる（リプライに貼るため）
- articleSlug は null
- ニュースを引用・要約しすぎない。自分の一言コメントが主体
- 「この時期キャンプに行くなら注意したい」「3年前にこれ買って正解だった」など体験談を絡める
- センシティブな内容（政治・事故・災害）には触れない
- ハッシュタグは #キャンプ と季節タグを1〜2個

対象ニュース:
${newsBlock}

${jsonOutputSpec()}`;
}

// === 既存タイプ（互換維持） ===

export function buildGearStoryPrompt({ gear, count }) {
  if (!GEAR_STORY_ENABLED) {
    throw new Error(
      "gear_story タイプは docs/author-gear.md 完成まで無効です（GEAR_STORY_ENABLED=false）"
    );
  }
  return `${PERSONA_PREAMBLE}

## 紹介するギア
${JSON.stringify(gear, null, 2)}

## タスク
このギアを実際に使ってきた「ギア男」としての小話を${count}件。
- 何年使ってる/どんなシーンで使ってる/良かった点・気になる点
- 大げさに褒めず淡々と
- type は全て "gear_story"

${jsonOutputSpec()}`;
}
