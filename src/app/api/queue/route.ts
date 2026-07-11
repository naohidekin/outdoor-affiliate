import fs from "node:fs";
import fsPromises from "node:fs/promises";
import path from "node:path";
import { NextRequest, NextResponse } from "next/server";
import { isAuthenticated } from "@/lib/auth";

export const runtime = "nodejs";

const HOME = process.env.HOME || "/Users/NaohideKin";

export interface QueueItem {
  id: string;
  business: "gearman" | "amble" | "kodomo" | "jsh" | "drAuto";
  type: "x" | "article" | "threads" | "note";
  status: string;
  text: string;
  title?: string;
  scores?: Record<string, number>;
  avgScore?: number;
  qualityIssues?: { level: string; pattern: string; count: number }[];
  createdAt: string;
  sourceFile: string;
}

function calcAvg(scores: Record<string, number>): number {
  const vals = Object.values(scores).filter((v) => typeof v === "number");
  if (vals.length === 0) return 0;
  return Math.round((vals.reduce((a, b) => a + b, 0) / vals.length) * 10) / 10;
}

function safeRead(filePath: string): string | null {
  try {
    return fs.readFileSync(filePath, "utf8");
  } catch {
    return null;
  }
}

function loadGearmanX(): QueueItem[] {
  const filePath = path.join(
    HOME,
    "Desktop/AI関連/claude/outdoor-affiliate/data/x-posts.json",
  );
  const raw = safeRead(filePath);
  if (!raw) return [];
  try {
    const posts = JSON.parse(raw) as Array<{
      id: string;
      text: string;
      status: string;
      createdAt: string;
      scores?: Record<string, number>;
    }>;
    return posts.map((p) => ({
      id: `gearman-x-${p.id}`,
      business: "gearman" as const,
      type: "x" as const,
      status: p.status,
      text: p.text,
      scores: p.scores,
      avgScore: p.scores ? calcAvg(p.scores) : undefined,
      createdAt: p.createdAt,
      sourceFile: filePath,
    }));
  } catch {
    return [];
  }
}

function loadGearmanArticles(): QueueItem[] {
  const filePath = path.join(
    HOME,
    "Desktop/AI関連/claude/outdoor-affiliate/data/articles.json",
  );
  const qualityPath = path.join(
    HOME,
    "Desktop/AI関連/claude/outdoor-affiliate/data/article-quality-report.json",
  );
  const raw = safeRead(filePath);
  if (!raw) return [];

  let qualityMap: Record<
    string,
    { level: string; pattern: string; count: number }[]
  > = {};
  const qRaw = safeRead(qualityPath);
  if (qRaw) {
    try {
      const qReport = JSON.parse(qRaw) as {
        results: Array<{
          slug: string;
          issues: { level: string; pattern: string; count: number }[];
        }>;
      };
      qReport.results.forEach((r) => {
        qualityMap[r.slug] = r.issues;
      });
    } catch {
      /* ignore */
    }
  }

  try {
    const articles = JSON.parse(raw) as Array<{
      id: string;
      title: string;
      slug: string;
      excerpt?: string;
      status: string;
      createdAt?: string;
      scores?: Record<string, number>;
    }>;
    return articles.map((a) => ({
      id: `gearman-article-${a.id}`,
      business: "gearman" as const,
      type: "article" as const,
      status: a.status,
      text: a.excerpt ?? a.title,
      title: a.title,
      scores: a.scores,
      avgScore: a.scores ? calcAvg(a.scores) : undefined,
      qualityIssues: qualityMap[a.slug],
      createdAt: a.createdAt ?? new Date(0).toISOString(),
      sourceFile: filePath,
    }));
  } catch {
    return [];
  }
}

function loadAmble(): QueueItem[] {
  const filePath = path.join(
    HOME,
    "Desktop/AI関連/claude/san-pedinvestor-x/data/x-posts.json",
  );
  const raw = safeRead(filePath);
  if (!raw) return [];
  try {
    const posts = JSON.parse(raw) as Array<{
      id: string;
      text: string;
      status: string;
      generatedAt?: string;
      score_persona?: number | null;
      score_buzz?: number | null;
      score_ai?: number | null;
      scores?: Record<string, number>;
    }>;
    return posts.map((p) => {
      let scores: Record<string, number> | undefined;
      if (p.scores && Object.keys(p.scores).length > 0) {
        scores = p.scores;
      } else {
        const partial: Record<string, number> = {};
        if (p.score_persona != null) partial.persona = p.score_persona;
        if (p.score_buzz != null) partial.buzz = p.score_buzz;
        if (p.score_ai != null) partial.ai_naturalness = p.score_ai;
        if (Object.keys(partial).length > 0) scores = partial;
      }
      return {
        id: `amble-${p.id}`,
        business: "amble" as const,
        type: "x" as const,
        status: p.status,
        text: p.text,
        scores,
        avgScore: scores ? calcAvg(scores) : undefined,
        createdAt: p.generatedAt ?? new Date(0).toISOString(),
        sourceFile: filePath,
      };
    });
  } catch {
    return [];
  }
}

function loadKodomo(): QueueItem[] {
  const filePath = path.join(
    HOME,
    "Desktop/AI関連/parent-child-medical/data/x/posts.jsonl",
  );
  const raw = safeRead(filePath);
  if (!raw) return [];
  const items: QueueItem[] = [];
  for (const line of raw.split("\n")) {
    const trimmed = line.trim();
    if (!trimmed) continue;
    try {
      const p = JSON.parse(trimmed) as {
        id: string;
        body: string;
        status: string;
        createdAt: string;
        _scores?: Record<string, number>;
        scores?: Record<string, number>;
        score?: number;
      };
      const scores = p._scores ?? p.scores;
      items.push({
        id: `kodomo-${p.id}`,
        business: "kodomo" as const,
        type: "x" as const,
        status: p.status,
        text: p.body,
        scores,
        avgScore: scores ? calcAvg(scores) : (p.score ?? undefined),
        createdAt: p.createdAt,
        sourceFile: filePath,
      });
    } catch {
      /* skip malformed lines */
    }
  }
  return items;
}

function loadJSH(): QueueItem[] {
  const filePath = path.join(
    HOME,
    "dev/threads-japan-mistakes/data/post-queue.json",
  );
  const raw = safeRead(filePath);
  if (!raw) return [];
  try {
    const data = JSON.parse(raw) as {
      posts?: Array<{
        id: string;
        text: string;
        status: string;
        created_at: string;
        scores?: Record<string, number | undefined> & { average?: number };
      }>;
    };
    const posts = Array.isArray(data) ? data : (data.posts ?? []);
    return posts.map((p) => {
      const rawScores = p.scores ? { ...p.scores } : undefined;
      if (rawScores) {
        delete rawScores.average;
        // Remove undefined values
        for (const k of Object.keys(rawScores)) {
          if (rawScores[k] == null) delete rawScores[k];
        }
      }
      const cleanScores =
        rawScores && Object.keys(rawScores).length > 0
          ? (rawScores as Record<string, number>)
          : undefined;
      return {
        id: `jsh-${p.id}`,
        business: "jsh" as const,
        type: "threads" as const,
        status: p.status,
        text: p.text,
        scores: cleanScores,
        avgScore: cleanScores ? calcAvg(cleanScores) : undefined,
        createdAt: p.created_at,
        sourceFile: filePath,
      };
    });
  } catch {
    return [];
  }
}

function parseCsvRows(raw: string): Array<Record<string, string>> {
  const lines = raw.split("\n").filter((l) => l.trim());
  if (lines.length < 2) return [];
  const headers = lines[0].split(",").map((h) => h.trim());
  return lines.slice(1).map((line) => {
    const vals = line.split(",");
    const obj: Record<string, string> = {};
    headers.forEach((h, i) => {
      obj[h] = (vals[i] ?? "").trim();
    });
    return obj;
  });
}

function loadDrAuto(): QueueItem[] {
  // X投稿キュー（x-posts.json）を返す
  const xPostsPath = path.join(
    HOME,
    "Desktop/AI関連/note-dr-auto/data/x-posts.json",
  );
  const raw = safeRead(xPostsPath);
  if (!raw) return [];
  try {
    const posts = JSON.parse(raw) as Array<{
      id: string;
      type: string;
      body: string;
      status: string;
      scores?: Record<string, number> | null;
      avgScore?: number | null;
      generated_at: string;
      pipeline_id?: string | null;
    }>;
    return posts.map((p) => ({
      id: `drAuto-${p.id}`,
      business: "drAuto" as const,
      type: "x" as const,
      status: p.status,
      text: p.body,
      scores: p.scores ?? undefined,
      avgScore: p.avgScore ?? undefined,
      createdAt: p.generated_at,
      sourceFile: xPostsPath,
    }));
  } catch {
    return [];
  }
}

// --- Write-back helpers ---

const FILE_PATHS = {
  gearmanX: path.join(HOME, "Desktop/AI関連/claude/outdoor-affiliate/data/x-posts.json"),
  gearmanArticle: path.join(HOME, "Desktop/AI関連/claude/outdoor-affiliate/data/articles.json"),
  amble: path.join(HOME, "Desktop/AI関連/claude/san-pedinvestor-x/data/x-posts.json"),
  kodomo: path.join(HOME, "Desktop/AI関連/parent-child-medical/data/x/posts.jsonl"),
  jsh: path.join(HOME, "dev/threads-japan-mistakes/data/post-queue.json"),
  drAuto: path.join(HOME, "Desktop/AI関連/note-dr-auto/data/x-posts.json"),
};

async function updateJsonStatus(filePath: string, rawId: string, status: string) {
  const raw = await fsPromises.readFile(filePath, "utf8");
  const items = JSON.parse(raw) as Array<{ id: string; status: string } & Record<string, unknown>>;
  const idx = items.findIndex((i) => i.id === rawId);
  if (idx === -1) throw new Error(`ID not found: ${rawId}`);
  items[idx] = { ...items[idx], status };
  await fsPromises.writeFile(filePath, `${JSON.stringify(items, null, 2)}\n`, "utf8");
}

async function updateJsonlStatus(filePath: string, rawId: string, status: string) {
  const raw = await fsPromises.readFile(filePath, "utf8");
  let found = false;
  const updated = raw.split("\n").map((line) => {
    const trimmed = line.trim();
    if (!trimmed) return line;
    try {
      const obj = JSON.parse(trimmed) as { id: string; status: string } & Record<string, unknown>;
      if (obj.id === rawId) { found = true; return JSON.stringify({ ...obj, status }); }
    } catch { /* skip */ }
    return line;
  });
  if (!found) throw new Error(`ID not found: ${rawId}`);
  await fsPromises.writeFile(filePath, updated.join("\n"), "utf8");
}

async function updateJshStatus(filePath: string, rawId: string, status: string) {
  const raw = await fsPromises.readFile(filePath, "utf8");
  const data = JSON.parse(raw) as { posts?: Array<{ id: string; status: string } & Record<string, unknown>> };
  const posts = Array.isArray(data) ? data : (data.posts ?? []);
  const idx = posts.findIndex((p) => p.id === rawId);
  if (idx === -1) throw new Error(`ID not found: ${rawId}`);
  posts[idx] = { ...posts[idx], status };
  const out = Array.isArray(data) ? posts : { ...data, posts };
  await fsPromises.writeFile(filePath, `${JSON.stringify(out, null, 2)}\n`, "utf8");
}

// --- PATCH: ステータス更新 (全事業共通) ---

export async function PATCH(req: NextRequest) {
  if (!(await isAuthenticated())) {
    return NextResponse.json({ error: "認証が必要です" }, { status: 401 });
  }

  try {
    const body = (await req.json()) as { id?: string; status?: string };
    if (!body.id || !body.status) {
      return NextResponse.json({ error: "id と status が必要です" }, { status: 400 });
    }
    const { id, status } = body;

    if (id.startsWith("gearman-x-")) {
      await updateJsonStatus(FILE_PATHS.gearmanX, id.slice("gearman-x-".length), status);
    } else if (id.startsWith("gearman-article-")) {
      await updateJsonStatus(FILE_PATHS.gearmanArticle, id.slice("gearman-article-".length), status);
    } else if (id.startsWith("amble-")) {
      await updateJsonStatus(FILE_PATHS.amble, id.slice("amble-".length), status);
    } else if (id.startsWith("kodomo-")) {
      await updateJsonlStatus(FILE_PATHS.kodomo, id.slice("kodomo-".length), status);
    } else if (id.startsWith("jsh-")) {
      await updateJshStatus(FILE_PATHS.jsh, id.slice("jsh-".length), status);
    } else if (id.startsWith("drAuto-")) {
      await updateJsonStatus(FILE_PATHS.drAuto, id.slice("drAuto-".length), status);
    } else {
      return NextResponse.json({ error: "不明なID形式です" }, { status: 400 });
    }

    return NextResponse.json({ ok: true, id, status });
  } catch (error) {
    console.error("Queue PATCH error:", error);
    return NextResponse.json({ error: "更新に失敗しました" }, { status: 500 });
  }
}

export async function GET(req: NextRequest) {
  if (!(await isAuthenticated())) {
    return NextResponse.json({ error: "認証が必要です" }, { status: 401 });
  }

  try {
    const items: QueueItem[] = [
      ...loadJSH(),
      ...loadKodomo(),
      ...loadAmble(),
      ...loadGearmanX(),
      ...loadGearmanArticles(),
      ...loadDrAuto(),
    ];

    // 同一IDが複数ソースに存在する場合に備えてデデュープ
    const seen = new Set<string>();
    const deduped = items.filter((item) => {
      if (seen.has(item.id)) return false;
      seen.add(item.id);
      return true;
    });

    deduped.sort(
      (a, b) =>
        new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime(),
    );

    return NextResponse.json(deduped);
  } catch (error) {
    console.error("Queue GET error:", error);
    return NextResponse.json(
      { error: "データ取得に失敗しました" },
      { status: 500 },
    );
  }
}
