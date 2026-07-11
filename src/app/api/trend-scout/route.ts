import { NextRequest, NextResponse } from "next/server";
import { isAuthenticated } from "@/lib/auth";

export const runtime = "nodejs";

const BRAVE_API_KEY = process.env.BRAVE_API_KEY || "";

// --- Business-specific default search queries ---
// news: Brave News Search API
// web:  Brave Web Search API

type SearchMode = "news" | "web";

interface QueryConfig {
  label: string;
  queries: { label: string; q: string; mode: SearchMode }[];
}

const BUSINESS_QUERIES: Record<string, QueryConfig> = {
  gearman: {
    label: "ギア男（キャンプ）",
    queries: [
      { label: "キャンプニュース", q: "キャンプ アウトドア ギア 2026", mode: "news" },
      { label: "キャンプX投稿トレンド", q: "キャンプ ギア おすすめ 話題", mode: "web" },
      { label: "スノーピーク・SOTO最新", q: "スノーピーク SOTO ユニフレーム 新製品 2026", mode: "news" },
    ],
  },
  amble: {
    label: "アンブロ（投資）",
    queries: [
      { label: "投資ニュース", q: "NISA 個人投資家 株 2026 話題", mode: "news" },
      { label: "開業医×マネー", q: "開業医 資産運用 医師 投資 話題", mode: "web" },
      { label: "金融トレンド", q: "米国株 インデックス 投資信託 話題 2026", mode: "news" },
    ],
  },
  kodomo: {
    label: "こどもケアラボ（小児医療）",
    queries: [
      { label: "小児科・育児ニュース", q: "育児 子育て 小児科 医療 ニュース 2026", mode: "news" },
      { label: "育児トレンド投稿", q: "子育て 育児 悩み 話題 X Twitter 2026", mode: "web" },
      { label: "子どもの健康", q: "子ども 感染症 ワクチン 予防 最新", mode: "news" },
    ],
  },
  jsh: {
    label: "JSH（訪日外国人・ショッピング）",
    queries: [
      { label: "Japan travel trends", q: "Japan shopping tips tourists trending 2026", mode: "web" },
      { label: "Japan news (EN)", q: "Japan travel tourism shopping guide 2026", mode: "news" },
      { label: "訪日外国人ニュース", q: "インバウンド 訪日外国人 ショッピング 2026", mode: "news" },
    ],
  },
  drAuto: {
    label: "Dr.auto（医師×AI）",
    queries: [
      { label: "医療AI最新", q: "クリニック AI 医療 DX 2026 話題", mode: "news" },
      { label: "開業医トレンド", q: "開業医 経営 医師 AI Claude note 話題", mode: "web" },
      { label: "医療テクノロジー", q: "医療 テクノロジー AI 診断 2026", mode: "news" },
    ],
  },
};

interface BraveWebResult {
  title?: string;
  url?: string;
  description?: string;
  age?: string;
  meta_url?: { hostname?: string };
}

interface BraveNewsResult {
  title?: string;
  url?: string;
  description?: string;
  age?: string;
  source?: { name?: string };
  meta_url?: { hostname?: string };
}

interface TrendResult {
  title: string;
  url: string;
  snippet: string;
  source: string;
  age: string;
  mode: SearchMode;
  queryLabel: string;
}

async function searchBraveWeb(q: string): Promise<BraveWebResult[]> {
  const params = new URLSearchParams({ q, count: "8", freshness: "pw" });
  const res = await fetch(
    `https://api.search.brave.com/res/v1/web/search?${params}`,
    {
      headers: {
        Accept: "application/json",
        "Accept-Encoding": "gzip",
        "X-Subscription-Token": BRAVE_API_KEY,
      },
    },
  );
  if (!res.ok) throw new Error(`Brave Web API ${res.status}`);
  const data = await res.json() as { web?: { results?: BraveWebResult[] } };
  return data.web?.results ?? [];
}

async function searchBraveNews(q: string): Promise<BraveNewsResult[]> {
  const params = new URLSearchParams({ q, count: "8", freshness: "pw" });
  const res = await fetch(
    `https://api.search.brave.com/res/v1/news/search?${params}`,
    {
      headers: {
        Accept: "application/json",
        "Accept-Encoding": "gzip",
        "X-Subscription-Token": BRAVE_API_KEY,
      },
    },
  );
  if (!res.ok) {
    // Fallback to web search on news API error
    console.warn(`Brave News API ${res.status} for "${q}", falling back to web`);
    const webResults = await searchBraveWeb(q);
    return webResults.map((r) => ({
      title: r.title,
      url: r.url,
      description: r.description,
      age: r.age,
      source: { name: r.meta_url?.hostname },
      meta_url: r.meta_url,
    }));
  }
  const data = await res.json() as { results?: BraveNewsResult[] };
  return data.results ?? [];
}

export async function GET(req: NextRequest) {
  if (!(await isAuthenticated())) {
    return NextResponse.json({ error: "認証が必要です" }, { status: 401 });
  }

  if (!BRAVE_API_KEY) {
    return NextResponse.json({ error: "BRAVE_API_KEY が未設定です" }, { status: 500 });
  }

  const { searchParams } = new URL(req.url);
  const business = searchParams.get("business") ?? "jsh";
  const queryIndex = parseInt(searchParams.get("qi") ?? "0", 10);
  const customQ = searchParams.get("q") ?? "";

  const config = BUSINESS_QUERIES[business];
  if (!config) {
    return NextResponse.json({ error: `不明な business: ${business}` }, { status: 400 });
  }

  const queryConf = config.queries[queryIndex] ?? config.queries[0];
  const finalQ = customQ || queryConf.q;
  const { mode, label } = queryConf;

  try {
    let results: TrendResult[] = [];

    if (mode === "news") {
      const raw = await searchBraveNews(finalQ);
      results = raw.map((r) => ({
        title: r.title ?? "",
        url: r.url ?? "",
        snippet: r.description ?? "",
        source: r.source?.name ?? r.meta_url?.hostname ?? "",
        age: r.age ?? "",
        mode,
        queryLabel: label,
      }));
    } else {
      const raw = await searchBraveWeb(finalQ);
      results = raw.map((r) => ({
        title: r.title ?? "",
        url: r.url ?? "",
        snippet: r.description ?? "",
        source: r.meta_url?.hostname ?? "",
        age: r.age ?? "",
        mode,
        queryLabel: label,
      }));
    }

    return NextResponse.json({
      business,
      queryLabel: label,
      queryText: finalQ,
      mode,
      results: results.filter((r) => r.title && r.url),
    });
  } catch (error) {
    console.error("Trend Scout error:", error);
    return NextResponse.json(
      { error: `検索失敗: ${error instanceof Error ? error.message : String(error)}` },
      { status: 502 },
    );
  }
}

// Export config for the frontend to know available queries per business
export async function POST(req: NextRequest) {
  if (!(await isAuthenticated())) {
    return NextResponse.json({ error: "認証が必要です" }, { status: 401 });
  }
  // Return config map for UI
  const config = Object.fromEntries(
    Object.entries(BUSINESS_QUERIES).map(([k, v]) => [
      k,
      { label: v.label, queries: v.queries.map((q, i) => ({ index: i, label: q.label })) },
    ]),
  );
  return NextResponse.json(config);
}
