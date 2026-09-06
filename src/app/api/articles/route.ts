import { NextRequest, NextResponse } from "next/server";
import { v4 as uuidv4 } from "uuid";
import { isAuthenticated } from "@/lib/auth";
import { getArticles, saveArticle, deleteArticle, getArticleById, getProducts } from "@/lib/db";
import { Article } from "@/lib/types";
import { triggerPostPublishIndexing } from "@/lib/indexing";
import { pullFromSupabase } from "@/lib/local-sync";
import { revalidateArticlePages } from "@/lib/revalidate";

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

  // 3. 内部商品IDの本文露出（「（chair-013）」等。読者に見せる文字列ではない）
  const leakedIds = content.match(/[（(][a-z]+-\d{3}[）)]/g);
  if (leakedIds) {
    warnings.push(`本文に内部商品IDが露出: ${[...new Set(leakedIds)].join(", ")}`);
  }

  // 4. タイトルの「◯選」と紐付け商品数の乖離（comparisonタグが無い記事向け。
  //    コツ系記事はタイトルのNが商品数でないことがあるため、乖離が2倍以上の
  //    明白なケースだけ警告する）
  const titleN = article.title?.match(/(\d+)選/);
  if (titleN && compTags.length === 0) {
    const claimed = parseInt(titleN[1]);
    const linked = (article.productIds ?? []).length;
    if (linked > 0 && (claimed >= linked * 2 || linked >= claimed * 2)) {
      warnings.push(`タイトル「${claimed}選」に対して紐付け商品が${linked}件です`);
    }
  }

  // 5. {{price:商品ID}} の参照切れ。表示側はタグを黙って消すので、
  //    ID打ち間違い・価格未登録は「価格の記述が丸ごと消えた本文」になって出る
  const priceTags = [...content.matchAll(/\{\{price:([^}]+)\}\}/g)].map((m) =>
    m[1].trim()
  );
  if (priceTags.length > 0) {
    const products = await getProducts();
    const priceById = new Map(products.map((p) => [p.id, p.price]));
    const broken = [...new Set(priceTags)].filter((id) => !priceById.get(id));
    if (broken.length > 0) {
      warnings.push(
        `{{price:}} が解決できません（存在しないID or 価格未登録）: ${broken.join(", ")}`
      );
    }
  }

  return warnings;
}

export async function GET() {
  // 管理画面専用。公開ページはサーバーコンポーネントが直接db.tsを呼ぶため
  // このAPIを使わない。未認証に返すと、アクセスごとに全記事本文がSupabase
  // から転送され（Egress浪費）、全記事の一括スクレイピング経路にもなる
  if (!(await isAuthenticated())) {
    return NextResponse.json({ error: "認証が必要です" }, { status: 401 });
  }
  return NextResponse.json(await getArticles());
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
    metaDescription: typeof body.metaDescription === "string" ? body.metaDescription.trim() : "",
    productIds: body.productIds || [],
    status: body.status || "draft",
    createdAt: now,
    updatedAt: now,
    publishedAt: body.status === "published" ? now : null,
  };

  await saveArticle(article);

  if (article.slug) {
    await revalidateArticlePages(article.slug, article.categoryId);
  }
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
    metaDescription: typeof body.metaDescription === "string" ? body.metaDescription.trim() : existing.metaDescription,
    updatedAt: now,
    publishedAt:
      body.status === "published" && !existing.publishedAt ? now : existing.publishedAt,
  };

  // 整合性チェックは「公開への遷移時」だけでなく「公開中の記事の再保存」でも走らせる。
  // 従来は公開後の編集がノーチェックで通り、タイトル◯選と本文の乖離等が本番に出ていた
  if (updated.status === "published") {
    const warnings = await checkArticleIntegrity(updated);
    if (warnings.length > 0) {
      return NextResponse.json(
        { error: "公開前チェックに失敗しました", warnings },
        { status: 400 }
      );
    }
  }

  await saveArticle(updated);

  if (updated.slug) {
    await revalidateArticlePages(updated.slug, updated.categoryId);
  }
  // スラッグ変更時は旧URLのキャッシュも消す（残すと旧スラッグで旧本文が生き続ける）
  if (existing.slug && existing.slug !== updated.slug) {
    await revalidateArticlePages(existing.slug, existing.categoryId);
  }

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

  const existing = await getArticleById(id);
  await deleteArticle(id);
  if (existing?.slug) {
    await revalidateArticlePages(existing.slug, existing.categoryId);
  }
  return NextResponse.json({ success: true });
}
