/**
 * Pinterest Board Creator v3
 *
 * 既存のChromeプロファイル（ログイン済み）を使用するバージョン
 *
 * 使い方:
 *   1. Chromeを完全に終了する（重要！）
 *   2. npm install puppeteer （未インストールの場合）
 *   3. node scripts/pinterest-create-boards.js
 *
 * 注意:
 *   - 実行前にChromeを完全に閉じてください（プロファイルのロックが必要）
 *   - Chromeが起動中だとプロファイルを使えません
 */

const puppeteer = require("puppeteer");
const readline = require("readline");
const path = require("path");
const fs = require("fs");
const os = require("os");

// ピンコンテンツ読み込み
const pinContentPath = path.join(__dirname, "..", "docs", "pinterest-pin-content.json");
const pinContent = JSON.parse(fs.readFileSync(pinContentPath, "utf-8"));

const PINTEREST_URL = "https://www.pinterest.com";
const SCREENSHOTS_DIR = path.join(__dirname, "..", "screenshots");

if (!fs.existsSync(SCREENSHOTS_DIR)) {
  fs.mkdirSync(SCREENSHOTS_DIR, { recursive: true });
}

// Chromeプロファイルのパスを自動検出
function getChromeProfilePath() {
  const platform = os.platform();
  if (platform === "darwin") {
    return path.join(os.homedir(), "Library", "Application Support", "Google", "Chrome");
  } else if (platform === "win32") {
    return path.join(os.homedir(), "AppData", "Local", "Google", "Chrome", "User Data");
  } else {
    return path.join(os.homedir(), ".config", "google-chrome");
  }
}

// Chrome実行ファイルのパスを検出
function getChromeExecutablePath() {
  const platform = os.platform();
  if (platform === "darwin") {
    return "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
  } else if (platform === "win32") {
    return "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe";
  }
  return "/usr/bin/google-chrome";
}

function waitForUserInput(prompt) {
  const rl = readline.createInterface({ input: process.stdin, output: process.stdout });
  return new Promise((resolve) => rl.question(prompt, () => { rl.close(); resolve(); }));
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function screenshot(page, name) {
  const filepath = path.join(SCREENSHOTS_DIR, `${name}.png`);
  await page.screenshot({ path: filepath, fullPage: false });
  console.log(`  📸 ${filepath}`);
}

async function checkLoggedIn(page) {
  // ログイン状態の確認: 「ログイン」ボタンが存在するかチェック
  const loginBtn = await page.evaluate(() => {
    const buttons = document.querySelectorAll("button");
    for (const b of buttons) {
      const text = b.textContent?.trim();
      if (text === "ログイン" || text === "Log in" || text === "Sign up") {
        return text;
      }
    }
    return null;
  });
  return loginBtn === null; // ログインボタンがなければログイン済み
}

async function createBoardViaURL(page, boardName) {
  const safeName = boardName.replace(/[^a-zA-Z0-9]/g, "_");
  console.log(`\n${"=".repeat(50)}`);
  console.log(`📋 Creating: "${boardName}"`);

  try {
    // ピン作成ページ経由でボードを作成する方法
    // ピン作成時に「新規ボード作成」ができる
    console.log("  Navigating to pin creator...");
    await page.goto(`${PINTEREST_URL}/pin-creation-tool/`, {
      waitUntil: "networkidle2",
      timeout: 15000,
    });
    await sleep(3000);
    await screenshot(page, `${safeName}_01_pin_creation`);

    // ログイン確認
    const isLoggedIn = await checkLoggedIn(page);
    console.log(`  Login status: ${isLoggedIn ? "✅ Logged in" : "❌ NOT logged in"}`);

    if (!isLoggedIn) {
      console.log("  ❌ Not logged in. Please check Chrome profile.");
      return false;
    }

    // ボード選択ドロップダウンを探してクリック
    console.log("  Looking for board selector...");

    // 「ボードを選択」「Select board」などのドロップダウンを探す
    let boardSelectorClicked = false;

    // 方法1: data-test-id
    const boardSelectors = [
      '[data-test-id="board-dropdown-select-button"]',
      '[data-test-id="boardDropdownSelectButton"]',
      '[data-test-id="board-selector"]',
      '[data-test-id="storyboard-selector"]',
    ];
    for (const sel of boardSelectors) {
      const el = await page.$(sel);
      if (el) {
        await el.click();
        boardSelectorClicked = true;
        console.log(`  ✅ Clicked board selector: ${sel}`);
        break;
      }
    }

    // 方法2: テキストで探す
    if (!boardSelectorClicked) {
      boardSelectorClicked = await page.evaluate(() => {
        const elements = document.querySelectorAll("button, [role='button'], div[role='button']");
        for (const el of elements) {
          const text = el.textContent?.trim();
          if (
            text === "ボードを選択" ||
            text === "Select board" ||
            text === "Choose board" ||
            text?.includes("ボードを選択") ||
            text?.includes("Select board")
          ) {
            el.click();
            return true;
          }
        }
        return false;
      });
      if (boardSelectorClicked) console.log("  ✅ Clicked board selector (text match)");
    }

    // 方法3: ページの要素をダンプ
    if (!boardSelectorClicked) {
      console.log("  Dumping page elements...");
      const elements = await page.evaluate(() => {
        const all = document.querySelectorAll("button, [role='button'], input, select, [role='combobox'], [role='listbox']");
        return Array.from(all).map((el, i) => ({
          i,
          tag: el.tagName,
          text: el.textContent?.trim().substring(0, 80),
          role: el.getAttribute("role"),
          aria: el.getAttribute("aria-label"),
          dataTestId: el.getAttribute("data-test-id"),
          type: el.getAttribute("type"),
          placeholder: el.getAttribute("placeholder"),
        }));
      });
      elements.forEach((el) => {
        console.log(`    [${el.i}] <${el.tag}> text="${el.text}" role=${el.role} aria="${el.aria}" data-test="${el.dataTestId}" type=${el.type} placeholder="${el.placeholder}"`);
      });
      await screenshot(page, `${safeName}_02_elements_dump`);
    }

    await sleep(2000);
    await screenshot(page, `${safeName}_03_after_board_selector`);

    if (!boardSelectorClicked) {
      console.log("  ⚠️ Could not find board selector. Will try direct board creation...");
    }

    // 「新しいボードを作成」リンク/ボタンを探す
    console.log("  Looking for 'Create board' option...");
    await sleep(1000);

    let createBoardClicked = false;

    // ドロップダウン内の「新しいボードを作成」を探す
    createBoardClicked = await page.evaluate(() => {
      const elements = document.querySelectorAll("button, a, div, [role='option'], [role='menuitem'], li");
      for (const el of elements) {
        const text = el.textContent?.trim();
        if (
          text === "新しいボードを作成" ||
          text === "Create board" ||
          text === "ボードを作成" ||
          text === "+ Create board" ||
          text === "＋ ボードを作成" ||
          text?.includes("Create board") ||
          text?.includes("ボードを作成")
        ) {
          el.click();
          return true;
        }
      }
      return false;
    });
    if (createBoardClicked) console.log("  ✅ Clicked 'Create board'");

    await sleep(2000);
    await screenshot(page, `${safeName}_04_create_board_dialog`);

    // ボード名入力フィールドを探す
    console.log("  Looking for board name input...");

    // ダイアログ/モーダル内のinputを探す
    let nameInput = null;

    // ダイアログ内を優先的に検索
    const dialogInputSelectors = [
      '[role="dialog"] input[type="text"]',
      '[role="dialog"] input',
      'input[id*="board"]',
      'input[name*="board"]',
      'input[placeholder*="ボード"]',
      'input[placeholder*="board"]',
      'input[placeholder*="Places"]',
      'input[data-test-id="board-name-input"]',
    ];

    for (const sel of dialogInputSelectors) {
      const el = await page.$(sel);
      if (el) {
        const isVisible = await page.evaluate((e) => {
          const rect = e.getBoundingClientRect();
          return rect.width > 0 && rect.height > 0;
        }, el);
        if (isVisible) {
          // 検索バーではないことを確認
          const isSearchBar = await page.evaluate((e) => {
            return e.id === "search-input" || e.getAttribute("aria-label") === "検索する";
          }, el);
          if (!isSearchBar) {
            nameInput = el;
            console.log(`  ✅ Found board name input: ${sel}`);
            break;
          }
        }
      }
    }

    // フォールバック: 全inputからsearch以外を探す
    if (!nameInput) {
      const inputs = await page.$$("input[type='text'], input:not([type])");
      for (const inp of inputs) {
        const info = await page.evaluate((el) => ({
          id: el.id,
          placeholder: el.placeholder,
          ariaLabel: el.getAttribute("aria-label"),
          visible: el.getBoundingClientRect().width > 0,
        }), inp);
        if (info.visible && info.id !== "search-input" && info.ariaLabel !== "検索する") {
          nameInput = inp;
          console.log(`  ✅ Found non-search input: id="${info.id}" placeholder="${info.placeholder}"`);
          break;
        }
      }
    }

    if (!nameInput) {
      console.log("  ❌ Could not find board name input.");
      await screenshot(page, `${safeName}_05_no_input`);
      return false;
    }

    // ボード名を入力
    await nameInput.click({ clickCount: 3 });
    await sleep(300);
    await nameInput.type(boardName, { delay: 80 });
    console.log(`  ✅ Typed: "${boardName}"`);
    await sleep(1000);
    await screenshot(page, `${safeName}_06_name_entered`);

    // 作成ボタンをクリック
    console.log("  Clicking create/submit...");
    let created = false;

    created = await page.evaluate(() => {
      const buttons = document.querySelectorAll("button, [role='button']");
      for (const btn of buttons) {
        const text = btn.textContent?.trim();
        if (
          text === "作成" ||
          text === "Create" ||
          text === "Done" ||
          text === "完了" ||
          text === "Save" ||
          text === "保存"
        ) {
          btn.click();
          return true;
        }
      }
      return false;
    });
    if (created) console.log("  ✅ Clicked create button");

    await sleep(3000);
    await screenshot(page, `${safeName}_07_result`);

    if (created) {
      console.log(`  ✅✅ Board "${boardName}" likely created!`);
      return true;
    }

    console.log(`  ⚠️ Could not confirm creation`);
    return false;
  } catch (error) {
    console.log(`  ❌ Error: ${error.message}`);
    await screenshot(page, `${safeName}_error`).catch(() => {});
    return false;
  }
}

async function main() {
  console.log("🚀 Pinterest Board Creator v3 (Chrome Profile)");
  console.log("=".repeat(50));

  const chromeProfilePath = getChromeProfilePath();
  const chromeExec = getChromeExecutablePath();

  console.log(`📁 Chrome profile: ${chromeProfilePath}`);
  console.log(`🌐 Chrome exec: ${chromeExec}`);

  // Chromeが起動中か確認
  console.log("\n⚠️  重要: Chromeを完全に終了してから実行してください！");
  console.log("   (Chromeが起動中だとプロファイルがロックされます)");
  await waitForUserInput("\nChromeを終了しましたか？ (Enter で続行) ");

  let browser;
  try {
    browser = await puppeteer.launch({
      headless: false,
      executablePath: chromeExec,
      userDataDir: chromeProfilePath,
      defaultViewport: null, // Chromeのデフォルトサイズを使用
      args: [
        "--no-sandbox",
        "--disable-setuid-sandbox",
        "--profile-directory=Default",
      ],
      // Chrome起動時にプロファイルを使う
      ignoreDefaultArgs: ["--enable-automation"],
    });
  } catch (error) {
    console.log(`\n❌ Chrome起動エラー: ${error.message}`);
    console.log("\n💡 Chromeが起動中の場合は終了してから再実行してください。");
    console.log("   または、以下のコマンドでChromeプロセスを終了:");
    console.log("   killall 'Google Chrome'");
    return;
  }

  const page = await browser.newPage();

  // Pinterest にアクセス
  console.log("\n📌 Pinterestにアクセス中...");
  await page.goto(`${PINTEREST_URL}/`, { waitUntil: "networkidle2", timeout: 20000 });
  await sleep(3000);
  await screenshot(page, "00_initial_page");

  // ログイン確認
  const isLoggedIn = await checkLoggedIn(page);
  console.log(`\n🔐 Login status: ${isLoggedIn ? "✅ Logged in!" : "❌ NOT logged in"}`);

  if (!isLoggedIn) {
    console.log("\n⚠️ Pinterestにログインされていません。");
    console.log("   ブラウザでPinterestにログインしてください。");
    await waitForUserInput("\n✅ ログイン完了後、Enterキーを押してください... ");

    // 再確認
    await page.goto(`${PINTEREST_URL}/`, { waitUntil: "networkidle2" });
    await sleep(2000);
    const retryLogin = await checkLoggedIn(page);
    if (!retryLogin) {
      console.log("❌ ログインできていません。終了します。");
      await browser.close();
      return;
    }
  }

  console.log("\n📋 Creating boards via pin creation tool...");

  const results = [];
  for (const board of pinContent.boards) {
    const success = await createBoardViaURL(page, board.name);
    results.push({ name: board.name, success });
    await sleep(3000 + Math.random() * 3000);
  }

  console.log("\n" + "=".repeat(50));
  console.log("📊 Results:");
  const successCount = results.filter((r) => r.success).length;
  for (const r of results) {
    console.log(`  ${r.success ? "✅" : "❌"} ${r.name}`);
  }
  console.log(`\n  ${successCount}/${results.length} boards created`);

  if (successCount < results.length) {
    console.log("\n📋 Board descriptions (手動作成用):");
    for (const board of pinContent.boards) {
      console.log(`\n  【${board.name}】`);
      console.log(`  ${board.description}`);
    }
  }

  await waitForUserInput("\n完了。Enterキーでブラウザを閉じます... ");
  await browser.close();
}

main().catch(console.error);
