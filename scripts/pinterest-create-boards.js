/**
 * Pinterest Board Creator - Puppeteer Script
 *
 * 使い方:
 *   1. npm install puppeteer （未インストールの場合）
 *   2. node scripts/pinterest-create-boards.js
 *   3. ブラウザが開くのでPinterestにログイン
 *   4. ログイン後、ターミナルでEnterキーを押す
 *   5. 自動でボードが作成される
 *
 * 注意:
 *   - Pinterestの自動操作はレート制限に注意（間隔を空けて実行）
 *   - 初回はヘッドレスモードOFFで動作確認推奨
 */

const puppeteer = require("puppeteer");
const readline = require("readline");
const path = require("path");
const fs = require("fs");

// ピンコンテンツ読み込み
const pinContentPath = path.join(__dirname, "..", "docs", "pinterest-pin-content.json");
const pinContent = JSON.parse(fs.readFileSync(pinContentPath, "utf-8"));

const PINTEREST_URL = "https://www.pinterest.com";
const PROFILE_URL = `${PINTEREST_URL}/japanese_guide/`;

// ログイン待ち用
function waitForUserInput(prompt) {
  const rl = readline.createInterface({
    input: process.stdin,
    output: process.stdout,
  });
  return new Promise((resolve) => {
    rl.question(prompt, () => {
      rl.close();
      resolve();
    });
  });
}

// ランダムな待機時間（レート制限回避）
function randomDelay(min = 2000, max = 5000) {
  const delay = Math.floor(Math.random() * (max - min + 1)) + min;
  return new Promise((resolve) => setTimeout(resolve, delay));
}

async function createBoard(page, boardName, boardDescription) {
  console.log(`\n📋 Creating board: "${boardName}"...`);

  try {
    // プロフィールページへ移動
    await page.goto(PROFILE_URL, { waitUntil: "networkidle2" });
    await randomDelay(2000, 3000);

    // 「+」ボタンまたは「ボードを作成」ボタンをクリック
    // Pinterestの UIは変わることがあるので、複数セレクタを試す
    const createBoardSelectors = [
      '[data-test-id="boardCreateButton"]',
      '[data-test-id="create-board-button"]',
      'button[aria-label="Create board"]',
      'button[aria-label="ボードを作成"]',
      '[data-test-id="profile-board-create-section"]',
    ];

    let clicked = false;
    for (const selector of createBoardSelectors) {
      try {
        await page.waitForSelector(selector, { timeout: 3000 });
        await page.click(selector);
        clicked = true;
        console.log(`  ✅ Clicked create button: ${selector}`);
        break;
      } catch {
        // 次のセレクタを試す
      }
    }

    if (!clicked) {
      // フォールバック: "+" アイコンを探す
      const plusButtons = await page.$$("button");
      for (const btn of plusButtons) {
        const text = await page.evaluate((el) => el.textContent, btn);
        if (text && text.includes("+")) {
          await btn.click();
          clicked = true;
          console.log("  ✅ Clicked + button");
          break;
        }
      }
    }

    if (!clicked) {
      console.log("  ❌ Could not find create board button. Trying URL approach...");
      await page.goto(`${PINTEREST_URL}/board/create/`, { waitUntil: "networkidle2" });
      await randomDelay(1000, 2000);
    }

    await randomDelay(1500, 2500);

    // ボード名入力
    const nameSelectors = [
      '#board-name',
      'input[id="boardEditName"]',
      'input[placeholder="Like "Places to Go" or "Recipes to Make""]',
      'input[placeholder*="board"]',
      'input[data-test-id="board-name-input"]',
      'input[type="text"]',
    ];

    let nameInput = null;
    for (const selector of nameSelectors) {
      try {
        nameInput = await page.waitForSelector(selector, { timeout: 3000 });
        if (nameInput) {
          console.log(`  ✅ Found name input: ${selector}`);
          break;
        }
      } catch {
        // 次のセレクタを試す
      }
    }

    if (nameInput) {
      await nameInput.click({ clickCount: 3 }); // 既存テキストを選択
      await nameInput.type(boardName, { delay: 50 });
      console.log(`  ✅ Entered board name: "${boardName}"`);
    } else {
      console.log("  ❌ Could not find name input field");
      return false;
    }

    await randomDelay(1000, 2000);

    // 作成ボタンをクリック
    const createSelectors = [
      'button[data-test-id="board-create-button"]',
      'button[type="submit"]',
      'div[data-test-id="create-board-done-button"]',
    ];

    let created = false;
    for (const selector of createSelectors) {
      try {
        await page.waitForSelector(selector, { timeout: 3000 });
        await page.click(selector);
        created = true;
        console.log("  ✅ Clicked create/submit button");
        break;
      } catch {
        // 次のセレクタを試す
      }
    }

    if (!created) {
      // フォールバック: テキストで探す
      const buttons = await page.$$("button");
      for (const btn of buttons) {
        const text = await page.evaluate((el) => el.textContent, btn);
        if (text && (text.includes("Create") || text.includes("作成"))) {
          await btn.click();
          created = true;
          console.log("  ✅ Clicked create button (text match)");
          break;
        }
      }
    }

    await randomDelay(2000, 3000);

    if (created) {
      console.log(`  ✅ Board "${boardName}" created successfully!`);

      // ボードの説明を追加（ボードページに移動して編集）
      if (boardDescription) {
        console.log("  📝 Adding board description...");
        // ボード編集は作成後に手動で追加する方が確実
        // Pinterest UIでボード → 鉛筆アイコン → 説明追加
      }

      return true;
    }

    console.log(`  ⚠️  Board "${boardName}" may not have been created. Check manually.`);
    return false;
  } catch (error) {
    console.log(`  ❌ Error creating board "${boardName}": ${error.message}`);
    return false;
  }
}

async function main() {
  console.log("🚀 Pinterest Board Creator for Japan Shop Helper");
  console.log("=".repeat(50));

  const browser = await puppeteer.launch({
    headless: false, // ログインのためブラウザを表示
    defaultViewport: { width: 1280, height: 900 },
    args: ["--no-sandbox", "--disable-setuid-sandbox"],
  });

  const page = await browser.newPage();

  // Pinterestにアクセス
  await page.goto(`${PINTEREST_URL}/login/`, { waitUntil: "networkidle2" });

  console.log("\n📌 Pinterestのログインページが開きました。");
  console.log("   ブラウザでログインしてください。");
  await waitForUserInput("\n✅ ログイン完了後、Enterキーを押してください... ");

  // ログイン確認
  await page.goto(PROFILE_URL, { waitUntil: "networkidle2" });
  await randomDelay(2000, 3000);

  console.log("\n📋 Creating boards...");
  console.log("=".repeat(50));

  const results = [];

  for (const board of pinContent.boards) {
    const success = await createBoard(page, board.name, board.description);
    results.push({ name: board.name, success });
    await randomDelay(3000, 6000); // ボード間の待機（レート制限対策）
  }

  console.log("\n" + "=".repeat(50));
  console.log("📊 Results:");
  for (const r of results) {
    console.log(`  ${r.success ? "✅" : "❌"} ${r.name}`);
  }

  console.log("\n📝 Next steps:");
  console.log("  1. 各ボードの説明文を手動で追加（鉛筆アイコンから編集）");
  console.log("  2. 既存ピンを適切なボードに移動");
  console.log("  3. pinterest-pin-content.json の内容を元に新しいピンを作成");

  console.log("\n📋 Board descriptions to add:");
  for (const board of pinContent.boards) {
    console.log(`\n  【${board.name}】`);
    console.log(`  ${board.description}`);
  }

  await waitForUserInput("\n完了。Enterキーでブラウザを閉じます... ");
  await browser.close();
}

main().catch(console.error);
