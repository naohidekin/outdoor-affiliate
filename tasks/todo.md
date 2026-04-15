# camp-gear-lab.com 総合診断依頼（Codex セカンドオピニオン）

## 依頼内容

サイト全体を診断し、**アクセス・インプレッション・エンゲージメント向上**のために「やるべきこと」を優先度付きで洗い出してほしい。

## 現状サマリ（2026-04-15時点）

### サイト概要
- **URL**: https://camp-gear-lab.com
- **技術**: Next.js + Supabase + Vercel
- **コンテンツ**: キャンプギア比較・レビュー記事
- **収益**: 楽天アフィリエイト + Amazonアソシエイト
- **SNS**: X (@camp_gear_lab) — IFTTT経由で自動投稿

### コンテンツ状況
- 公開記事: 29本（published） + 3本（draft、4/16公開予定）
- 商品: 152件（全件imageUrl・affiliateUrl設定済み）
- カテゴリ: 12

### カテゴリ別記事数（偏り大）
| カテゴリ | 記事数 | 未使用商品数 |
|---------|--------|------------|
| テント | 9 | 8+1 |
| シュラフ | 4 | 3 |
| 焚き火台 | 3 | 3 |
| ランタン | 2 | 5+3 |
| バーナー | 2 | 3 |
| ウェア | 2 | 0 |
| テーブル | 2 | 0 |
| バックパック | 1 | 0 |
| 靴 | 1 | 0 |
| タープ | 1 | 3 |
| チェア | 1 | 6 |
| クーラー | 1 | 3 |

### SEO対応状況
- [x] 全記事にFAQ構造化データ（JSON-LD FAQPage）
- [x] 全記事にmetaDescription（65〜118文字）
- [x] 全記事に内部リンク（2〜3箇所）
- [x] 全記事2000文字以上
- [x] Article / BreadcrumbList / Product / HowTo JSON-LD
- [x] sitemap.xml / robots.txt / RSS feed
- [x] OGP画像自動生成
- [x] Google Indexing API連携済み

### パイプライン
- **X投稿パイプライン**: 6エージェント、launchd登録済み
- **記事パイプライン**: 6エージェント、launchd登録済み（水曜週次 + 毎日10:00公開）
- **Supabase同期**: sync-to-supabase.js で JSON→DB差分同期

### 直近の改善（本セッション）
- 薄い記事4本を拡充（1394-1845文字 → 3678-5764文字）
- 内部リンクなし4記事にリンク追加
- 商品カテゴリID不整合20件を修正
- 全商品にimageUrl設定
- 更新8記事のGoogle Indexing再リクエスト
- 明日公開3記事のX宣伝投稿を事前作成

## 診断してほしい観点

1. **コンテンツ戦略**: カテゴリの偏り解消、記事テーマの優先順位、検索ボリュームの高いキーワード
2. **SEO**: 技術的SEO（Core Web Vitals、構造化データ、内部リンク構造）の改善余地
3. **収益化**: アフィリエイト導線、CTAの配置、コンバージョン改善
4. **X/SNS**: 投稿頻度、エンゲージメント向上施策、フォロワー獲得戦略
5. **サイト品質**: UI/UX、ページ速度、モバイル対応
6. **コード品質**: アーキテクチャ、パフォーマンス、セキュリティ
7. **運用**: パイプラインの安定性、監視、エラーハンドリング

## 確認すべき主要ファイル

- `src/app/page.tsx` — トップページ
- `src/app/articles/[slug]/page.tsx` — 記事ページ
- `src/app/category/[slug]/page.tsx` — カテゴリページ
- `src/lib/db.ts` — データアクセス層
- `src/components/ArticleContent.tsx` — 記事本文レンダリング
- `src/components/ComparisonTable.tsx` — 商品比較表
- `data/articles.json` — 記事データ
- `data/products.json` — 商品データ
- `scripts/article-writer-agent.js` — 記事生成
- `scripts/article-publisher-agent.js` — 記事公開
- `scripts/sync-to-supabase.js` — DB同期
- `CLAUDE.md` — 執筆ガイドライン・ペルソナ定義
