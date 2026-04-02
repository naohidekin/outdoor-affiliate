export interface Category {
  id: string;
  name: string;
  slug: string;
  description: string;
  order: number;
}

export interface Product {
  id: string;
  name: string;
  brand: string;
  price: number;
  imageUrl: string;
  affiliateUrl: string;
  amazonUrl: string;
  categoryId: string;
  specs: Record<string, string>;
  description: string;
  rating: number; // 1-5
  createdAt: string;
  updatedAt: string;
}

export interface FAQ {
  question: string;
  answer: string;
}

export interface Article {
  id: string;
  title: string;
  slug: string;
  categoryId: string;
  content: string; // Markdown
  excerpt: string;
  productIds: string[];
  status: "draft" | "published";
  faqs?: FAQ[];
  metaDescription?: string;
  createdAt: string;
  updatedAt: string;
  publishedAt: string | null;
}
