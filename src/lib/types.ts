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

export type XPostType =
  | "article_promo"
  | "outdoor_tip"
  | "article_repost"
  | "seasonal"
  | "rakuten_sale"
  | "amazon_deal"
  | "news_comment"
  | "gear_story";

export type XPostStatus = "draft" | "approved" | "queued" | "posted";

export type XPostSlot = "morning" | "noon" | "night";

export interface XPost {
  id: string;
  type: XPostType;
  text: string;
  articleSlug: string | null;
  url: string | null;
  hashtags: string;
  status: XPostStatus;
  scheduledDate: string;
  generatedAt: string;
  postedAt: string | null;
  // --- Phase1 拡張（後方互換: 既存A〜J列はそのまま、K〜N列を追加） ---
  /** "HH:MM" 形式の投稿時刻スロット (任意)。IFTTTが対応していなければスケジューラ側で使用 */
  scheduledTime?: string;
  /** 添付画像URL (Sheets「X投稿管理」のimage_url列に渡される) */
  imageUrl?: string;
  /** PRラベル (アフィリンク含む投稿に "*広告を含みます" を自動付与) */
  prLabel?: boolean;
  /** NGワード/誇大表現チェッカーが返した検出メッセージ */
  validationErrors?: string;
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
