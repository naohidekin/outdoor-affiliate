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

// === ナレッジ読み込み（account-config.json）===

function loadAccountConfig() {
  const configPath = path.join(process.cwd(), "data", "account-config.json");
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
export const RAKUTEN_ROOM_URL = _config.rakutenRoomUrl || "${RAKUTEN_ROOM_URL}";
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

## ペルソナ具体度ガード（捏造防止・絶対遵守）
- **車**: 「外車のSUV」程度まで。車種・ブランド・モデル名は絶対に出さない（過去に車種情報を誤記した事故あり）
- **キャンプギア**: ペルソナのメイン装備（${p.mainGear}）以外の具体名を勝手に出さない。断定的なレビューが必要なら一般化表現に留める
- **医療**: 専門科特定（小児科等）・個別症例・具体的医薬品名・医療機器名は禁止。開示OKな範囲は「開業医・内科ホームドクター・法人で美容自費診療/訪問診療/訪問看護も展開」まで
- **職場・家族**: 地名は「${p.location}」より細かくしない。医院名・学校名・家族個人名は出さない
- **note運用は別アカウント**: noteは別人格で運用中なので、この投稿で「note書いた」等と混同しない
- **迷ったら抽象化または沈黙**。「この固有名詞は事実確認済みか？」を投稿前に必ず自問する

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
- 各投稿は${fmt.maxChars}文字以内（URLは本文に入れないので文字数に含めない）

## ハッシュタグの禁止（最重要）
**ハッシュタグ（#タグ）を一切付けない**。X のアルゴリズムはハッシュタグ付き
投稿のリーチを下げる傾向があるため、本文中・末尾とも # は使わない。
過去のプロンプト例に「ハッシュタグ N個」と書かれていても無視すること。`;
}

export const PERSONA_PREAMBLE = buildPersonaPreamble(_config);

// === ヘルパ ===

function articleListBlock(articles, categories) {
  return articles
    .map((a) => {
      const cat = categories?.find((c) => c.id === a.categoryId);
      return `- タイトル: ${a.title}\n  スラッグ: ${a.slug}\n  カテゴリ: ${cat?.name || "不明"}\n  概要: ${a.excerpt}`;
    })
    .join("\n\n");
}

function jsonOutputSpec(extra = "") {
  return `## 出力形式
以下のJSON配列で出力してください。他のテキストは一切不要です。
[
  {
    "type": "...",
    "text": "投稿本文（# ハッシュタグ禁止、URL も本文に含めない）",
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
- ハッシュタグは付けない（# 一切使わない）

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
- ハッシュタグは付けない（# 一切使わない）
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
- ハッシュタグは付けない（# 一切使わない）

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
- ハッシュタグは付けない（# 一切使わない）
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
- ハッシュタグは付けない（# 一切使わない）
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
- ハッシュタグは付けない（# 一切使わない）
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
- ハッシュタグは付けない（# 一切使わない）
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
- ハッシュタグは付けない（# 一切使わない）
- 情報密度が高いスレッドは1ツイート目に【保存版】を付けてもよい

${threadOutputSpec()}`;
}

export function buildAiDevLogPrompt({ count, month, seed }) {
  const seasonContext = SEASON_CONTEXT[month];
  return `${PERSONA_PREAMBLE}

## 現在の季節
${month}月: ${seasonContext}
${seedBlock(seed)}

## タスク（この軸はフォロワー増の副主軸 — エンジニア層への差別化）
Claude Code / AI開発のリアルな体験を${count}件。

- type は全て "ai_dev_log"
- **最大の差別化ポイント**: 「開業医がClaude Codeで個人サイトを作って運営している」という立ち位置そのもの。ここを濃く匂わせる。エンジニアでも医者でもない、非エンジニア側の生のリアクションが効く
- 書くべき題材（優先順位順）:
  1. Claude Code / AIで詰まって解決した **具体的な体験**（Before/After、時間比較、失敗談）
  2. 「これAIができるの？」系の驚きエピソード（医療業界との接続ネタも可）
  3. 非エンジニアの学び（「try/catchが何か最近覚えた」「git reset --hard で3時間の作業を消した」等の素直な失敗）
  4. プロンプトや環境設定の共有（ただしAPIキー・個人情報は絶対に含めない）
- テック用語は **2〜3個まで**。詰め込みすぎず「医者でも読める」バランス
- Claude Code / Anthropic の料金・内部仕様の推測は書かない（事実ベースのみ）
- URLは不要
- ハッシュタグは付けない（# 一切使わない）
- **selfReply**: 「同じ詰まり方した人いる？」「もっと良い解法あったら教えて」系

## バズ＆フォロワー増のコツ
- AI界隈は「自分もやってみた」RTが起きやすい層。**具体数字**（「3時間の作業が5分」「月額2000円で週次自動化」等）が強い
- **非エンジニア視点** は差別化ポイント。「エンジニアには当たり前のことを感心してる」のが逆に響く
- 文体は他タイプより砕けてOK。開発日記調・独り言調も可（ただし下品にはしない）
- 1行目に **逆説／意外** を入れる（「AIの一番の使い道、コード書くことじゃないかもしれない」等）

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
- ハッシュタグは付けない（# 一切使わない）
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

## タスク（この軸は現フェーズのフォロワー増主軸 — 週3件の主力）
医師×健康の実用情報を${count}件。アウトドア軸に縛らず、日常生活・季節・生活習慣・訪問診療の現場視点など広く扱う。

- type は全て "doc_health_tip"
- 書き手のペルソナ: **開業医・内科ホームドクター**。法人として美容系自費診療・訪問診療・訪問看護も展開。「本職柄〜」「診療していて〜」「ホームドクターの立場で言うと〜」のトーンでOK
- 外来でよく聞かれる質問、訪問診療で見た生活の工夫、高齢患者の実例（匿名化された一般論）、季節疾患の注意など

## 開示してOKな属性
- 開業医である、内科ホームドクターである、訪問診療・訪問看護もやっている、美容自費診療も手がけている

## 絶対に出さない情報
- 専門科の特定（小児科・皮膚科・整形外科など個別の科名は出さない）
- 個別症例の詳細（「○○歳の男性患者が」等の具体的ケース記述）
- 具体的医薬品名（商品名・一般名問わず）
- 医療機器の具体名・型番
- 医院名・勤務地の具体・患者の特定につながる情報

## 薬機法・医療法ガード（絶対遵守）
以下は**絶対に使わない**:
- 「治る」「治す」「効く」「効きます」「痩せる」「改善する」「改善できる」「予防できます」「必ず〜」
- 「診断」「処方」「投薬」など医行為を含意する動詞の断定使用
- 特定の薬品名・治療法の推奨・個別医療相談への回答
- 断定は避け、「〜の傾向があります」「一般論として〜」「続く場合はかかりつけ医に相談を」の言い回しを基本とする

## バズ＆フォロワー増のコツ
- ホームドクター視点は珍しい（外来医が多いX上で差別化できる）。「訪問診療で見た〜」「ホームドクターとして伝えたい〜」は独自性が高い
- 「意外」系が強い（「実は〜」「よく誤解されるんですが〜」「患者さんによく聞かれるんですが〜」）
- 季節ネタ×医療は保存されやすい（花粉症・熱中症・冬の乾燥・GWの食中毒 等）
- 【保存版】【ブクマ推奨】は情報密度が高い時だけ使う

- ハッシュタグは付けない（# 一切使わない）
- **selfReply**: 「気になる症状ある方はリプで（個別相談はできませんが傾向はコメントできます）」「皆さんのかかりつけ医はどんな先生？」等の会話誘発

${jsonOutputSpec()}`;
}

// 楽天セールカレンダー（主要イベント）
const RAKUTEN_SALE_CALENDAR = {
  1:  [{ name: "お買い物マラソン", around: "中旬" }],
  2:  [{ name: "お買い物マラソン", around: "中旬" }],
  3:  [{ name: "スーパーSALE", around: "上旬" }, { name: "お買い物マラソン", around: "下旬" }],
  4:  [{ name: "お買い物マラソン", around: "中旬" }],
  5:  [{ name: "お買い物マラソン", around: "中旬" }],
  6:  [{ name: "スーパーSALE", around: "上旬" }, { name: "お買い物マラソン", around: "下旬" }],
  7:  [{ name: "お買い物マラソン", around: "中旬" }],
  8:  [{ name: "お買い物マラソン", around: "中旬" }],
  9:  [{ name: "スーパーSALE", around: "上旬" }, { name: "お買い物マラソン", around: "下旬" }],
  10: [{ name: "お買い物マラソン", around: "中旬" }],
  11: [{ name: "お買い物マラソン", around: "中旬" }],
  12: [{ name: "スーパーSALE", around: "上旬" }, { name: "大感謝祭", around: "下旬" }],
};

export function buildSeasonalHookPrompt({ count, month, seed, articles, categories, roomProducts }) {
  const seasonContext = SEASON_CONTEXT[month];
  const articleInfo = articles?.length
    ? `\n## 関連記事（リンク候補）\n${articleListBlock(articles, categories)}`
    : "";

  // 楽天セール情報
  const sales = RAKUTEN_SALE_CALENDAR[month] || [];
  const saleBlock = sales.length > 0
    ? `\n## 今月の楽天セール情報（投稿ネタ候補）
${sales.map((s) => `- 楽天${s.name}（${month}月${s.around}頃）`).join("\n")}
- セール時期なら「${count}件のうち1件は楽天セール×キャンプギアのネタにしてもよい」
- その場合: urlフィールドに「${RAKUTEN_ROOM_URL}」を入れ、末尾に「楽天ROOMはリプ欄に。(*広告を含みます)」と書く
- セール投稿は押しつけない。「この時期に買い回るなら」「僕もマラソンで補充した」程度のトーン`
    : "";

  return `${PERSONA_PREAMBLE}

## 現在の季節
${month}月: ${seasonContext}
${seedBlock(seed)}
${articleInfo}
${saleBlock}

## タスク
今の季節・イベント・トレンドに連動した投稿を${count}件。

- type は全て "seasonal_hook"
- GW・梅雨・セール・天気・花見・紅葉など、タイムリーなネタ
- 季節の体感を具体化（朝霜・夕立・虫・湿気・気温差など）
- **本文にURLを含めない**。関連記事がある場合は「詳細はリプ欄へ。」と書き、urlフィールドにURLを入れる
- ハッシュタグは付けない（# 一切使わない）
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
- ハッシュタグは付けない（# 一切使わない）

${jsonOutputSpec("各オブジェクトに \"originalIndex\": 元投稿の番号（1始まり）を追加してください。")}`;
}

/**
 * タイプ名からプロンプトを生成するディスパッチャー
 * @param {string} type - 投稿タイプ
 * @param {object} context - { month, count, seed, articles, categories, existingPosts, roomProducts }
 * @returns {string} プロンプト文字列
 */
export function getPromptForType(type, context) {
  switch (type) {
    case "article_promo":      return buildArticlePromoPrompt(context);
    case "outdoor_tip":        return buildOutdoorTipPrompt(context);
    case "poll_question":      return buildPollQuestionPrompt(context);
    case "failure_story":      return buildFailureStoryPrompt(context);
    case "gear_thread":        return buildGearThreadPrompt(context);
    case "ai_dev_log":         return buildAiDevLogPrompt(context);
    case "parenting_outdoor":  return buildParentingOutdoorPrompt(context);
    case "doc_health_tip":     return buildDocHealthTipPrompt(context);
    case "seasonal_hook":      return buildSeasonalHookPrompt(context);
    case "repost_rewrite":     return buildRepostRewritePrompt(context);
    case "news_comment":       return buildNewsCommentPrompt(context);
    case "rakuten_room_pick":  return buildRakutenRoomPickPrompt(context);
    default:
      throw new Error(`未知の投稿タイプ: ${type}`);
  }
}

/**
 * rakuten_room_pick: 楽天ROOMに追加した商品をX投稿で紹介。
 * context.roomProducts: ROOM投稿済み商品リスト [{ id, name, price, productUrl }]
 */
export function buildRakutenRoomPickPrompt({ count, month, seed, roomProducts }) {
  const seasonContext = SEASON_CONTEXT[month];
  const productList = (roomProducts || [])
    .slice(0, 10)
    .map((p, i) => `${i + 1}. ${p.name}${p.price ? ` (¥${p.price.toLocaleString()})` : ""}`)
    .join("\n");

  return `${PERSONA_PREAMBLE}

## 現在の季節
${month}月: ${seasonContext}
${seedBlock(seed)}

## タスク
楽天ROOMに最近追加したキャンプギアを紹介するX投稿を${count}件。

- type は全て "rakuten_room_pick"
- トーン: 「最近ROOMに追加した○○、実際に使ってるけど△△なところが気に入ってる」「ずっと楽天で買い回ってるギアたち、ROOMにまとめ始めた」など自然な語り口
- **本文にURLを含めない**。末尾に「楽天ROOMはリプ欄に。」と書く
- urlフィールドに「${RAKUTEN_ROOM_URL}」を入れる（ROOMマイページリンク）
- selfReply: 「ROOM覗いてみて、他のギアも載せてます」「フォローしてくれたら嬉しい」系の軽い誘導
- ハッシュタグは付けない（# 一切使わない）
- 文末に「(*広告を含みます)」と入れる（アフィリエイト表記）
- 商品の具体的な感想・スペック比較・使用シーンを盛り込むこと
- 1投稿で1〜2商品に絞る（詰め込まない）

## ROOM掲載商品（この中から選んで紹介）
${productList || "（商品データなし — 一般的なキャンプギアについて書いてください）"}

${jsonOutputSpec()}`;
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
- ハッシュタグは付けない（# 一切使わない）

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
