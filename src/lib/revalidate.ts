import { revalidatePath } from "next/cache";
import { getCategoryById } from "./db";

// 記事の作成・更新・削除後にISRキャッシュを即時無効化する。
// これが無いと revalidate=21600 の期限まで最大6時間、古いページが配信され続ける。
// 無効化は次のリクエストで再生成される（invalidate方式）
export async function revalidateArticlePages(
  slug: string,
  categoryId?: string
): Promise<void> {
  revalidatePath(`/articles/${slug}`);
  revalidatePath("/"); // トップの新着・記事一覧
  revalidatePath("/sitemap.xml");
  revalidatePath("/feed"); // RSS
  if (categoryId) {
    try {
      const category = await getCategoryById(categoryId);
      if (category) revalidatePath(`/category/${category.slug}`);
    } catch {
      // カテゴリ解決失敗で記事本体の再検証を止めない
    }
  }
}

// 商品データ（価格・画像・スペック）は多数の記事の比較表・カード・JSON-LDに
// 埋め込まれており、どの記事が該当商品を含むかの逆引きよりも全記事の無効化が確実。
// 再生成は各ページへの次アクセス時に分散して走るため負荷スパイクにはならない
export function revalidateAllArticlePages(): void {
  revalidatePath("/articles/[slug]", "page");
  revalidatePath("/category/[slug]", "page");
  revalidatePath("/");
}
