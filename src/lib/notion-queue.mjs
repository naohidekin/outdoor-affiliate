/**
 * Notion REST API ヘルパー — notion-poster.js 専用
 *
 * Notion SDK は不要。native https で直接 REST API を叩く。
 * IPv4 強制 (family: 4) で undici のタイムアウト問題を回避。
 */

import https from "https";

const NOTION_VERSION = "2022-06-28";
const NOTION_HOST = "api.notion.com";

// ─── 低レベル HTTP ─────────────────────────────────────

function notionRequest(method, path, body, token) {
  return new Promise((resolve, reject) => {
    const data = body ? JSON.stringify(body) : null;
    const options = {
      hostname: NOTION_HOST,
      port: 443,
      path,
      method,
      family: 4,
      headers: {
        Authorization: `Bearer ${token}`,
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
        ...(data ? { "Content-Length": Buffer.byteLength(data) } : {}),
      },
    };
    const req = https.request(options, (res) => {
      const chunks = [];
      res.on("data", (c) => chunks.push(c));
      res.on("end", () => {
        const text = Buffer.concat(chunks).toString("utf-8");
        try {
          resolve({ status: res.statusCode, body: JSON.parse(text) });
        } catch {
          resolve({ status: res.statusCode, body: text });
        }
      });
    });
    req.on("error", reject);
    if (data) req.write(data);
    req.end();
  });
}

// ─── 公開 API ──────────────────────────────────────────

/**
 * Notion DB から approved ページを最大 20 件取得。
 *
 * @param {string} databaseId
 * @param {object} opts
 * @param {string} opts.statusField   ステータスプロパティ名 (default: "ステータス")
 * @param {string} opts.approvedValue フィルタ値 (default: "approved")
 * @param {string} token              Notion Integration Token
 * @returns {Promise<object[]>}       Notion Page オブジェクトの配列
 */
export async function queryApproved(
  databaseId,
  { statusField = "ステータス", approvedValue = "approved" } = {},
  token
) {
  const res = await notionRequest(
    "POST",
    `/v1/databases/${databaseId}/query`,
    {
      filter: {
        property: statusField,
        select: { equals: approvedValue },
      },
      page_size: 20,
    },
    token
  );
  if (res.status !== 200) {
    throw new Error(
      `Notion query failed (DB: ${databaseId}, status: ${res.status}): ${JSON.stringify(res.body)}`
    );
  }
  return res.body.results || [];
}

/**
 * ページのステータスを "posted" に更新し、投稿日時を記録する。
 *
 * @param {string} pageId
 * @param {object} opts
 * @param {string} opts.statusField    ステータスプロパティ名
 * @param {string} opts.statusValue    更新後の値 (default: "posted")
 * @param {string} opts.postedAtField  投稿日時プロパティ名
 * @param {string} opts.postUrl        投稿後の X URL（オプション）
 * @param {string} token
 */
export async function markPosted(
  pageId,
  {
    statusField = "ステータス",
    statusValue = "posted",
    postedAtField = "投稿日時",
    postUrl = null,
  } = {},
  token
) {
  const properties = {
    [statusField]: { select: { name: statusValue } },
    [postedAtField]: { date: { start: new Date().toISOString() } },
  };
  if (postUrl) {
    properties["投稿URL"] = { url: postUrl };
  }
  const res = await notionRequest(
    "PATCH",
    `/v1/pages/${pageId}`,
    { properties },
    token
  );
  if (res.status !== 200) {
    throw new Error(
      `Notion update failed (page: ${pageId}, status: ${res.status}): ${JSON.stringify(res.body)}`
    );
  }
  return res.body;
}

// ─── プロパティ抽出ヘルパー ────────────────────────────

/**
 * rich_text プロパティからプレーンテキストを抽出。
 */
export function extractText(property) {
  if (!property) return "";
  const rt = property.rich_text || [];
  return rt.map((r) => r.plain_text || "").join("");
}

/**
 * title プロパティからプレーンテキストを抽出。
 */
export function extractTitle(property) {
  if (!property) return "";
  const rt = property.title || [];
  return rt.map((r) => r.plain_text || "").join("");
}

/**
 * url プロパティから URL 文字列を取得。
 */
export function extractUrl(property) {
  return property?.url || null;
}

/**
 * X / Twitter の投稿 URL から tweet ID を抽出。
 * https://x.com/username/status/1234567890 → "1234567890"
 */
export function extractTweetId(url) {
  if (!url) return null;
  const match = url.match(/\/status\/(\d+)/);
  return match ? match[1] : null;
}
