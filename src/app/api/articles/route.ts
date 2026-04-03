import { NextRequest, NextResponse } from "next/server";
import { v4 as uuidv4 } from "uuid";
import { isAuthenticated } from "@/lib/auth";
import { getArticles, saveArticle, deleteArticle, getArticleById } from "@/lib/db";
import { Article } from "@/lib/types";
import { notifyGoogleIndex } from "@/lib/indexing";

export async function GET() {
  return NextResponse.json(getArticles());
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

  saveArticle(article);

  if (article.status === "published" && article.slug) {
    notifyGoogleIndex(article.slug).catch(() => {});
  }

  return NextResponse.json(article, { status: 201 });
}

export async function PUT(request: NextRequest) {
  if (!(await isAuthenticated())) {
    return NextResponse.json({ error: "認証が必要です" }, { status: 401 });
  }

  const body = await request.json();
  const existing = getArticleById(body.id);
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

  saveArticle(updated);

  if (updated.status === "published" && updated.slug) {
    notifyGoogleIndex(updated.slug).catch(() => {});
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

  deleteArticle(id);
  return NextResponse.json({ success: true });
}
