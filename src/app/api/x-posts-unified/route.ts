import { NextResponse } from "next/server";
import fs from "fs";
import path from "path";

interface KodomoPost {
  id: string;
  status: "draft" | "approved" | "posted" | "rejected";
  body: string;
  _ctaIncluded?: boolean;
  _wiseScores?: {
    w: number;
    i: number;
    s: number;
    e: number;
    ai: number;
  };
  createdAt: string;
}

interface SanPediPost {
  id: string;
  status: "draft" | "approved" | "posted" | "rejected" | "skip";
  text: string;
  score_a?: number;
  score_b?: number;
  score_c?: number;
  score_d?: number;
  score_ai?: number;
  generatedAt?: string;
}

async function getKodomoStats() {
  try {
    const postsPath = path.join(
      process.cwd(),
      "..",
      "..",
      "parent-child-medical",
      "data",
      "x",
      "posts.jsonl"
    );

    if (!fs.existsSync(postsPath)) {
      console.warn(`Kodomo posts file not found: ${postsPath}`);
      return {
        totalPosts: 0,
        draftCount: 0,
        approvedCount: 0,
        postedCount: 0,
        wisePassCount: 0,
        wisePassRate: 0,
      };
    }

    const content = fs.readFileSync(postsPath, "utf-8");
    const lines = content
      .split("\n")
      .filter((line) => line.trim().length > 0);
    const posts: KodomoPost[] = lines.map((line) => JSON.parse(line));

    const withWise = posts.filter((p) => p._wiseScores);
    const wisePass = withWise.filter(
      (p) =>
        p._wiseScores!.w >= 2 &&
        p._wiseScores!.i >= 2 &&
        p._wiseScores!.s >= 2 &&
        p._wiseScores!.e >= 2 &&
        p._wiseScores!.ai >= 3
    );

    return {
      totalPosts: posts.length,
      draftCount: posts.filter((p) => p.status === "draft").length,
      approvedCount: posts.filter((p) => p.status === "approved").length,
      postedCount: posts.filter((p) => p.status === "posted").length,
      wisePassCount: wisePass.length,
      wisePassRate:
        withWise.length > 0
          ? Math.round((wisePass.length / withWise.length) * 100)
          : 0,
    };
  } catch (err) {
    console.error("Error fetching kodomo stats:", err);
    return {
      totalPosts: 0,
      draftCount: 0,
      approvedCount: 0,
      postedCount: 0,
      wisePassCount: 0,
      wisePassRate: 0,
    };
  }
}

async function getSanPediStats() {
  try {
    // san-pedinvestor は Google Sheets を使用しているため、
    // ここでは推定データを返す。
    // 実装の際は Google Sheets API を使用するか、
    // ローカルキャッシュファイルを使用することを検討してください。

    // 一応、ローカルファイルがあるか試行
    const sheetsBackupPath = path.join(
      process.cwd(),
      "..",
      "..",
      "..",
      "claude",
      "san-pedinvestor-x",
      "posts.json"
    );

    if (fs.existsSync(sheetsBackupPath)) {
      const content = fs.readFileSync(sheetsBackupPath, "utf-8");
      const posts: SanPediPost[] = JSON.parse(content);

      const withScores = posts.filter(
        (p) =>
          p.score_a != null &&
          p.score_b != null &&
          p.score_c != null &&
          p.score_d != null &&
          p.score_ai != null
      );
      const wisePassed = withScores.filter(
        (p) =>
          p.score_a! >= 2 &&
          p.score_b! >= 2 &&
          p.score_c! >= 2 &&
          p.score_d! >= 2 &&
          p.score_ai! >= 3
      );

      return {
        totalPosts: posts.length,
        draftCount: posts.filter((p) => p.status === "draft").length,
        approvedCount: posts.filter((p) => p.status === "approved").length,
        postedCount: posts.filter((p) => p.status === "posted").length,
        wisePassCount: wisePassed.length,
        wisePassRate:
          withScores.length > 0
            ? Math.round((wisePassed.length / withScores.length) * 100)
            : 0,
      };
    }

    // バックアップファイルがない場合は空の統計を返す
    return {
      totalPosts: 0,
      draftCount: 0,
      approvedCount: 0,
      postedCount: 0,
      wisePassCount: 0,
      wisePassRate: 0,
    };
  } catch (err) {
    console.error("Error fetching san-pedi stats:", err);
    return {
      totalPosts: 0,
      draftCount: 0,
      approvedCount: 0,
      postedCount: 0,
      wisePassCount: 0,
      wisePassRate: 0,
    };
  }
}

export async function GET() {
  try {
    const [kodomo, sanpedi] = await Promise.all([
      getKodomoStats(),
      getSanPediStats(),
    ]);

    return NextResponse.json({
      kodomo,
      sanpedi,
    });
  } catch (err) {
    console.error("Error in /api/x-posts-unified:", err);
    return NextResponse.json(
      { error: "統計の取得に失敗しました" },
      { status: 500 }
    );
  }
}
