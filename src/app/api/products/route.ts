import { NextRequest, NextResponse } from "next/server";
import { v4 as uuidv4 } from "uuid";
import { isAuthenticated } from "@/lib/auth";
import { getProducts, saveProduct, deleteProduct, getProductById } from "@/lib/db";
import { Product } from "@/lib/types";

export async function GET() {
  return NextResponse.json(getProducts());
}

export async function POST(request: NextRequest) {
  if (!(await isAuthenticated())) {
    return NextResponse.json({ error: "認証が必要です" }, { status: 401 });
  }

  const body = await request.json();
  const now = new Date().toISOString();

  const product: Product = {
    id: uuidv4(),
    name: body.name || "",
    brand: body.brand || "",
    price: body.price || 0,
    imageUrl: body.imageUrl || "",
    affiliateUrl: body.affiliateUrl || "",
    amazonUrl: body.amazonUrl || "",
    categoryId: body.categoryId || "",
    specs: body.specs || {},
    description: body.description || "",
    rating: body.rating || 0,
    createdAt: now,
    updatedAt: now,
  };

  saveProduct(product);
  return NextResponse.json(product, { status: 201 });
}

export async function PUT(request: NextRequest) {
  if (!(await isAuthenticated())) {
    return NextResponse.json({ error: "認証が必要です" }, { status: 401 });
  }

  const body = await request.json();
  const existing = getProductById(body.id);
  if (!existing) {
    return NextResponse.json({ error: "商品が見つかりません" }, { status: 404 });
  }

  const updated: Product = {
    ...existing,
    ...body,
    updatedAt: new Date().toISOString(),
  };

  saveProduct(updated);
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

  deleteProduct(id);
  return NextResponse.json({ success: true });
}
