/**
 * 楽天ROOM デイリー追加スクリプト v2
 * - 永続セッション（初回のみログイン）
 * - 1日5件ずつ rakuten-room-add-list.txt から追加
 * Usage: node run.js /tmp/playwright-rakuten-room-daily.js [--login]
 */
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');
const os = require('os');
const https = require('https');

const DAILY_LIMIT = 5;
const PROFILE_DIR = path.join(os.homedir(), '.rakuten-room-profile');
const PROGRESS_FILE = '/Users/NaohideKin/Desktop/AI関連/claude/outdoor-affiliate/data/rakuten-room-progress.json';
const LIST_FILE = '/Users/NaohideKin/Desktop/AI関連/claude/outdoor-affiliate/rakuten-room-add-list.txt';
const ENV_FILE = '/Users/NaohideKin/Desktop/AI関連/claude/outdoor-affiliate/.env.local';
const LOGIN_MODE = process.argv.includes('--login');

// .env.local から ANTHROPIC_API_KEY を読み込む
let ANTHROPIC_API_KEY = '';
try {
  const env = fs.readFileSync(ENV_FILE, 'utf-8');
  const match = env.match(/^ANTHROPIC_API_KEY=(.+)$/m);
  if (match) ANTHROPIC_API_KEY = match[1].trim().replace(/^["']|["']$/g, '');
} catch {}

// ===== Claude API でROOMコメント生成 =====
async function generateRoomComment(productName) {
  if (!ANTHROPIC_API_KEY) {
    console.log('  ⚠️  ANTHROPIC_API_KEY 未設定、コメントなしで投稿');
    return '';
  }
  const prompt = `楽天ROOMに投稿するキャンプギアの紹介コメントを日本語で書いてください。

商品名: ${productName}

条件:
- 3〜5行、絵文字を適度に使用
- キャンプ好き（長野在住・家族キャンプ・ソロキャンプ）のギア男(@camp_gear_lab)らしいコメント
- 最後に関連ハッシュタグ5〜7個（#キャンプ #アウトドア等）
- 合計500文字以内
- セール・マラソン・クーポン・期間限定・ポイント等の情報は一切含めない（恒久的なコメントにする）
- JSONや余計な説明は不要。コメント本文のみ出力`;

  return new Promise((resolve) => {
    const body = JSON.stringify({
      model: 'claude-haiku-4-5-20251001',
      max_tokens: 300,
      messages: [{ role: 'user', content: prompt }],
    });
    const req = https.request({
      hostname: 'api.anthropic.com',
      path: '/v1/messages',
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'x-api-key': ANTHROPIC_API_KEY,
        'anthropic-version': '2023-06-01',
      },
    }, (res) => {
      let data = '';
      res.on('data', d => data += d);
      res.on('end', () => {
        try {
          const json = JSON.parse(data);
          resolve(json.content?.[0]?.text?.trim() || '');
        } catch { resolve(''); }
      });
    });
    req.on('error', () => resolve(''));
    req.write(body);
    req.end();
  });
}

// ===== 商品リスト読み込み =====
function parseProductList(text) {
  const items = [];
  const blocks = text.split(/\n(?=\d+\.)/).filter(Boolean);
  for (const block of blocks) {
    const lines = block.trim().split('\n').map(l => l.trim()).filter(Boolean);
    if (!lines[0]) continue;
    const numMatch = lines[0].match(/^(\d+)\.\s+(.+)/);
    if (!numMatch) continue;
    const idx = parseInt(numMatch[1]);
    const name = numMatch[2];
    const url = lines.find(l => l.startsWith('http'));
    if (url) items.push({ idx, name, url });
  }
  return items;
}

// ===== 進捗管理 =====
function loadProgress() {
  try {
    return JSON.parse(fs.readFileSync(PROGRESS_FILE, 'utf8'));
  } catch {
    return { completed: [], lastRun: null, totalItems: 40 };
  }
}
function saveProgress(progress) {
  fs.writeFileSync(PROGRESS_FILE, JSON.stringify(progress, null, 2));
}

// ===== メイン =====
(async () => {
  // プロファイルディレクトリ作成
  if (!fs.existsSync(PROFILE_DIR)) fs.mkdirSync(PROFILE_DIR, { recursive: true });

  const listText = fs.readFileSync(LIST_FILE, 'utf8');
  const allProducts = parseProductList(listText);
  const progress = loadProgress();
  const pending = allProducts.filter(p => !progress.completed.includes(p.idx));
  const todayBatch = pending.slice(0, DAILY_LIMIT);

  if (todayBatch.length === 0) {
    console.log('✅ すべての商品を追加済みです！(40/40)');
    return;
  }

  console.log(`\n📋 本日の追加予定 (${DAILY_LIMIT}件/日):`);
  todayBatch.forEach(p => console.log(`  ${p.idx}. ${p.name}`));
  console.log('');

  // 永続コンテキストでブラウザ起動（セッション保存）
  const browser = await chromium.launchPersistentContext(PROFILE_DIR, {
    headless: !LOGIN_MODE,  // ログイン時のみ画面あり、通常は非表示
    slowMo: LOGIN_MODE ? 600 : 300,
    viewport: { width: 1280, height: 900 },
  });
  const page = browser.pages()[0] || await browser.newPage();

  // ===== ログイン確認 =====
  if (LOGIN_MODE) {
    console.log('🔐 ログインモード。楽天ROOMのSSO認証を開始します...');
    const triggerUrl = 'https://room.rakuten.co.jp/mix?itemcode=snowpeak-official%3Aes-070&scid=we_room_upc60';
    await page.goto(triggerUrl, { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(3000);

    console.log('');
    console.log('👉 ブラウザで楽天アカウントにログインしてください。');
    console.log('   ログインが完了するとこのターミナルに「✅ ログイン完了」と表示されます。');
    console.log('   （最大5分待機）...');
    console.log('');

    // ログイン完了をポーリングで確認（ROOMの投稿フォームが表示されるまで待つ）
    let loggedIn = false;
    const deadline = Date.now() + 300000; // 5分
    while (Date.now() < deadline) {
      await page.waitForTimeout(3000);
      const currentUrl = page.url();
      // ROOMのmixページに戻った かつ ログインページではない
      if (currentUrl.includes('room.rakuten.co.jp') && !currentUrl.includes('login.account.rakuten.com')) {
        // 投稿フォームの存在を確認
        const hasForm = await page.evaluate(() => {
          // ログイン済みのROOM mixページには投稿フォームがある
          return document.querySelector('textarea, input[type="text"], button[type="submit"], form') !== null;
        });
        if (hasForm) {
          loggedIn = true;
          break;
        }
      }
    }

    if (loggedIn) {
      console.log('✅ ログイン完了！セッションを保存しました。');
      console.log('   次回から --login なしで実行できます。');
    } else {
      console.log('⚠️  ログインを確認できませんでした。再度試してください。');
    }
    await browser.close();
    return;
  }

  // ログイン状態チェック（リダイレクト時のERR_ABORTEDを無視）
  try {
    await page.goto('https://room.rakuten.co.jp/', { waitUntil: 'domcontentloaded' });
  } catch (_) { /* リダイレクトによるabortは無視 */ }
  await page.waitForTimeout(3000);
  const currentUrl = page.url();
  if (currentUrl.includes('login') || currentUrl.includes('account.rakuten.com')) {
    console.log('⚠️  ログインが必要です。以下のコマンドで先にログインしてください:');
    console.log('   node run.js /tmp/playwright-rakuten-room-daily.js --login');
    await browser.close();
    return;
  }
  console.log('✅ ログイン済み\n');

  // ===== 各商品を処理 =====
  let addedCount = 0;
  for (const product of todayBatch) {
    console.log(`[${product.idx}/40] ${product.name}`);

    try {
      // 検索結果ページへ
      await page.goto(product.url, { waitUntil: 'domcontentloaded', timeout: 30000 });
      await page.waitForTimeout(2000);

      // タイトルリンクを探す（PR広告を除外し商品名キーワードに近いものを優先）
      let productUrl = null;
      const keywords = product.name.split(/[\s　]+/).filter(s => s.length > 1);
      const allItemLinks = await page.locator('a[href*="item.rakuten.co.jp"]').all();
      let bestLink = null, bestScore = -1;
      for (const link of allItemLinks) {
        const text = (await link.textContent()).trim();
        if (text.length < 5) continue;
        // PR広告っぽいものをスキップ
        const isPr = await link.evaluate(el => {
          const parent = el.closest('[class*="sponsor"], [class*="pr"], [class*="ad"]');
          return !!parent;
        }).catch(() => false);
        if (isPr) continue;
        // キーワードマッチ数でスコアリング
        const score = keywords.filter(k => text.includes(k)).length;
        if (score > bestScore) { bestScore = score; bestLink = link; }
      }
      // スコアが0でも最初の候補にフォールバック
      if (!bestLink) {
        for (const link of allItemLinks) {
          const text = (await link.textContent()).trim();
          if (text.length > 5) { bestLink = link; break; }
        }
      }
      if (bestLink) {
        productUrl = await bestLink.getAttribute('href');
        const text = (await bestLink.textContent()).trim();
        console.log(`  📦 商品(score=${bestScore}): ${text.substring(0, 50)}`);
      }

      if (!productUrl) {
        console.log('  ⚠️  商品リンク見つからず、スキップ');
        continue;
      }

      // 商品ページへ
      await page.goto(productUrl, { waitUntil: 'domcontentloaded', timeout: 30000 });
      await page.waitForTimeout(2000);

      // 「ROOMに投稿」リンクを探す
      const roomLinks = await page.locator('a[href*="room.rakuten.co.jp/mix"]').all();
      if (roomLinks.length === 0) {
        console.log('  ⚠️  「ROOMに投稿」ボタン見つからず');
        await page.screenshot({ path: `/tmp/room-debug-${product.idx}.png` });
        console.log(`  📸 /tmp/room-debug-${product.idx}.png`);
        continue;
      }

      const roomUrl = await roomLinks[0].getAttribute('href');
      console.log('  👍 「ROOMに投稿」クリック...');

      // 新しいタブで開く可能性があるので処理
      const [newPage] = await Promise.all([
        browser.waitForEvent('page').catch(() => null),
        roomLinks[0].click(),
      ]);

      const targetPage = newPage || page;
      await targetPage.waitForLoadState('domcontentloaded').catch(() => {});
      await targetPage.waitForTimeout(2000);

      const roomPageUrl = targetPage.url();
      console.log(`  🌐 ROOMページ: ${roomPageUrl.substring(0, 80)}`);

      if (roomPageUrl.includes('login') || roomPageUrl.includes('account.rakuten.com')) {
        console.log('  ⚠️  セッション切れ。--login で再ログインしてください。');
        await browser.close();
        return;
      }

      await targetPage.screenshot({ path: `/tmp/room-page-${product.idx}.png` });

      // textarea にコメントを入力
      try {
        const textarea = targetPage.locator('textarea').first();
        if (await textarea.isVisible({ timeout: 3000 })) {
          const comment = await generateRoomComment(product.name);
          if (comment) {
            await textarea.fill(comment);
            console.log(`  ✏️  コメント入力: ${comment.substring(0, 40)}...`);
            await targetPage.waitForTimeout(500);
          }
        }
      } catch { /* textarea なければスキップ */ }

      // 「完了」ボタンを探す（優先順位順）
      const submitSelectors = [
        '.collect-btn',
        'button:has-text("完了")',
        'button[type="submit"]',
        'button:has-text("投稿")',
        'button:has-text("コレ")',
        '[class*="submit"]',
        'input[type="submit"]',
      ];

      let posted = false;
      for (const sel of submitSelectors) {
        try {
          const btn = targetPage.locator(sel).first();
          if (await btn.isVisible({ timeout: 2000 })) {
            const btnText = (await btn.textContent()).trim();
            console.log(`  ✅ 投稿ボタン発見: "${btnText}" → クリック`);
            await btn.click();
            await targetPage.waitForTimeout(2000);
            posted = true;
            break;
          }
        } catch { continue; }
      }

      if (!posted) {
        // スクリーンショットで手動確認
        console.log(`  ⚠️  投稿ボタン自動検出失敗`);
        console.log(`  📸 /tmp/room-page-${product.idx}.png を確認してください`);

        // ページ上のボタンをリスト
        const pageBtns = await targetPage.evaluate(() => {
          const results = [];
          document.querySelectorAll('button, [role="button"], input[type="submit"]').forEach(el => {
            const text = el.textContent?.trim() || el.value || '';
            if (text) results.push({ text: text.substring(0, 40), class: (el.className || '').substring(0, 60) });
          });
          return results.slice(0, 10);
        });
        console.log('  ページ上のボタン:', JSON.stringify(pageBtns));
        continue;
      }

      // 投稿成功
      progress.completed.push(product.idx);
      addedCount++;
      console.log(`  ✅ 追加完了！`);

      // 新しいタブを閉じる
      if (newPage) await newPage.close().catch(() => {});

    } catch (err) {
      console.log(`  ❌ エラー: ${err.message.substring(0, 100)}`);
    }

    // 人間っぽい間隔 (2〜4秒)
    await page.waitForTimeout(2000 + Math.floor(Math.random() * 2000));
  }

  // 進捗保存
  progress.lastRun = new Date().toISOString();
  saveProgress(progress);

  console.log(`\n============================`);
  console.log(`✅ 本日: ${addedCount}/${todayBatch.length} 件追加`);
  console.log(`📊 累計: ${progress.completed.length}/${progress.totalItems} 件`);
  console.log(`残り: ${progress.totalItems - progress.completed.length} 件`);
  console.log(`============================`);

  await page.waitForTimeout(3000);
  await browser.close();
})();
