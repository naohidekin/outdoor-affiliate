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

export interface XPost {
  id: string;
  text: string;
  type: "comparison" | "question" | "failure" | "summary" | "cospa" | "family" | "site-link";
  articleSlug?: string;
  status: "draft" | "approved" | "posted";
  scheduledDay?: string; // e.g. "月", "火", ...
  scheduledTime?: string; // e.g. "07:00", "20:00"
  createdAt: string;
  postedAt?: string;
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
