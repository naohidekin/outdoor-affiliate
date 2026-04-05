/**
 * Pinterest Board Creator v2 - Puppeteer Script
 *
 * 使い方:
 *   1. npm install puppeteer （未インストールの場合）
 *   2. node scripts/pinterest-create-boards.js
 *   3. ブラウザが開くのでPinterestにログイン
 *   4. ログイン後、ターミナルでEnterキーを押す
 *   5. 自動でボードが作成される
 *
 * デバッグ:
 *   - 各ステップでスクリーンショットが screenshots/ に保存される
 *   - 失敗した場合はスクリーンショットを確認してセレクタを調整
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
const SCREENSHOTS_DIR = path.join(__dirname, "..", "screenshots");

// スクリーンショット保存ディレクトリ作成
if (!fs.existsSync(SCREENSHOTS_DIR)) {
  fs.mkdirSync(SCREENSHOTS_DIR, { recursive: true });
}

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

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function screenshot(page, name) {
  const filepath = path.join(SCREENSHOTS_DIR, `${name}.png`);
  await page.screenshot({ path: filepath, fullPage: false });
  console.log(`  📸 Screenshot: ${filepath}`);
}

async function dumpPageInfo(page, label) {
  // ページ上のボタンとinput要素をすべて列挙（デバッグ用）
  const info = await page.evaluate(() => {
    const buttons = Array.from(document.querySelectorAll("button")).map((b, i) => ({
      index: i,
      text: b.textContent?.trim().substring(0, 50),
      ariaLabel: b.getAttribute("aria-label"),
      dataTestId: b.getAttribute("data-test-id"),
      className: b.className?.substring(0, 60),
    }));
    const inputs = Array.from(document.querySelectorAll("input, textarea")).map((inp, i) => ({
      index: i,
      type: inp.type,
      placeholder: inp.placeholder,
      id: inp.id,
      name: inp.name,
      ariaLabel: inp.getAttribute("aria-label"),
      dataTestId: inp.getAttribute("data-test-id"),
    }));
    const links = Array.from(document.querySelectorAll("a")).map((a, i) => ({
      index: i,
      href: a.href,
      text: a.textContent?.trim().substring(0, 50),
    })).filter(a => a.text && a.text.length > 0);
    return { buttons: buttons.slice(0, 30), inputs, links: links.slice(0, 20) };
  });
  console.log(`\n  🔍 [${label}] Page elements:`);
  console.log(`  Buttons (${info.buttons.length}):`);
  info.buttons.forEach((b) => {
    console.log(`    [${b.index}] "${b.text}" aria="${b.ariaLabel}" data-test="${b.dataTestId}"`);
  });
  console.log(`  Inputs (${info.inputs.length}):`);
  info.inputs.forEach((inp) => {
    console.log(`    [${inp.index}] type=${inp.type} placeholder="${inp.placeholder}" id="${inp.id}" aria="${inp.ariaLabel}" data-test="${inp.dataTestId}"`);
  });
  return info;
}

async function createBoard(page, boardName) {
  console.log(`\n${"=".repeat(50)}`);
  console.log(`📋 Creating board: "${boardName}"`);
  console.log("=".repeat(50));

  const safeName = boardName.replace(/[^a-zA-Z0-9]/g, "_");

  try {
    // Step 1: プロフィールページへ移動
    console.log("\n  Step 1: Navigate to profile...");
    await page.goto(PROFILE_URL, { waitUntil: "networkidle2", timeout: 15000 });
    await sleep(3000);
    await screenshot(page, `${safeName}_01_profile`);

    // Step 2: ページの要素を調査
    console.log("\n  Step 2: Analyzing page elements...");
    const profileInfo = await dumpPageInfo(page, "Profile Page");

    // Step 3: 「+」ボタンを探してクリック
    console.log("\n  Step 3: Looking for create/add button...");

    let clicked = false;

    // 方法A: data-test-id で探す
    const testIdSelectors = [
      '[data-test-id="boardCreateButton"]',
      '[data-test-id="create-board-button"]',
      '[data-test-id="profile-board-create-section"]',
      '[data-test-id="add-button"]',
    ];
    for (const sel of testIdSelectors) {
      const el = await page.$(sel);
      if (el) {
        await el.click();
        clicked = true;
        console.log(`  ✅ Clicked: ${sel}`);
        break;
      }
    }

    // 方法B: aria-label で探す
    if (!clicked) {
      const ariaLabels = [
        "Create board", "ボードを作成", "Create", "作成",
        "Add", "追加", "New board", "新しいボード",
      ];
      for (const label of ariaLabels) {
        const el = await page.$(`[aria-label="${label}"]`);
        if (el) {
          await el.click();
          clicked = true;
          console.log(`  ✅ Clicked aria-label: "${label}"`);
          break;
        }
      }
    }

    // 方法C: ボタンテキストで「+」や「Create」を探す
    if (!clicked) {
      clicked = await page.evaluate(() => {
        const buttons = document.querySelectorAll("button, [role='button'], a");
        for (const btn of buttons) {
          const text = btn.textContent?.trim();
          const aria = btn.getAttribute("aria-label") || "";
          if (
            text === "+" ||
            text === "＋" ||
            aria.toLowerCase().includes("create") ||
            aria.includes("作成") ||
            aria.includes("追加")
          ) {
            btn.click();
            return true;
          }
        }
        return false;
      });
      if (clicked) console.log("  ✅ Clicked via text/aria search");
    }

    // 方法D: 保存済みタブの横の「+」アイコン
    if (!clicked) {
      clicked = await page.evaluate(() => {
        // SVG内のpathやアイコンで「+」を探す
        const svgs = document.querySelectorAll("svg");
        for (const svg of svgs) {
          const parent = svg.closest("button, [role='button'], a");
          if (parent) {
            const rect = parent.getBoundingClientRect();
            // プロフィールページ右側の小さなボタンを探す
            if (rect.width < 60 && rect.height < 60 && rect.top > 100) {
              const paths = svg.querySelectorAll("path");
              for (const p of paths) {
                const d = p.getAttribute("d") || "";
                // 「+」アイコンは十字の path を持つ
                if (d.includes("M") && d.length < 100) {
                  parent.click();
                  return true;
                }
              }
            }
          }
        }
        return false;
      });
      if (clicked) console.log("  ✅ Clicked via SVG icon search");
    }

    await sleep(2000);
    await screenshot(page, `${safeName}_02_after_click`);

    if (!clicked) {
      console.log("  ⚠️  Could not find button. Trying dropdown approach...");

      // 方法E: プロフィールの「保存済み」タブをクリックしてからボード作成
      const savedTab = await page.evaluate(() => {
        const links = document.querySelectorAll("a, [role='tab']");
        for (const link of links) {
          const text = link.textContent?.trim();
          if (text === "保存済み" || text === "Saved" || text === "Boards") {
            link.click();
            return true;
          }
        }
        return false;
      });

      if (savedTab) {
        console.log("  ✅ Clicked Saved/Boards tab");
        await sleep(2000);
        await screenshot(page, `${safeName}_02b_saved_tab`);
        await dumpPageInfo(page, "After Saved Tab");

        // 「+」を再度探す
        clicked = await page.evaluate(() => {
          const elements = document.querySelectorAll("button, [role='button'], div[role='button']");
          for (const el of elements) {
            const text = el.textContent?.trim();
            if (text === "+" || text === "＋") {
              el.click();
              return true;
            }
          }
          return false;
        });
        if (clicked) console.log("  ✅ Clicked + after Saved tab");
        await sleep(2000);
      }
    }

    await screenshot(page, `${safeName}_03_modal_check`);

    // Step 4: モーダル/ダイアログ内の要素を調査
    console.log("\n  Step 4: Looking for board name input in modal...");
    const modalInfo = await dumpPageInfo(page, "Modal/Dialog");

    // Step 5: ボード名を入力
    let nameInput = null;

    // input要素を幅広く検索
    const inputSelectors = [
      'input[id="boardEditName"]',
      'input[data-test-id="board-name-input"]',
      'input[placeholder*="Places"]',
      'input[placeholder*="場所"]',
      'input[placeholder*="board"]',
      'input[placeholder*="ボード"]',
      '#board-name',
      // ダイアログ内のinput
      '[role="dialog"] input[type="text"]',
      '[role="dialog"] input',
      'form input[type="text"]',
      // 最後の手段: 最初のテキストinput
      'input[type="text"]',
    ];

    for (const sel of inputSelectors) {
      try {
        nameInput = await page.$(sel);
        if (nameInput) {
          const isVisible = await page.evaluate((el) => {
            const rect = el.getBoundingClientRect();
            return rect.width > 0 && rect.height > 0;
          }, nameInput);
          if (isVisible) {
            console.log(`  ✅ Found input: ${sel}`);
            break;
          }
          nameInput = null;
        }
      } catch {
        // next
      }
    }

    if (!nameInput) {
      console.log("  ❌ Could not find name input. Dumping page HTML snippet...");
      const bodySnippet = await page.evaluate(() => {
        const dialog = document.querySelector('[role="dialog"]');
        if (dialog) return dialog.innerHTML.substring(0, 1000);
        return document.body.innerHTML.substring(0, 1000);
      });
      console.log(`  HTML: ${bodySnippet.substring(0, 500)}`);
      await screenshot(page, `${safeName}_04_failed`);
      return false;
    }

    // 入力
    await nameInput.click({ clickCount: 3 });
    await sleep(300);
    await nameInput.type(boardName, { delay: 80 });
    console.log(`  ✅ Typed: "${boardName}"`);
    await sleep(1000);
    await screenshot(page, `${safeName}_05_name_entered`);

    // Step 6: 作成ボタンをクリック
    console.log("\n  Step 6: Clicking create button...");

    let created = false;
    const submitSelectors = [
      'button[data-test-id="board-create-button"]',
      '[data-test-id="create-board-done-button"]',
      'button[type="submit"]',
      '[role="dialog"] button[type="button"]',
    ];

    for (const sel of submitSelectors) {
      const el = await page.$(sel);
      if (el) {
        const text = await page.evaluate((e) => e.textContent?.trim(), el);
        if (text && (text.includes("Create") || text.includes("作成") || text.includes("Done") || text.includes("完了"))) {
          await el.click();
          created = true;
          console.log(`  ✅ Clicked submit: ${sel} ("${text}")`);
          break;
        }
      }
    }

    // テキストで探すフォールバック
    if (!created) {
      created = await page.evaluate(() => {
        const buttons = document.querySelectorAll("button, [role='button']");
        for (const btn of buttons) {
          const text = btn.textContent?.trim();
          if (text === "Create" || text === "作成" || text === "Done" || text === "完了") {
            btn.click();
            return true;
          }
        }
        return false;
      });
      if (created) console.log("  ✅ Clicked submit via text search");
    }

    await sleep(3000);
    await screenshot(page, `${safeName}_06_result`);

    if (created) {
      console.log(`\n  ✅✅ Board "${boardName}" created!`);
      return true;
    }

    console.log(`\n  ⚠️ Could not confirm creation of "${boardName}"`);
    return false;
  } catch (error) {
    console.log(`  ❌ Error: ${error.message}`);
    await screenshot(page, `${safeName}_error`).catch(() => {});
    return false;
  }
}

async function main() {
  console.log("🚀 Pinterest Board Creator v2 for Japan Shop Helper");
  console.log("=".repeat(50));
  console.log("📸 Screenshots will be saved to: screenshots/");
  console.log("");

  const browser = await puppeteer.launch({
    headless: false,
    defaultViewport: { width: 1280, height: 900 },
    args: ["--no-sandbox", "--disable-setuid-sandbox"],
    // 遅めの操作で安定性向上
    slowMo: 50,
  });

  const page = await browser.newPage();

  // User-Agent設定（bot検出回避）
  await page.setUserAgent(
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
  );

  // Pinterestにアクセス
  await page.goto(`${PINTEREST_URL}/login/`, { waitUntil: "networkidle2" });

  console.log("📌 Pinterestのログインページが開きました。");
  console.log("   ブラウザでログインしてください。");
  await waitForUserInput("\n✅ ログイン完了後、Enterキーを押してください... ");

  // ログイン後の確認
  await page.goto(PROFILE_URL, { waitUntil: "networkidle2" });
  await sleep(3000);
  await screenshot(page, "00_logged_in_profile");

  // まず1つだけ作成してテスト
  console.log("\n🧪 まず最初のボードでテスト...");
  const firstBoard = pinContent.boards[0];
  const testResult = await createBoard(page, firstBoard.name);

  if (!testResult) {
    console.log("\n❌ テストボードの作成に失敗しました。");
    console.log("📸 screenshots/ フォルダのスクリーンショットを確認してください。");
    console.log("   スクリーンショットを共有していただければ、セレクタを修正します。");
    await waitForUserInput("\n続行しますか？ (Enter=続行 / Ctrl+C=終了) ");
  }

  // 残りのボードを作成
  const results = [{ name: firstBoard.name, success: testResult }];
  for (let i = 1; i < pinContent.boards.length; i++) {
    const board = pinContent.boards[i];
    const success = await createBoard(page, board.name);
    results.push({ name: board.name, success });
    await sleep(4000 + Math.random() * 3000);
  }

  console.log("\n" + "=".repeat(50));
  console.log("📊 Results:");
  for (const r of results) {
    console.log(`  ${r.success ? "✅" : "❌"} ${r.name}`);
  }

  console.log("\n📋 Board descriptions (手動で追加してください):");
  for (const board of pinContent.boards) {
    console.log(`\n  【${board.name}】`);
    console.log(`  ${board.description}`);
  }

  await waitForUserInput("\n完了。Enterキーでブラウザを閉じます... ");
  await browser.close();
}

main().catch(console.error);
