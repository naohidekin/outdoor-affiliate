# Outdoor Gear Lab — Lake & Sky リブランディング 設計書

**作成日**: 2026-04-06
**対象**: outdoor-affiliate (Next.js 16 + Tailwind v4 + App Router)
**ブランチ**: redesign/lake-and-sky

---

## 0. ゴール

- 現状の「土・焚火・林間」系（緑/茶/ベージュ）を全廃し、「白×青×清涼感」に
  全面リニューアル
- 運営者「ギア男」の実在感を立ち上げ、量産型アフィサイトの上から目線を排除
- 既存の AffiliateLink / next/image / RSS / /admin / data/articles.json スキーマ /
  並走中の X 運用ブランチを **壊さない**
- 段階的チェックポイント方式で、各段で巻き戻し可能な粒度で進める

---

## 1. デザイン方針（Lake & Sky）

### 1.1 トーン
- 朝の湖面、青空、雪山稜線を想起させる清涼系
- 余白を贅沢に、情報密度は絞る
- モバイルファースト
- 参考: Apple Newsroom, Stripe Blog, Outside Magazine

### 1.2 カラーパレット

3 階層で管理：

**プリミティブ層**（生の値、直接 className では使わない）

| カテゴリ | 名前 | 値 |
|---|---|---|
| Neutral | white | #FFFFFF |
| Neutral | snow | #FAFBFC |
| Neutral | mist | #F4F7FB |
| Neutral | line | #E2E8F0 |
| Neutral | line-soft | #EDF2F7 |
| Neutral | slate-400 | #94A3B8 |
| Neutral | slate-500 | #64748B |
| Neutral | slate-600 | #475569 |
| Neutral | ink | #1A1F2E |
| Neutral | ink-strong | #0F1420 |
| Lake | lake-50 | #EBF4FF |
| Lake | lake-100 | #DBEAFE |
| Lake | lake-200 | #BFDBFE |
| Lake | lake-400 | #60A5FA |
| Lake | lake-500 | #3B82F6 |
| Lake | lake-600 | #2B6CB0 ★メイン |
| Lake | lake-700 | #1E40AF |
| Lake | lake-800 | #1E3A8A |

**セマンティック層**（実コンポーネントから参照）

| 用途 | 変数 | 参照先 |
|---|---|---|
| 全体背景 | --bg-base | snow #FAFBFC |
| カード/モーダル背景 | --bg-card | white #FFFFFF |
| 弱い背景 | --bg-muted | mist |
| ハイライト背景 | --bg-highlight | lake-50 |
| 本文テキスト | --text-base | ink |
| 見出し | --text-strong | ink-strong |
| 弱め本文 | --text-muted | slate-600 |
| キャプション | --text-caption | slate-400 |
| リンク | --text-link | lake-600 |
| リンク hover | --text-link-hover | lake-800 |
| メインアクセント | --accent | lake-600 |
| 引用枠ボーダー | --border-quote | lake-800 |
| 罫線 | --border-base | line |

**Tailwind 公開層**: `@theme inline` で `lake-50〜800` `snow` `mist` `ink` `ink-strong` `line` `line-soft` 等を Tailwind ユーティリティとして公開する。

### 1.3 タイポグラフィ

- フォント: **Inter + Noto Sans JP** に統一（DM Sans 廃止）
- ウェイト: 400 / 500 / 600 のみ。**Bold (700) は使わない**
- 例外: 記事 H1 タイトルのみ 600 を許可
- 本文中の強調 (`<strong>`): **font-weight 500 + lake-700 の青色**
- 本文サイズ: 17px / line-height 1.85 / letter-spacing 0.005em
- 日本語は `font-feature-settings: "palt"` で字間自動調整

### 1.4 装飾ルール
- 太字は 1 記事 5〜8 箇所まで（writing-style.md と整合）
- 色つきは青系 1 色のみ（赤・緑・黄は使わない）
- マーカー: lake-50 背景ハイライト
- 引用: 左に 4px lake-800 ボーダー + lake-50 背景、斜体は使わない
- 角丸: rounded-lg 控えめ、影は使わないか極薄

### 1.5 レイアウト
- Header: 白背景 + 細い下線、sticky、Lake アクセント
- Footer: 白基調に変更（旧: ダークブラウン）、淡い区切り線
- コンテンツ幅: 記事本文 max-w-2xl (672px)、トップ max-w-6xl

---

## 2. キャラクター

`docs/author-profile.md` を正本とする。

- 名前: **ギア男**（一本化、「ケンタ」呼称は廃止）
- 37 歳 / 長野 / キャンプ歴 10 年（2016 年〜）
- 妻 + 子ども 2 人（小学校低学年〜中学年の男女）
- 本職: 医師（About / プロフィールページのみ。記事本文では基本出さない）
- メイン装備: アメニティドーム L（旧）+ メッシュタープのドッキングスタイル
- 儀式: サイトに着いたらまずスタンレー グロウラーで一杯

愛用ギアは `docs/author-gear.md` から引用必須。

---

## 3. 記事文体

`docs/writing-style.md` を正本とする。

- ですます調 + 一人称「私」
- 断言型は維持しつつ上から目線を排除
- 太字 5〜8 箇所まで
- 構成: タイトル → リード → 基礎 → 比較表 → 各製品評価 → ギア男の結論 → まとめ
- X ポスト引用 2〜5 個 / 記事
- 画像差し込み: カバー + 各 H2 + 本文中 2〜3 枚

---

## 4. 新規コンポーネント

### 4.1 XEmbed
- パス: `src/components/XEmbed.tsx`
- モード: `card`（自前カード優先）/ 将来 `embed`（widgets.js）
- 表示要素: アバター/プレースホルダー、表示名、@ID、本文、投稿日、X 公式アイコン、引用元リンク
- スタイル: 白背景 + line ボーダー + lake-600 アクセント
- 詳細: `docs/xembed-usage.md`

### 4.2 Img（画像 ID 解決）
- パス: `src/components/Img.tsx`
- `data/images.json` から ID で解決
- 自前撮影への差し替えを容易に
- 詳細: `docs/image-guidelines.md`

### 4.3 ArticleContent 拡張
- `::xpost{url="..."}` パーサー追加
- `::img{id="..."}` パーサー追加
- 既存 `{{product:...}}` `{{comparison:...}}` `{{ranking:...}}` は維持

---

## 5. 画像運用

`docs/image-guidelines.md` を正本とする。

- ソース優先: 自前撮影 → Unsplash → Pexels → メーカー公式/楽天/Amazon
- `next.config.ts` の `remotePatterns` に Unsplash/Pexels を追加
- `data/images.json` で一元管理し、`::img{id="..."}` で参照
- クレジット表記必須

---

## 6. 移行戦略（チェックポイント方式）

旧トークン（緑/茶/ベージュ）は段階的に置換。各チェックポイントで停止、
スクリーンショット報告、ユーザー承認後に次段へ。

| ✓ | チェックポイント | スコープ |
|---|---|---|
| A | globals.css 新トークン追加 + layout.tsx + Header + Footer 切替 |
| B | トップページ (page.tsx) 切替 |
| C | 商品系コンポーネント (ProductCard / ComparisonTable / RankingList) 切替 |
| D | 記事ページ + prose スタイル切替 + カテゴリページ切替 |
| E | 旧変数 (--brand-green, --brand-brown, --color-legacy-*) 削除 |
| F | XEmbed / Img / ArticleContent 拡張 / data/images.json |
| G | サンプル記事リライト（アメドL ユーザー視点比較） |
| H | 旗艦記事新規作成（アメドL 10 年レビュー） |

各チェックポイントで以下を取得：
- スクリーンショット 6 枚（index, articles/[代表], category/[代表] × 375px / 1280px）
- 実装したファイル一覧
- 影響範囲のサマリ

---

## 7. 触らない領域

以下は X 運用ブランチが並走しているため**変更禁止**：

- `src/app/admin/x-posts/` 配下
- `src/app/api/x-posts/` 配下
- `scripts/generate-x-posts.js`
- `scripts/queue-to-sheets.js`
- `src/lib/sheets-xposts.ts`

また以下は機能的に維持：
- AffiliateLink, next/image, RSS, /admin
- data/articles.json のスキーマ（content 内容のみ書き換え）
- 既存内部リンク

---

## 8. 確定事項（リンク先）

| 項目 | ファイル |
|---|---|
| 執筆者プロフィール | docs/author-profile.md |
| 愛用ギア正本 | docs/author-gear.md |
| 記事文体ガイド | docs/writing-style.md |
| X ポスト引用ガイド | docs/xembed-usage.md |
| 画像運用ガイド | docs/image-guidelines.md |
| 記事ロードマップ | docs/article-roadmap.md |

---

## 9. 進行ルール

1. 各チェックポイントで停止 → スクリーンショット報告 → ユーザー承認 → 次段
2. 1 ステップでも違和感があれば即巻き戻し可能な粒度
3. すべての作業は redesign/lake-and-sky ブランチ上で
4. 既存の AffiliateLink / next/image / RSS / /admin / X 運用領域を壊さない
5. 迷ったら作業を止めてユーザーに確認
