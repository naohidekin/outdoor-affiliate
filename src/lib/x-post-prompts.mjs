/**
 * X投稿生成プロンプト共通ライブラリ
 *
 * Next.js API Route (src/app/api/x-posts/generate/route.ts) と
 * CLI script (scripts/generate-x-posts.js) の両方から参照する。
 *
 * Lake & Sky トーン（淡々として知的、煽らない）を全プロンプトに適用する。
 * 詳細は CLAUDE.md「X 投稿のトーン」セクション参照。
 */

// === 定数 ===

export const SITE_URL = "https://camp-gear-lab.com";

export const CATEGORY_HASHTAGS = {
  tent: "#テント #ファミキャン",
  light: "#ランタン #キャンプギア",
  "sleeping-bag": "#シュラフ #寝袋",
  burner: "#バーナー #キャンプ飯",
  backpack: "#登山 #バックパック",
  wear: "#アウトドアウェア #レインウェア",
  shoes: "#トレッキングシューズ #登山靴",
};

export const SEASON_CONTEXT = {
  1: "冬キャンプシーズン。防寒対策、冬用シュラフ、薪ストーブが話題",
  2: "冬キャンプ後半。春キャンプの準備が始まる時期",
  3: "春キャンプシーズン開始。花見キャンプ、新生活でキャンプデビュー",
  4: "春キャンプ本番。GWキャンプの計画時期。朝晩の寒暖差に注意",
  5: "GWキャンプ。新緑の季節。虫対策が必要になり始める",
  6: "梅雨シーズン。雨キャンプの準備、レインウェア選び",
  7: "夏キャンプ開始。暑さ対策、水遊び、虫除け必須",
  8: "夏キャンプ本番。高原キャンプ、川遊び、お盆キャンプ",
  9: "秋キャンプ開始。涼しくなり始め、焚き火が気持ちいい季節",
  10: "秋キャンプ本番。紅葉キャンプ、焚き火、温かい料理",
  11: "秋冬の境目。防寒ギアの見直し、冬キャンプ準備",
  12: "冬キャンプシーズン突入。年末キャンプ、冬装備の確認",
};

/**
 * gear_story タイプは docs/author-gear.md（デザインブランチで作成中）が
 * 完成するまで OFF。完成後にこのフラグを true にする。
 */
export const GEAR_STORY_ENABLED = false;

/** Lake & Sky トーンとペルソナ。すべての生成プロンプトの先頭に挿入する */
export const PERSONA_PREAMBLE = `あなたは「ギア男」というXアカウント(@camp_gear_lab) の運営者です。
キャンプ歴10年、長野拠点、2児の父、37歳。ブログ camp-gear-lab.com も運営しています。

## トーン（最重要・絶対遵守）
このアカウントは「Lake & Sky」（白×青×清涼感）のデザイン方針と呼応した、
**淡々として知的、煽らない**ポストをします。

- 断定より「個人的には〜」「3年使った結論から言うと〜」「うちの環境では〜」型を優先
- 体言止め・倒置・口語的省略を控えめに使う。句読点を多用しない
- 絵文字は0〜1個。連打しない。顔文字は使わない
- 一人称は控えめに
- 教科書的にならず、自分の体験や失敗談をベースに
- 本職が医師であることは基本伏せる（必要時のみ「本職柄、安全管理にはちょっとうるさい方なので」程度に匂わせる）

## NG表現（絶対に使わない）
最高 / 最強 / 絶対 / 神 / 完全 / 100% / 必ず / 今すぐ / 間違いなく
「〜してみてはいかがでしょうか」「〜をご紹介します」「〜についてまとめました」
「おすすめ○選」「徹底比較」「完全ガイド」

## 文体の例（こういう感じで）
- 「このテント、設営5分は盛ってると思ったけど実際そうだった。ワンタッチ系で一番まともかも」
- 「夜露でテーブル濡れるの地味にストレス。アルミ天板に変えてから気にならなくなった」
- 「春キャンプ、昼は暑いのに夜は5度とかザラ。フリース忘れて凍えた去年の自分に教えたい」
- 「個人的には、ペグだけは絶対に妥協しない方がいい。3年使ってきた結論」

## 共通フォーマット
- 各投稿は280文字以内（URLとハッシュタグ含む）
- ハッシュタグは2〜3個、本文末尾に改行して配置`;

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
    "text": "投稿本文（ハッシュタグ含む）",
    "articleSlug": "記事のスラッグ または null",
    "url": "記事のURL または null"
  }
]${extra ? "\n\n" + extra : ""}`;
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
以下の記事を自然に紹介するポストを1件ずつ。記事URLは ${SITE_URL}/articles/{スラッグ}
宣伝っぽくなく、実体験や感想を交えて「ブログに書いた」感じで。

${articleInfoList}

## タスク2: キャンプ豆知識（${articles.length}件）
季節に合ったキャンプの実用的な豆知識。URLは不要。
教科書的にならず、自分の体験や失敗談ベースで。

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

- type は全て "outdoor_tip"
- ハッシュタグは2〜3個

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
記事URLは ${SITE_URL}/articles/{スラッグ}
宣伝っぽくなく、実体験や感想を交えて「ブログに書いた」感じで。

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
- 候補記事から1つ選び articleSlug にスラッグを入れる（URLも添付）
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
- 候補記事から1つ選び articleSlug にスラッグを入れる
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

export const POST_TYPES = {
  article_promo:     { axis: "camp",      weeklyCount: 2,   approval: "batch" },
  outdoor_tip:       { axis: "camp",      weeklyCount: 1,   approval: "auto"  },
  poll_question:     { axis: "rotate",    weeklyCount: 2,   approval: "auto"  },
  failure_story:     { axis: "camp",      weeklyCount: 1,   approval: "auto"  },
  gear_thread:       { axis: "camp",      weeklyCount: 1,   approval: "batch", isThread: true },
  ai_dev_log:        { axis: "ai",        weeklyCount: 1.5, approval: "auto"  },
  parenting_outdoor: { axis: "parenting", weeklyCount: 1,   approval: "auto"  },
  doc_health_tip:    { axis: "doctor",    weeklyCount: 1,   approval: "manual" },
  seasonal_hook:     { axis: "all",       weeklyCount: 1,   approval: "batch" },
  repost_rewrite:    { axis: "all",       weeklyCount: 0.5, approval: "batch" },
};

export const APPROVAL_RULES = {
  auto:   ["outdoor_tip", "poll_question", "failure_story", "ai_dev_log", "parenting_outdoor"],
  batch:  ["article_promo", "gear_thread", "seasonal_hook", "repost_rewrite"],
  manual: ["doc_health_tip"],
};

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
    "url": "最終ツイートに含めるURL または null"
  }
]

各ツイートは280文字以内。tweets[0]が親ツイート。`;
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
  5. まとめ＋サイトリンク（関連記事があれば）
- 各ツイートは280文字以内
- ハッシュタグは親ツイートに2〜3個

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
- URLは関連記事がある場合のみ
- ハッシュタグ: #ファミリーキャンプ など2〜3個

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
- URLは関連記事がある場合のみ
- ハッシュタグは2〜3個（季節タグ必須）

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
    default:
      throw new Error(`未知の投稿タイプ: ${type}`);
  }
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
