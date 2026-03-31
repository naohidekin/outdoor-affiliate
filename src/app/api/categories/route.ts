import { NextRequest, NextResponse } from "next/server";
import { v4 as uuidv4 } from "uuid";
import { isAuthenticated } from "@/lib/auth";
import { getCategories, saveCategory, deleteCategory } from "@/lib/db";
import { Category } from "@/lib/types";

export async function GET() {
  return NextResponse.json(getCategories());
}

export async function POST(request: NextRequest) {
  if (!(await isAuthenticated())) {
    return NextResponse.json({ error: "認証が必要です" }, { status: 401 });
  }

  const body = await request.json();
  const categories = getCategories();

  const category: Category = {
    id: uuidv4(),
    name: body.name || "",
    slug: body.slug || "",
    description: body.description || "",
    order: body.order ?? categories.length + 1,
  };

  saveCategory(category);
  return NextResponse.json(category, { status: 201 });
}

export async function PUT(request: NextRequest) {
  if (!(await isAuthenticated())) {
    return NextResponse.json({ error: "認証が必要です" }, { status: 401 });
  }

  const body = await request.json();
  const categories = getCategories();
  const existing = categories.find((c) => c.id === body.id);
  if (!existing) {
    return NextResponse.json({ error: "カテゴリが見つかりません" }, { status: 404 });
  }

  const updated: Category = { ...existing, ...body };
  saveCategory(updated);
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

  deleteCategory(id);
  return NextResponse.json({ success: true });
}
