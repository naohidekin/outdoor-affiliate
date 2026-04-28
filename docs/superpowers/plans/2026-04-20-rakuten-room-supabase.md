# Rakuten Room Supabase Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the text-file-based Rakuten Room auto-posting script with one that reads directly from Supabase `products` table, using decoded affiliate URLs for direct product page navigation.

**Architecture:** A new script `scripts/rakuten-room-supabase.js` queries Supabase for all products with Rakuten `affiliate_url`, decodes the `pc=` parameter to get `item.rakuten.co.jp` URLs directly, and posts 5 items/day to Rakuten Room via Playwright persistent context. Progress is tracked by product ID in `data/rakuten-room-supabase-progress.json`. The existing launchd plist is updated to point to the new script.

**Tech Stack:** Node.js (CommonJS), Playwright (persistent context), `@supabase/supabase-js`, Claude Haiku API (https), launchd plist

---

### Task 1: Create `scripts/rakuten-room-supabase.js`

**Files:**
- Create: `scripts/rakuten-room-supabase.js`

The script logic:
1. Read Supabase credentials from `.env.local`
2. Fetch all products where `affiliate_url` LIKE `%rakuten%`, ordered by `created_at`
3. Load progress from `data/rakuten-room-supabase-progress.json`
4. Filter to pending (not in `progress.posted` set)
5. Take first 5
6. For each: decode `pc=` from affiliate_url → navigate directly to `item.rakuten.co.jp` URL
7. Find "ROOMに投稿" link → click → fill comment (Claude Haiku) → click submit
8. Save progress by product ID

- [ ] **Step 1: Create the script**

```js
/**
 * 楽天ROOM Supabase連携版 v1
 * - Supabase productsテーブルから楽天商品を取得
 * - affiliate_urlのpc=パラメータをデコードして直接商品URLへ
 * - 1日5件ずつ投稿、進捗はproduct IDで管理
 * Usage: node run.js /tmp/playwright-rakuten-room-supabase.js [--login] [--dry-run]
 */
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');
const os = require('os');
const https = require('https');

const DAILY_LIMIT = 5;
const PROFILE_DIR = path.join(os.homedir(), '.rakuten-room-profile');
const PROGRESS_FILE = '/Users/NaohideKin/Desktop/AI関連/claude/outdoor-affiliate/data/rakuten-room-supabase-progress.json';
const ENV_FILE = '/Users/NaohideKin/Desktop/AI関連/claude/outdoor-affiliate/.env.local';
const LOGIN_MODE = process.argv.includes('--login');
const DRY_RUN = process.argv.includes('--dry-run');

// .env.local から環境変数を読み込む
function loadEnv() {
  const vars = {};
  try {
    const env = fs.readFileSync(ENV_FILE, 'utf-8');
    for (const line of env.split('\n')) {
      const m = line.match(/^([A-Z_]+)=(.+)$/);
      if (m) vars[m[1]] = m[2].trim().replace(/^["']|["']$/g, '');
    }
  } catch {}
  return vars;
}

// affiliate_url から item.rakuten.co.jp URL を抽出
function decodeAffiliateUrl(affiliateUrl) {
  try {
    const match = affiliateUrl.match(/[?&]pc=([^&]+)/);
    if (match) return decodeURIComponent(match[1]);
  } catch {}
  // hb.afl.rakuten形式でない場合はそのまま返す
  if (affiliateUrl.includes('item.rakuten.co.jp')) return affiliateUrl;
  return null;
}

// Supabaseから楽天商品を全件取得
async function fetchRakutenProducts(env) {
  return new Promise((resolve) => {
    const body = JSON.stringify({});
    const url = `${env.SUPABASE_URL}/rest/v1/products?affiliate_url=like.*rakuten*&select=id,name,affiliate_url,price&order=created_at.asc&limit=1000`;
    const urlObj = new URL(url);
    const req = https.request({
      hostname: urlObj.hostname,
      path: urlObj.pathname + urlObj.search,
      method: 'GET',
      headers: {
        'apikey': env.SUPABASE_SERVICE_ROLE_KEY,
        'Authorization': `Bearer ${env.SUPABASE_SERVICE_ROLE_KEY}`,
        'Content-Type': 'application/json',
      },
    }, (res) => {
      let data = '';
      res.on('data', d => data += d);
      res.on('end', () => {
        try { resolve(JSON.parse(data)); } catch { resolve([]); }
      });
    });
    req.on('error', () => resolve([]));
    req.end();
  });
}

// Claude Haiku でROOMコメント生成
async function generateRoomComment(productName, apiKey) {
  if (!apiKey) return '';
  const prompt = `楽天ROOMに投稿するキャンプギアの紹介コメントを日本語で書いてください。

商品名: ${productName}

条件:
- 3〜5行、絵文字を適度に使用
- キャンプ好き（長野在住・家族キャンプ・ソロキャンプ）のギア男(@camp_gear_lab)らしいコメント
- 最後に関連ハッシュタグ5〜7個（#キャンプ #アウトドア等）
- 合計500文字以内
- セール・マラソン・クーポン・期間限定・ポイント等の情報は一切含めない
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
        'x-api-key': apiKey,
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

// 進捗管理
function loadProgress() {
  try {
    return JSON.parse(fs.readFileSync(PROGRESS_FILE, 'utf8'));
  } catch {
    return { posted: [], lastRun: null };
  }
}
function saveProgress(progress) {
  fs.writeFileSync(PROGRESS_FILE, JSON.stringify(progress, null, 2));
}

// ===== メイン =====
(async () => {
  const env = loadEnv();

  if (!env.SUPABASE_URL || !env.SUPABASE_SERVICE_ROLE_KEY) {
    console.log('❌ SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY が未設定です');
    process.exit(1);
  }

  // Supabaseから商品取得
  console.log('📡 Supabaseから楽天商品を取得中...');
  const allProducts = await fetchRakutenProducts(env);
  console.log(`  ${allProducts.length}件の楽天商品を確認`);

  // URLデコードして有効な商品のみ
  const validProducts = allProducts
    .map(p => ({ ...p, productUrl: decodeAffiliateUrl(p.affiliate_url) }))
    .filter(p => p.productUrl && p.productUrl.includes('item.rakuten.co.jp'));
  console.log(`  ${validProducts.length}件が直接URL取得可能`);

  const progress = loadProgress();
  const postedSet = new Set(progress.posted);
  const pending = validProducts.filter(p => !postedSet.has(p.id));
  const todayBatch = pending.slice(0, DAILY_LIMIT);

  if (todayBatch.length === 0) {
    console.log('✅ すべての楽天商品を投稿済みです！');
    return;
  }

  console.log(`\n📋 本日の投稿予定 (${DAILY_LIMIT}件/日):`);
  todayBatch.forEach(p => console.log(`  [${p.id}] ${p.name}`));
  console.log('');

  if (DRY_RUN) {
    console.log('🔍 --dry-run モード: 実際の投稿はスキップします');
    return;
  }

  // 永続コンテキストでブラウザ起動
  if (!fs.existsSync(PROFILE_DIR)) fs.mkdirSync(PROFILE_DIR, { recursive: true });
  const browser = await chromium.launchPersistentContext(PROFILE_DIR, {
    headless: !LOGIN_MODE,
    slowMo: LOGIN_MODE ? 600 : 300,
    viewport: { width: 1280, height: 900 },
  });
  const page = browser.pages()[0] || await browser.newPage();

  // ログインモード
  if (LOGIN_MODE) {
    console.log('🔐 ログインモード...');
    const triggerUrl = 'https://room.rakuten.co.jp/mix?itemcode=snowpeak-official%3Aes-070&scid=we_room_upc60';
    await page.goto(triggerUrl, { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(3000);
    console.log('👉 ブラウザで楽天アカウントにログインしてください（最大5分待機）...');
    let loggedIn = false;
    const deadline = Date.now() + 300000;
    while (Date.now() < deadline) {
      await page.waitForTimeout(3000);
      const url = page.url();
      if (url.includes('room.rakuten.co.jp') && !url.includes('login.account.rakuten.com')) {
        const hasForm = await page.evaluate(() =>
          document.querySelector('textarea, input[type="text"], button[type="submit"], form') !== null
        );
        if (hasForm) { loggedIn = true; break; }
      }
    }
    console.log(loggedIn ? '✅ ログイン完了！' : '⚠️  ログイン確認できず');
    await browser.close();
    return;
  }

  // ログイン状態確認
  try {
    await page.goto('https://room.rakuten.co.jp/', { waitUntil: 'domcontentloaded' });
  } catch (_) {}
  await page.waitForTimeout(3000);
  if (page.url().includes('login') || page.url().includes('account.rakuten.com')) {
    console.log('⚠️  ログインが必要です: node run.js /tmp/playwright-rakuten-room-supabase.js --login');
    await browser.close();
    return;
  }
  console.log('✅ ログイン済み\n');

  // ===== 各商品を処理 =====
  let addedCount = 0;
  for (const product of todayBatch) {
    console.log(`[${product.id}] ${product.name}`);

    try {
      // 直接商品ページへ（検索不要）
      await page.goto(product.productUrl, { waitUntil: 'domcontentloaded', timeout: 30000 });
      await page.waitForTimeout(2000);

      // 「ROOMに投稿」リンクを探す
      const roomLinks = await page.locator('a[href*="room.rakuten.co.jp/mix"]').all();
      if (roomLinks.length === 0) {
        console.log('  ⚠️  「ROOMに投稿」ボタン見つからず');
        await page.screenshot({ path: `/tmp/room-debug-${product.id}.png` });
        continue;
      }

      console.log('  👍 「ROOMに投稿」クリック...');
      const [newPage] = await Promise.all([
        browser.waitForEvent('page').catch(() => null),
        roomLinks[0].click(),
      ]);

      const targetPage = newPage || page;
      await targetPage.waitForLoadState('domcontentloaded').catch(() => {});
      await targetPage.waitForTimeout(2000);

      if (targetPage.url().includes('login') || targetPage.url().includes('account.rakuten.com')) {
        console.log('  ⚠️  セッション切れ。--login で再ログインしてください。');
        await browser.close();
        return;
      }

      // コメント入力
      try {
        const textarea = targetPage.locator('textarea').first();
        if (await textarea.isVisible({ timeout: 3000 })) {
          const comment = await generateRoomComment(product.name, env.ANTHROPIC_API_KEY);
          if (comment) {
            await textarea.fill(comment);
            console.log(`  ✏️  コメント: ${comment.substring(0, 40)}...`);
            await targetPage.waitForTimeout(500);
          }
        }
      } catch {}

      // 投稿ボタンをクリック
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
            console.log(`  ✅ 投稿ボタン: "${btnText}" → クリック`);
            await btn.click();
            await targetPage.waitForTimeout(2000);
            posted = true;
            break;
          }
        } catch { continue; }
      }

      if (!posted) {
        const btns = await targetPage.evaluate(() =>
          Array.from(document.querySelectorAll('button, [role="button"], input[type="submit"]'))
            .map(el => ({ text: (el.textContent?.trim() || el.value || '').substring(0, 40), cls: (el.className || '').substring(0, 60) }))
            .filter(b => b.text).slice(0, 10)
        );
        console.log('  ⚠️  投稿ボタン自動検出失敗。ページ上のボタン:', JSON.stringify(btns));
        if (newPage) await newPage.close().catch(() => {});
        continue;
      }

      progress.posted.push(product.id);
      addedCount++;
      console.log('  ✅ 追加完了！');
      if (newPage) await newPage.close().catch(() => {});

    } catch (err) {
      console.log(`  ❌ エラー: ${err.message.substring(0, 100)}`);
    }

    await page.waitForTimeout(2000 + Math.floor(Math.random() * 2000));
  }

  progress.lastRun = new Date().toISOString();
  saveProgress(progress);

  console.log(`\n============================`);
  console.log(`✅ 本日: ${addedCount}/${todayBatch.length} 件追加`);
  console.log(`📊 累計: ${progress.posted.length}/${validProducts.length} 件`);
  console.log(`残り: ${validProducts.length - progress.posted.length} 件`);
  console.log(`============================`);

  await page.waitForTimeout(2000);
  await browser.close();
})();
```

Save to `scripts/rakuten-room-supabase.js`.

- [ ] **Step 2: dry-runで動作確認**

```bash
cd ~/Desktop/AI関連/claude/outdoor-affiliate
node /Users/NaohideKin/.claude/plugins/marketplaces/playwright-skill/skills/playwright-skill/run.js /tmp/playwright-rakuten-room-supabase.js --dry-run
```

Expected output:
```
📡 Supabaseから楽天商品を取得中...
  152件の楽天商品を確認
  NNN件が直接URL取得可能
📋 本日の投稿予定 (5件/日):
  [tent-f01] コールマン タフスクリーン2ルームエアー/MDX+
  ...
🔍 --dry-run モード: 実際の投稿はスキップします
```

- [ ] **Step 3: スクリプトをtmpにコピーしてdry-run実行**

```bash
cp ~/Desktop/AI関連/claude/outdoor-affiliate/scripts/rakuten-room-supabase.js /tmp/playwright-rakuten-room-supabase.js
node /Users/NaohideKin/.claude/plugins/marketplaces/playwright-skill/skills/playwright-skill/run.js /tmp/playwright-rakuten-room-supabase.js --dry-run
```

---

### Task 2: launchd plistを更新

**Files:**
- Modify: `~/Library/LaunchAgents/com.outdoor-affiliate.rakuten-room.plist`

- [ ] **Step 1: plistのスクリプトパスを更新**

`~/Library/LaunchAgents/com.outdoor-affiliate.rakuten-room.plist` の `ProgramArguments` を変更：

```xml
<array>
    <string>/opt/homebrew/bin/node</string>
    <string>/Users/NaohideKin/.claude/plugins/marketplaces/playwright-skill/skills/playwright-skill/run.js</string>
    <string>/Users/NaohideKin/Desktop/AI関連/claude/outdoor-affiliate/scripts/rakuten-room-supabase.js</string>
</array>
```

- [ ] **Step 2: launchdに再読み込み**

```bash
launchctl unload ~/Library/LaunchAgents/com.outdoor-affiliate.rakuten-room.plist
launchctl load ~/Library/LaunchAgents/com.outdoor-affiliate.rakuten-room.plist
launchctl list | grep rakuten
```

Expected: `-  0  com.outdoor-affiliate.rakuten-room`

- [ ] **Step 3: commit**

```bash
cd ~/Desktop/AI関連/claude/outdoor-affiliate
git add scripts/rakuten-room-supabase.js
git commit -m "feat: Rakuten Room自動投稿をSupabase直結版に移行"
```

---

### Task 3: 初回動作テスト（実投稿1件確認）

**Files:**
- Read: `data/rakuten-room-supabase-progress.json`（実行後に確認）
- Read: `logs/rakuten-room.log`（実行後に確認）

- [ ] **Step 1: tmpにコピーして実投稿テスト（1件）**

`DAILY_LIMIT`を1に変更してテスト実行。まずスクリプトを一時的に変更：

```bash
cp ~/Desktop/AI関連/claude/outdoor-affiliate/scripts/rakuten-room-supabase.js /tmp/playwright-rakuten-room-supabase.js
# DAILY_LIMIT=1 に変更
sed -i '' 's/const DAILY_LIMIT = 5/const DAILY_LIMIT = 1/' /tmp/playwright-rakuten-room-supabase.js
node /Users/NaohideKin/.claude/plugins/marketplaces/playwright-skill/skills/playwright-skill/run.js /tmp/playwright-rakuten-room-supabase.js
```

- [ ] **Step 2: 進捗ファイルを確認**

```bash
cat ~/Desktop/AI関連/claude/outdoor-affiliate/data/rakuten-room-supabase-progress.json
```

Expected: `posted`配列に1件のproduct IDが追加されている

- [ ] **Step 3: 楽天ROOMでPinterest同様に確認**

楽天ROOMのマイページ（https://room.rakuten.co.jp/room_XXXX）で投稿が追加されていることを確認。

