const { chromium } = require('playwright');
const os = require('os');
const path = require('path');

const PROFILE_DIR = path.join(os.homedir(), '.rakuten-room-profile');
const URLS = [
  { label: "夏キャンプ 虫対策セット", url: "https://room.rakuten.co.jp/room_naomaru/1800012289290411" },
  { label: "初めてのファミリーキャンプ一式", url: "https://room.rakuten.co.jp/room_naomaru/1800012289289365" },
  { label: "子ども連れ 暑さ対策", url: "https://room.rakuten.co.jp/room_naomaru/1800012289288356" },
  { label: "春秋キャンプ 寒さ対策", url: "https://room.rakuten.co.jp/room_naomaru/1800012289286225" },
  { label: "防災兼用 キャンプギア", url: "https://room.rakuten.co.jp/room_naomaru/1800012289285534" },
];

(async () => {
  const browser = await chromium.launchPersistentContext(PROFILE_DIR, { headless: true });
  const page = browser.pages()[0] || await browser.newPage();

  for (const { label, url } of URLS) {
    try {
      await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 15000 });
      await page.waitForTimeout(2000);
      const finalUrl = page.url();
      const title = await page.title();
      const status = finalUrl.includes('login') ? '❌ ログイン要求' : finalUrl.includes('404') ? '❌ 404' : '✅ アクセス可';
      console.log(label + ': ' + status);
      console.log('  URL: ' + finalUrl);
      console.log('  title: ' + title.slice(0, 80));
    } catch(e) {
      console.log(label + ': ❌ エラー: ' + e.message.slice(0, 60));
    }
  }

  await browser.close();
})();
