import { google } from "googleapis";

const SITE_URL = "https://camp-gear-lab.com";

/**
 * Google Indexing API に URL_UPDATED 通知を送る
 * 認証情報がない場合や失敗時はログだけ出して静かに失敗する
 */
export async function notifyGoogleIndex(slug: string): Promise<void> {
  const credentialsJson = process.env.INDEXING_CREDENTIALS;
  if (!credentialsJson) {
    console.log("[Indexing] INDEXING_CREDENTIALS が未設定のためスキップ");
    return;
  }

  try {
    const credentials = JSON.parse(credentialsJson);
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
