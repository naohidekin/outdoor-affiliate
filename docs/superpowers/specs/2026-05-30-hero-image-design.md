# Hero Image System — Design Spec
**Date:** 2026-05-30
**Project:** outdoor-affiliate (camp-gear-lab.com)
**Status:** Approved

---

## 概要

全53記事のページトップにヒーロー画像エリアを追加し、記事タイプに応じて3スタイルを自動切替する。また記事内の製品写真（ProductCard）のimageUrl未設定分を補完する（D）。

---

## スコープ

| フェーズ | 内容 |
|---------|------|
| C | 全記事にヒーロー/アイキャッチ画像を追加（コード＋データ） |
| D | imageUrl未設定の製品を洗い出して補完（データのみ） |

---

## C: ヒーロー画像システム

### 配置

```
[Header]
[Breadcrumb]
★ [HeroImage] ← 追加
[Title (h1)]
[Author / 更新日]
[Quick-pick box]
[Article content]
```

高さ: デスクトップ 300px / モバイル 200px

### 3スタイル自動判定

#### タイプ判定ロジック（`src/lib/hero-type.ts`）

```ts
type HeroType = "tile" | "split" | "photo";

function getHeroType(slug: string): HeroType {
  if (/ranking|おすすめ|budget/.test(slug)) return "tile";
  if (/-vs-|-showdown-|-comparison-|-alternatives/.test(slug)) return "split";
  return "photo";
}
```

---

### スタイル①: Tile（ランキング記事）

**対象slug例:** `tumbler-camp-daily-ranking`, `gas-lantern-ranking`, `camp-chair-ranking`

**レイアウト:**
```
┌─────────────────────────────────┐
│ [img1] [img2] [img3] [img4]     │  ← 2列グリッド or 最大4枚
│ [img5] [img6]                   │
└─────────────────────────────────┘
```

**データソース:** `article.productIds` の先頭4〜6件の `imageUrl`
**外部API:** 不要
**フォールバック:** 画像が2枚未満の場合はPhotoスタイルに降格

**コンポーネント:** `<HeroTile products={products.slice(0, 6)} />`

---

### スタイル②: Split（比較記事）

**対象slug例:** `landlock-vs-landnest-shelter`, `picogrill-vs-tokyocamp-bonfire`, `amenity-dome-vs-landnest-dome`

**レイアウト:**
```
┌──────────────────────────────────┐
│ [製品A画像]  ╲  [製品B画像]      │
│ productIds[0] ╲  productIds[1]   │
│ 製品A名        ╲  製品B名        │
└──────────────────────────────────┘
```

**CSS:** `clip-path: polygon(0 0, 58% 0, 42% 100%, 0 100%)` / `polygon(58% 0, 100% 0, 100% 100%, 42% 100%)`
**オーバーレイ:** 製品名を白テキストでグラデーション背景に表示
**フォールバック:** 製品画像が1枚以下の場合はPhotoスタイルに降格

**コンポーネント:** `<HeroSplit productA={products[0]} productB={products[1]} />`

---

### スタイル③: Photo（ガイド・チェックリスト記事）

**対象slug例:** `family-camp-first-time-guide`, `tarp-setup-guide-for-beginners`, `winter-camp-beginners-checklist`

**データソース:** Unsplash API → `articles.json` の `eyecatch` フィールドに永続保存

**Unsplash検索クエリ生成:**
- 記事タグ or タイトルからキャンプ関連キーワードを抽出
- `camping outdoor [keyword]` でクエリ
- `orientation=landscape` + `w=1200` パラメータ指定

**取得スクリプト:** `scripts/fetch-unsplash-eyecatch.mjs`
- `--dry-run`: URLのみ表示
- `--force`: 既存eyecatchを上書き
- `.env.local` の `UNSPLASH_ACCESS_KEY` を使用

**articles.jsonスキーマ追加:**
```json
{
  "eyecatch": "https://images.unsplash.com/photo-xxxxx?w=1200"
}
```

**フォールバック:** eyecatch未設定の場合は最初のproductImageUrlを使用

**コンポーネント:** `<HeroPhoto src={eyecatch} alt={article.title} />`

---

### HeroImageコンポーネント統合

**ファイル:** `src/components/HeroImage.tsx`

```ts
interface Props {
  article: Article;
  products: Product[];
}

export default function HeroImage({ article, products }: Props) {
  const type = getHeroType(article.slug);
  // type に応じて HeroTile / HeroSplit / HeroPhoto を返す
}
```

**記事ページ側の変更:** `src/app/articles/[slug]/page.tsx`
- `getHeroType` で判定
- ブレッドクラムの直後に `<HeroImage>` を挿入

---

## D: 製品imageUrl補完

### 対象の特定
`data/products.json` から `imageUrl` が空の製品を洗い出す。

### 補完方針
1. 楽天公式店 (`shop.r10s.jp`) の画像URLを優先
2. スノーピーク等メーカー公式 (`img.snowpeak.co.jp` 等) を次点
3. Amazon商品画像URLを最終手段

### 補完スクリプト（任意）
- `scripts/find-missing-imageurl.mjs` で欠損リストを出力
- 各製品をweb検索して画像URLを追加

---

## ファイル変更一覧

| ファイル | 変更種別 | 内容 |
|---------|---------|------|
| `src/lib/hero-type.ts` | 新規 | getHeroType関数 |
| `src/components/HeroImage.tsx` | 新規 | 統合コンポーネント（3スタイル） |
| `src/components/HeroTile.tsx` | 新規 | タイルグリッド |
| `src/components/HeroSplit.tsx` | 新規 | 対角線スプリット |
| `src/components/HeroPhoto.tsx` | 新規 | Unsplash単体写真 |
| `src/app/articles/[slug]/page.tsx` | 修正 | HeroImage挿入 |
| `src/lib/types.ts` | 修正 | Article型に`eyecatch?: string`追加 |
| `data/articles.json` | 修正 | guide記事にeyecatchフィールド追加 |
| `scripts/fetch-unsplash-eyecatch.mjs` | 新規 | Unsplash一括取得スクリプト |

---

## 実装順序

1. `hero-type.ts` 作成（判定ロジック）
2. `HeroPhoto` コンポーネント（最シンプル）
3. `HeroTile` コンポーネント
4. `HeroSplit` コンポーネント
5. `HeroImage` 統合コンポーネント
6. `article/[slug]/page.tsx` に挿入
7. Unsplashバッチスクリプト実行（guide記事のeyecatch取得）
8. D: imageUrl欠損製品の補完

---

## 成功基準

- 全53記事でヒーロー画像が表示される
- スマホ(390px)でもレイアウト崩れなし
- Tileは2枚以上の画像が必要 → 不足時はPhotoにフォールバック
- Splitは左右に異なる製品画像 → 不足時はPhotoにフォールバック
- Unsplash eyecatchはarticles.jsonに永続保存（毎回APIを叩かない）
