import { NextRequest, NextResponse } from "next/server";
import { v4 as uuidv4 } from "uuid";
import { isAuthenticated } from "@/lib/auth";
import { getArticles, saveArticle, deleteArticle, getArticleById, getProducts } from "@/lib/db";
import { Article } from "@/lib/types";
import { triggerPostPublishIndexing } from "@/lib/indexing";
import { pullFromSupabase } from "@/lib/local-sync";

/** 公開前の整合性チェック。警告メッセージの配列を返す（空なら問題なし）*/
async function checkArticleIntegrity(article: Article): Promise<string[]> {
  const warnings: string[] = [];
  const content = article.content || "";

  // 1. 「◯選」タイトル vs comparisonタグのID数
  const titleMatch = article.title?.match(/(\d+)選/);
  if (titleMatch) {
    const claimed = parseInt(titleMatch[1]);
    const compTags = content.match(/\{\{comparison:([^}]+)\}\}/g) || [];
    for (const tag of compTags) {
      const ids = tag.replace(/\{\{comparison:|}\}/g, "").split(",").map((s) => s.trim()).filter(Boolean);
      if (ids.length !== claimed) {
        warnings.push(`タイトル「${claimed}選」に対してcomparisonタグの製品数が${ids.length}件です`);
      }
    }
  }

  // 2. comparisonタグの幽霊ID（productsに存在しないID）
  const compTags = content.match(/\{\{comparison:([^}]+)\}\}/g) || [];
  if (compTags.length > 0) {
    const products = await getProducts();
    const productIdSet = new Set(products.map((p) => p.id));
    for (const tag of compTags) {
      const ids = tag.replace(/\{\{comparison:|}\}/g, "").split(",").map((s) => s.trim()).filter(Boolean);
      const ghosts = ids.filter((id) => !productIdSet.has(id));
      if (ghosts.length > 0) {
        warnings.push(`comparisonタグに存在しない製品ID: ${ghosts.join(", ")}`);
      }
    }
  }

  return warnings;
}

export async function GET() {
  const articles = await getArticles();
  // 管理画面（認証済み）には全件、未認証には公開記事のみ返す
  // （下書き・予約記事の全文が誰でも読める情報露出を防ぐ）
  if (await isAuthenticated()) {
    return NextResponse.json(articles);
  }
  return NextResponse.json(articles.filter((a) => a.status === "published"));
}

export async function POST(request: NextRequest) {
  if (!(await isAuthenticated())) {
    return NextResponse.json({ error: "認証が必要です" }, { status: 401 });
  }

  const body = await request.json();
  const now = new Date().toISOString();

  const article: Article = {
    id: uuidv4(),
    title: body.title || "",
    slug: body.slug || "",
    categoryId: body.categoryId || "",
    content: body.content || "",
    excerpt: body.excerpt || "",
    productIds: body.productIds || [],
    status: body.status || "draft",
    createdAt: now,
    updatedAt: now,
    publishedAt: body.status === "published" ? now : null,
  };

  await saveArticle(article);

  if (article.status === "published" && article.slug) {
    triggerPostPublishIndexing(article.slug).catch(() => {});
    pullFromSupabase().catch(() => {});
  }

  return NextResponse.json(article, { status: 201 });
}

export async function PUT(request: NextRequest) {
  if (!(await isAuthenticated())) {
    return NextResponse.json({ error: "認証が必要です" }, { status: 401 });
  }

  const body = await request.json();
  const existing = await getArticleById(body.id);
  if (!existing) {
    return NextResponse.json({ error: "記事が見つかりません" }, { status: 404 });
  }

  const now = new Date().toISOString();
  const updated: Article = {
    ...existing,
    ...body,
    updatedAt: now,
    publishedAt:
      body.status === "published" && !existing.publishedAt ? now : existing.publishedAt,
  };

  // 公開時に整合性チェック
  if (updated.status === "published" && existing.status !== "published") {
    const warnings = await checkArticleIntegrity(updated);
    if (warnings.length > 0) {
      return NextResponse.json(
        { error: "公開前チェックに失敗しました", warnings },
        { status: 400 }
      );
    }
  }

  await saveArticle(updated);

  if (updated.status === "published" && updated.slug) {
    triggerPostPublishIndexing(updated.slug).catch(() => {});
    pullFromSupabase().catch(() => {});
  }

  return NextResponse.json(updated);
}

export async function DELETE(request: NextRequest) {
  if (!(await isAuthenticated())) {
    return NextResponse.json({ error: "認証が必要です" }, { status: 401 });
  }

  const { searchParams } = new URL(request.url);
  const id = searchParams.get("id");
  if (!id) {
    return NextResponse.json({ error: "IDが必要です" }, { status: 400 });
  }

  await deleteArticle(id);
  return NextResponse.json({ success: true });
}
