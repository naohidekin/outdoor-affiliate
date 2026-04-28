import { google } from "googleapis";

const SITE_URL = "https://camp-gear-lab.com";
const SITEMAP_URL = `${SITE_URL}/sitemap.xml`;

function getCredentials() {
  const credentialsJson = process.env.INDEXING_CREDENTIALS;
  if (!credentialsJson) return null;
  try {
    return JSON.parse(credentialsJson);
  } catch {
    return null;
  }
}

/**
 * Google Indexing API に URL_UPDATED 通知を送る
 * 認証情報がない場合や失敗時はログだけ出して静かに失敗する
 */
export async function notifyGoogleIndex(slug: string): Promise<void> {
  const credentials = getCredentials();
  if (!credentials) {
    console.log("[Indexing] INDEXING_CREDENTIALS が未設定のためスキップ");
    return;
  }

  try {
    const auth = new google.auth.GoogleAuth({
      credentials,
      scopes: ["https://www.googleapis.com/auth/indexing"],
    });

    const indexing = google.indexing({ version: "v3", auth });

    const url = `${SITE_URL}/articles/${slug}`;
    await indexing.urlNotifications.publish({
      requestBody: { url, type: "URL_UPDATED" },
    });

    console.log(`[Indexing] ✅ ${url}`);
  } catch (e: unknown) {
    const msg = e instanceof Error ? e.message : String(e);
    console.error(`[Indexing] ❌ ${slug}: ${msg}`);
  }
}

/**
 * Search Console にサイトマップ再送信を依頼
 * 認証情報がない場合や失敗時はログだけ出して静かに失敗する
 */
export async function resubmitSitemap(): Promise<void> {
  const credentials = getCredentials();
  if (!credentials) {
    console.log("[Sitemap] INDEXING_CREDENTIALS が未設定のためスキップ");
    return;
  }

  try {
    const auth = new google.auth.GoogleAuth({
      credentials,
      scopes: ["https://www.googleapis.com/auth/webmasters"],
    });

    const sc = google.searchconsole({ version: "v1", auth });
    await sc.sitemaps.submit({
      siteUrl: `${SITE_URL}/`,
      feedpath: SITEMAP_URL,
    });

    console.log(`[Sitemap] ✅ resubmitted ${SITEMAP_URL}`);
  } catch (e: unknown) {
    const msg = e instanceof Error ? e.message : String(e);
    console.error(`[Sitemap] ❌ ${msg}`);
  }
}

/**
 * 記事公開時に呼ぶ統合フック
 * - 個別URLを Indexing API で push
 * - サイトマップを GSC に再送信
 * 失敗してもAPIレスポンスを止めないため、すべて静かに処理
 */
export async function triggerPostPublishIndexing(slug: string): Promise<void> {
  await Promise.allSettled([notifyGoogleIndex(slug), resubmitSitemap()]);
}
