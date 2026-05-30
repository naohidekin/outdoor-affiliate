#!/usr/bin/env node
/**
 * Priority C記事バッチリライトスクリプト
 * WISE+Sense基準で短い記事を順次改善する
 */

import Anthropic from '@anthropic-ai/sdk';
import { readFileSync, writeFileSync, existsSync } from 'fs';
import { fileURLToPath } from 'url';
import { dirname, join } from 'path';

// .env.local を読み込む
function loadEnvLocal(dir) {
  const envPath = join(dir, '..', '.env.local');
  if (existsSync(envPath)) {
    const lines = readFileSync(envPath, 'utf-8').split('\n');
    for (const line of lines) {
      const m = line.match(/^([A-Z_]+)=(.+)$/);
      if (m && !process.env[m[1]]) {
        process.env[m[1]] = m[2].trim();
      }
    }
  }
}

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);
const ROOT = join(__dirname, '..');

loadEnvLocal(__dirname);

const apiKey = process.env.ANTHROPIC_API_KEY;
if (!apiKey) {
  console.error('ANTHROPIC_API_KEY が設定されていません');
  process.exit(1);
}
const client = new Anthropic({ apiKey });

// Priority A/B でリライト済み
const DONE = new Set([
  'spring-sleeping-bag-guide', 'firepit-beginner-guide', 'led-tent-light-ranking', 'low-table-ranking',
  'tent-with-vestibule-ranking', 'tarp-setup-guide-for-beginners', 'summer-camp-cooler-tips',
  'rain-camp-gear-essentials', 'solo-low-chair-ranking', 'family-camp-first-time-guide',
  'spring-camp-clothing-guide', // 本日リライト済み
]);

// --slug で特定記事のみ処理
const targetSlug = process.argv.includes('--slug')
  ? process.argv[process.argv.indexOf('--slug') + 1]
  : null;

// --limit で処理件数を制限
const limit = process.argv.includes('--limit')
  ? parseInt(process.argv[process.argv.indexOf('--limit') + 1])
  : 5; // デフォルト5件

const PERSONA = `
あなたはキャンプギアレビューサイト「camp-gear-lab.com」の著者「ギア男」です。

【プロフィール】
- 37歳、長野県在住
- 開業医・内科ホームドクター（法人として美容系自費診療・訪問診療・訪問看護も展開）
- キャンプ歴10年（2016年〜）
- メイン装備：スノーピーク アメニティドームL（旧型）+ メッシュタープ
- 家族：妻＋子供2人（小学校低学年〜中学年の男女）
- キャンプスタイル：家族キャンプ（月1〜2回）、たまにソロ
- 一人称：「僕」

【文体】
- ですます調。友人に話しかけるような温かみ
- 断言できることは断言する。「〜かもしれません」を多用しない
- AIくさい表現を全て排除：「〜することができます」「〜において」「〜と言えるでしょう」「〜解説していきましょう」「〜見ていきましょう」など全て口語に置き換え

【記事に必ず入れるもの（WISE+Sense）】
W（Warm/体温）：キャンプでの具体的な失敗体験や発見を冒頭か途中に入れる。時・場所・行動が伝わること
I（Insight/独自視点）：医師の目線か10年ギア選びをしてきた知見を1箇所以上入れる
S（Sincere/切実さ）：具体的な数値・製品名・比較・失敗談で説得力を持たせる
E（Empathy/共感）：ファミリーキャンパーが「あるある」と思える内容を含める
AI（AI臭さなし）：自然な人間の文章にする
Sense（半歩先）：「他のキャンプブログと同じことを言わない」角度を入れる

【NGワード】
- 絶対/最強/神ギア/間違いなし（→「〜なら十分」「〜が一番落ち着く」に置き換え）
- 素晴らしい/最高の/非常に（→具体スペックで示す）
- 今すぐ買え/売り切れ必至（→「気になる方はチェックを」程度）
- **太字**は記事全体で5〜8箇所まで
`;

const REWRITE_PROMPT = (article) => `
以下のキャンプ記事をWISE+Sense基準でリライトしてください。

【記事スラッグ】${article.slug}
【現在のタイトル】${article.title}
【対象キーワード】${JSON.stringify(article.targetKeywords || [])}
【現在の文字数】${article.content.length}字

【現在の記事内容】
${article.content}

【リライト要件】
1. 文字数を8,000字以上に拡張する（現在から+3,000字以上が目標）
2. 冒頭に「ギア男の実体験（失敗→感情→気づき→現在）」を追加する（W基準）
3. 医師の視点か長年のギア選び視点を最低1箇所入れる（I基準）
4. 具体的な数値・製品比較・失敗談で説得力を上げる（S基準）
5. 家族キャンパーの「あるある」や子連れ向け情報を加える（E基準）
6. AI特有表現を全て口語・断定に置き換える（AI基準）
7. 「よくある質問」セクション（Q&A形式、4〜6問）を追加する
8. 既存の内部リンク（[記事名](/articles/slug)形式）は全て保持する
9. 比較表（{{comparison:...}}タグ）は変更しない
10. Markdownテーブルは適切に活用する

【出力形式】
Markdownで記事本文のみ出力してください。タイトルから始めること（# から始める）。
コードブロックで囲まない。説明文も不要。記事本文だけ出力する。
`;

async function rewriteArticle(article) {
  console.log(`\n[${article.slug}] リライト開始 (${article.content.length}字 → 目標8000字+)`);

  const response = await client.messages.create({
    model: 'claude-sonnet-4-5',
    max_tokens: 8192,
    messages: [
      { role: 'user', content: PERSONA + '\n\n' + REWRITE_PROMPT(article) }
    ]
  });

  const newContent = response.content[0].text.trim();
  console.log(`[${article.slug}] 完了: ${newContent.length}字`);
  return newContent;
}

async function main() {
  const articlesPath = join(ROOT, 'data', 'articles.json');
  const articles = JSON.parse(readFileSync(articlesPath, 'utf-8'));

  // 対象記事を選別（短い順、DONE除外）
  let targets = articles
    .filter(a => !DONE.has(a.slug) && a.status === 'published')
    .map(a => ({ ...a, _chars: (a.content || '').length }))
    .sort((a, b) => a._chars - b._chars);

  if (targetSlug) {
    targets = targets.filter(a => a.slug === targetSlug);
  } else {
    targets = targets.slice(0, limit);
  }

  if (targets.length === 0) {
    console.log('処理対象なし');
    return;
  }

  console.log(`処理対象: ${targets.map(a => a.slug).join(', ')}`);

  let updated = 0;
  for (const target of targets) {
    try {
      const newContent = await rewriteArticle(target);

      // articles.json を更新
      const idx = articles.findIndex(a => a.slug === target.slug);
      if (idx !== -1) {
        articles[idx].content = newContent;
        updated++;

        // 都度保存（途中でエラーが出ても保存済み分は残る）
        writeFileSync(articlesPath, JSON.stringify(articles, null, 2));
        console.log(`[${target.slug}] 保存完了`);
      }

      // APIレート制限対策
      if (targets.indexOf(target) < targets.length - 1) {
        await new Promise(r => setTimeout(r, 2000));
      }
    } catch (err) {
      console.error(`[${target.slug}] エラー:`, err.message);
    }
  }

  console.log(`\n✅ 完了: ${updated}/${targets.length}件リライト`);
}

main().catch(console.error);
