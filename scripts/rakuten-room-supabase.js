/**
 * 楽天ROOM Supabase連携版 v2
 * - Supabase productsテーブルから楽天商品を取得
 * - affiliate_urlのpc=パラメータをデコードして直接商品URLへ
 * - 1日5件ずつ投稿、進捗はproduct IDで管理
 * - v2: ボタン検出安定化、リトライ/フォールバック、コメント品質向上
 * Usage: node run.js /tmp/playwright-rakuten-room-supabase.js [--login] [--dry-run]
 */
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');
const os = require('os');
const https = require('https');

const DAILY_LIMIT = 5;
const MAX_FAILURES = 3; // この回数失敗したらスキップ
const PROFILE_DIR = path.join(os.homedir(), '.rakuten-room-profile');
const BASE_DIR = '/Users/NaohideKin/Desktop/AI関連/claude/outdoor-affiliate';
const PROGRESS_FILE = path.join(BASE_DIR, 'data/rakuten-room-supabase-progress.json');
const PRODUCTS_FILE = path.join(BASE_DIR, 'data/products.json');
const ENV_FILE = path.join(BASE_DIR, '.env.local');
const LOGIN_MODE = process.argv.includes('--login');
const DRY_RUN = process.argv.includes('--dry-run');

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

function decodeAffiliateUrl(affiliateUrl) {
  try {
    const match = affiliateUrl.match(/[?&]pc=([^&]+)/);
    if (match) return decodeURIComponent(match[1]);
  } catch {}
  if (affiliateUrl.includes('item.rakuten.co.jp')) return affiliateUrl;
  return null;
}

async function fetchRakutenProducts(env) {
  return new Promise((resolve) => {
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
    req.on('error', (err) => { console.error(`  ❌ Supabase接続エラー: ${err.message}`); resolve([]); });
    req.end();
  });
}

function loadProductsData() {
  try {
    return JSON.parse(fs.readFileSync(PRODUCTS_FILE, 'utf8'));
  } catch { return []; }
}

function getProductContext(productId, productsData) {
  const p = productsData.find(d => d.id === productId);
  if (!p) return '';
  const parts = [];
  if (p.brand) parts.push(`ブランド: ${p.brand}`);
  if (p.price) parts.push(`価格: ¥${p.price.toLocaleString()}`);
  if (p.description) parts.push(`説明: ${p.description.substring(0, 150)}`);
  if (p.specs && Object.keys(p.specs).length > 0) {
    const specStr = Object.entries(p.specs).slice(0, 5).map(([k, v]) => `${k}: ${v}`).join(', ');
    parts.push(`スペック: ${specStr}`);
  }
  if (p.rating) parts.push(`評価: ${p.rating}/5`);
  return parts.length > 0 ? `\n\n商品データ:\n${parts.join('\n')}` : '';
}

function detectCategory(productName) {
  const name = productName.toLowerCase();
  if (/テント|ドーム|シェルター|タープ/.test(name)) return 'テント・タープ';
  if (/シュラフ|寝袋|スリーピング/.test(name)) return 'シュラフ・寝具';
  if (/ランタン|ライト|ランプ/.test(name)) return 'ランタン・照明';
  if (/バーナー|ストーブ|コンロ/.test(name)) return 'バーナー・火器';
  if (/焚き火|焚火|ファイヤー/.test(name)) return '焚き火台';
  if (/チェア|椅子/.test(name)) return 'チェア';
  if (/テーブル/.test(name)) return 'テーブル';
  if (/バック|リュック|パック/.test(name)) return 'バックパック';
  if (/ジャケット|ウェア|レイン/.test(name)) return 'ウェア';
  if (/クーラー|保冷/.test(name)) return 'クーラーボックス';
  if (/キッズ|kids|子ども/.test(name)) return 'キッズギア';
  return 'キャンプギア';
}

async function generateRoomComment(productName, apiKey, productId, productsData) {
  if (!apiKey) return '';
  const category = detectCategory(productName);
  const productContext = getProductContext(productId, productsData);
  const prompt = `楽天ROOMに投稿するキャンプギアの紹介コメントを日本語で書いてください。

商品名: ${productName}
カテゴリ: ${category}${productContext}

ペルソナ:
- 37歳の開業医（内科ホームドクター）、長野在住
- キャンプ歴10年、家族キャンプ中心（妻+子供2人）、たまにソロ
- メイン装備: スノーピーク アメニティドームL + メッシュタープ
- 買う前に徹底比較する「スペック厨」だが偉そうにしない
- 一人称は「僕」

条件:
- 3〜5行、絵文字を適度に使用（多すぎない）
- 実際に使った or 検討した体験をベースにした語り口（「先週のキャンプで〜」「ずっと気になってた〜」等）
- カテゴリに合わせたトーン: テント系→設営の話、シュラフ系→温度感の話、バーナー系→火力や使い勝手の話
- 最後に関連ハッシュタグ5〜7個（#キャンプ #アウトドア等）
- 合計500文字以内
- セール・マラソン・クーポン・期間限定・ポイント等の情報は一切含めない
- 「おすすめです」「ぜひ」等の販促ワードは控えめに
- AIっぽい硬い表現（〜することができます、〜と言えるでしょう）は禁止
- コメント本文のみ出力（JSONや余計な説明は不要）`;

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
    req.on('error', (err) => { console.error(`  ❌ Claude APIエラー: ${err.message}`); resolve(''); });
    req.write(body);
    req.end();
  });
}

function loadProgress() {
  try {
    const data = JSON.parse(fs.readFileSync(PROGRESS_FILE, 'utf8'));
    if (!data.failures) data.failures = {};
    return data;
  } catch {
    return { posted: [], failures: {}, lastRun: null };
  }
}
function recordFailure(progress, productId) {
  progress.failures[productId] = (progress.failures[productId] || 0) + 1;
}
function isMaxFailures(progress, productId) {
  return (progress.failures[productId] || 0) >= MAX_FAILURES;
}
function saveProgress(progress) {
  fs.writeFileSync(PROGRESS_FILE, JSON.stringify(progress, null, 2));
}

(async () => {
  if (!DRY_RUN) {
    const waitMs = Math.floor(Math.random() * 60 * 60 * 1000);
    console.log(`[random delay] ${Math.round(waitMs / 60000)}m before posting...`);
    await new Promise(r => setTimeout(r, waitMs));
  }
  const env = loadEnv();

  if (!env.SUPABASE_URL || !env.SUPABASE_SERVICE_ROLE_KEY) {
    console.log('❌ SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY が未設定です');
    process.exit(1);
  }

  if (!env.ANTHROPIC_API_KEY) {
    console.log('⚠️  ANTHROPIC_API_KEY未設定、コメントなしで投稿します');
  }

  console.log('📡 Supabaseから楽天商品を取得中...');
  const allProducts = await fetchRakutenProducts(env);
  console.log(`  ${allProducts.length}件の楽天商品を確認`);

  const validProducts = allProducts
    .map(p => ({ ...p, productUrl: decodeAffiliateUrl(p.affiliate_url) }))
    .filter(p => p.productUrl && p.productUrl.includes('item.rakuten.co.jp'));
  console.log(`  ${validProducts.length}件が直接URL取得可能`);

  const progress = loadProgress();
  const postedSet = new Set(progress.posted);
  const pending = validProducts.filter(p => !postedSet.has(p.id) && !isMaxFailures(progress, p.id));
  const skippedByFailure = validProducts.filter(p => !postedSet.has(p.id) && isMaxFailures(progress, p.id));
  if (skippedByFailure.length > 0) {
    console.log(`  ⏭️  ${skippedByFailure.length}件を${MAX_FAILURES}回以上失敗のためスキップ`);
  }
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

  const productsData = loadProductsData();
  console.log(`  📦 products.json: ${productsData.length}件の商品データ読込\n`);

  if (!fs.existsSync(PROFILE_DIR)) fs.mkdirSync(PROFILE_DIR, { recursive: true });
  const browser = await chromium.launchPersistentContext(PROFILE_DIR, {
    headless: !LOGIN_MODE,
    slowMo: LOGIN_MODE ? 600 : 300,
    viewport: { width: 1280, height: 900 },
  });
  const page = browser.pages()[0] || await browser.newPage();

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

  let addedCount = 0;
  for (const product of todayBatch) {
    console.log(`[${product.id}] ${product.name}`);

    try {
      await page.goto(product.productUrl, { waitUntil: 'domcontentloaded', timeout: 30000 });
      await page.waitForTimeout(2000);

      // 商品ページが有効か確認（削除・URL変更時はエラーページにリダイレクトされる）
      const currentUrl = page.url();
      const pageTitle = await page.title().catch(() => '');
      const hasError = await page.locator('text=ページが表示できません').count().catch(() => 0);
      if (!currentUrl.includes('item.rakuten.co.jp') || hasError > 0) {
        console.log(`  ⚠️  商品ページ無効（削除またはURL変更）: ${currentUrl.substring(0, 60)}`);
        progress.posted.push(product.id); // スキップ済みとしてマーク
        continue;
      }

      const roomLinks = await page.locator('a[href*="room.rakuten.co.jp/mix"]').all();
      if (roomLinks.length === 0) {
        console.log('  ⚠️  「ROOMに投稿」ボタン見つからず');
        recordFailure(progress, product.id);
        console.log(`  → 失敗記録 (${progress.failures[product.id]}/${MAX_FAILURES})`);
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

      try {
        const textarea = targetPage.locator('textarea').first();
        if (await textarea.isVisible({ timeout: 3000 })) {
          const comment = await generateRoomComment(product.name, env.ANTHROPIC_API_KEY, product.id, productsData);
          if (comment) {
            await textarea.fill(comment);
            console.log(`  ✏️  コメント: ${comment.substring(0, 40)}...`);
            await targetPage.waitForTimeout(500);
          }
        }
      } catch {}

      // 投稿ボタン検出: evaluate()で直接DOMを操作（Playwright locatorより確実）
      // .collect-btn が複数ある場合、最後のものが実際の投稿ボタン
      let posted = false;
      try {
        // まずボタンが描画されるのを待つ
        await targetPage.waitForSelector('.collect-btn', { timeout: 8000 }).catch(() => null);
        await targetPage.waitForTimeout(1000);

        const clickResult = await targetPage.evaluate(() => {
          const btns = document.querySelectorAll('.collect-btn');
          if (btns.length === 0) return { ok: false, count: 0, text: '' };
          // 最後の .collect-btn をクリック（最初のものは画像編集の完了ボタン）
          const target = btns[btns.length - 1];
          const text = (target.textContent || '').trim();
          target.click();
          return { ok: true, count: btns.length, text };
        });

        if (clickResult.ok) {
          console.log(`  🔘 投稿ボタン: "${clickResult.text}" (${clickResult.count}個中最後) → クリック`);
          await targetPage.waitForTimeout(3000);
          posted = true;
        }
      } catch (err) {
        console.log(`  ⚠️  .collect-btn クリックエラー: ${err.message.substring(0, 80)}`);
      }

      // フォールバック: .collect-btn がなかった場合
      if (!posted) {
        try {
          const fallbackResult = await targetPage.evaluate(() => {
            const selectors = ['button[type="submit"]', 'input[type="submit"]'];
            for (const sel of selectors) {
              const btn = document.querySelector(sel);
              if (btn) {
                const text = (btn.textContent || btn.value || '').trim();
                btn.click();
                return { ok: true, text };
              }
            }
            return { ok: false, text: '' };
          });
          if (fallbackResult.ok) {
            console.log(`  🔘 フォールバック: "${fallbackResult.text}" → クリック`);
            await targetPage.waitForTimeout(2000);
            posted = true;
          }
        } catch {}
      }

      if (!posted) {
        const btns = await targetPage.evaluate(() =>
          Array.from(document.querySelectorAll('button, [role="button"], input[type="submit"]'))
            .map(el => ({ text: (el.textContent?.trim() || el.value || '').substring(0, 40), cls: (el.className || '').substring(0, 60) }))
            .filter(b => b.text).slice(0, 10)
        );
        console.log('  ⚠️  投稿ボタン自動検出失敗。ページ上のボタン:', JSON.stringify(btns));
        recordFailure(progress, product.id);
        if (newPage) await newPage.close().catch(() => {});
        continue;
      }

      progress.posted.push(product.id);
      if (progress.failures[product.id]) delete progress.failures[product.id];
      addedCount++;
      console.log('  ✅ 追加完了！');
      if (newPage) await newPage.close().catch(() => {});

    } catch (err) {
      console.log(`  ❌ エラー: ${err.message.substring(0, 100)}`);
      if (err.message.includes('ERR_ABORTED') || err.message.includes('ERR_NAME_NOT_RESOLVED')) {
        progress.posted.push(product.id);
        console.log('  → 無効URLとしてスキップ済みにマーク');
      } else {
        recordFailure(progress, product.id);
        console.log(`  → 失敗記録 (${progress.failures[product.id]}/${MAX_FAILURES})`);
      }
    }

    await page.waitForTimeout(2000 + Math.floor(Math.random() * 2000));
  }

  progress.lastRun = new Date().toISOString();
  saveProgress(progress);

  const failedCount = Object.values(progress.failures).filter(v => v >= MAX_FAILURES).length;
  console.log(`\n============================`);
  console.log(`✅ 本日: ${addedCount}/${todayBatch.length} 件追加`);
  console.log(`📊 累計: ${progress.posted.length}/${validProducts.length} 件`);
  console.log(`残り: ${validProducts.length - progress.posted.length - failedCount} 件`);
  if (failedCount > 0) console.log(`⏭️  永続スキップ: ${failedCount} 件`);
  console.log(`============================`);

  await page.waitForTimeout(2000);
  await browser.close();
})();
