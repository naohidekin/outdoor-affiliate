# JSH Pinterest ピン画像 Canvaテンプレート設計書

## 基本仕様

- **サイズ**: 1000 x 1500 px（Pinterest推奨の2:3縦長）
- **フォーマット**: PNG or JPG
- **ファイル命名規則**: `jsh-pin-{board略称}-{番号}.png`

---

## テンプレート A: 商品紹介型（メイン）

全体の70%はこのテンプレート。

```
┌──────────────────────────┐
│                          │
│     [商品画像エリア]       │
│     (上部60%)            │
│                          │
│                          │
├──────────────────────────┤
│  ■ タイトル（白文字）      │
│  ■ 2-3行、太字           │
│    背景: 半透明ダーク      │
│    グラデーション          │
│                          │
├──────────────────────────┤
│  JSH ロゴ + サイトURL     │
│  japan-shop-helper.com   │
│  (下部バー: ブランドカラー) │
└──────────────────────────┘
```

### デザイン詳細
- **背景画像**: 商品のフリー素材 or Canva素材
- **タイトルエリア**: 下部40%に半透明黒グラデーション（opacity 60-70%）
- **タイトルフォント**: Noto Sans（太字）、白、32-40px
- **下部バー**: 高さ80px、色 `#1B7B6B`（JSHグリーン）
- **ロゴ**: JSHロゴ小（白版）+ 「japan-shop-helper.com」白文字 16px

### Canvaでの作り方
1. 「カスタムサイズ」→ 1000 x 1500
2. 背景に商品画像を配置（フル幅）
3. 下半分に長方形（黒、透明度60%）
4. テキスト追加（タイトル）
5. 最下部にブランドバー（長方形 #1B7B6B）
6. JSHロゴとURL配置

---

## テンプレート B: リスト型（ランキング・おすすめ）

全体の20%。「Top 5」「Best 10」系の記事向き。

```
┌──────────────────────────┐
│  ■ タイトル              │
│  "Top 5 Japanese         │
│   Sunscreens 2026"       │
│  背景: ブランドカラー      │
├──────────────────────────┤
│                          │
│  1. [商品画像] 商品名     │
│  2. [商品画像] 商品名     │
│  3. [商品画像] 商品名     │
│  4. [商品画像] 商品名     │
│  5. [商品画像] 商品名     │
│                          │
├──────────────────────────┤
│  JSH ロゴ + サイトURL     │
└──────────────────────────┘
```

### デザイン詳細
- **ヘッダー**: 高さ300px、背景 `#1B7B6B`
- **タイトルフォント**: Noto Sans Bold、白、36-44px
- **リストエリア**: 白背景、各アイテム高さ180px
- **番号**: 丸囲み数字、色 `#E8593E`（アクセント赤）
- **商品画像**: 120x120px 正方形、角丸
- **商品名フォント**: Noto Sans、ダークグレー、20px

---

## テンプレート C: ハウツー型（ガイド記事）

全体の10%。「How to Buy from Japan」系。

```
┌──────────────────────────┐
│  ■ タイトル              │
│  "How to Buy from        │
│   Rakuten Japan"         │
│  背景: グラデーション      │
├──────────────────────────┤
│                          │
│  Step 1  ──────────      │
│  [アイコン] 説明テキスト   │
│                          │
│  Step 2  ──────────      │
│  [アイコン] 説明テキスト   │
│                          │
│  Step 3  ──────────      │
│  [アイコン] 説明テキスト   │
│                          │
├──────────────────────────┤
│  JSH ロゴ + サイトURL     │
└──────────────────────────┘
```

### デザイン詳細
- **ヘッダー**: グラデーション `#1B7B6B` → `#2AA89A`
- **ステップ番号**: 丸囲み、背景 `#E8593E`、白文字
- **アイコン**: Canvaの無料アイコン使用
- **矢印/線**: ステップ間をつなぐ点線（グレー）

---

## カラーパレット

| 用途 | カラーコード | 名前 |
|------|------------|------|
| メインブランド | `#1B7B6B` | JSHグリーン |
| アクセント | `#E8593E` | アクセント赤 |
| テキスト（暗） | `#2D2D2D` | ダークグレー |
| テキスト（明） | `#FFFFFF` | 白 |
| 背景（明） | `#F5F5F0` | オフホワイト |
| 背景（暗） | `#1A1A2E` | ダークネイビー |
| サブカラー | `#2AA89A` | ライトティール |

---

## フォント

| 用途 | フォント | ウェイト | サイズ |
|------|--------|---------|-------|
| メインタイトル | Noto Sans JP / Montserrat | Bold | 36-44px |
| サブタイトル | Noto Sans JP / Open Sans | SemiBold | 24-28px |
| 本文 | Noto Sans JP / Open Sans | Regular | 18-22px |
| URL/ブランド | Montserrat | Medium | 16px |

※ Canvaで利用可能なフォントを優先。英語メインなのでMontserratが最適。

---

## ボード別 量産リスト（最初の30本）

### Japanese Beauty & Skincare（8本）

| # | タイトル（ピン上のテキスト） | テンプレ | 画像キーワード（Canva素材検索用） |
|---|-------------------------|---------|------|
| 1 | Top 5 Japanese Sunscreens You Can Buy Online | B(リスト) | japanese sunscreen, skincare flat lay |
| 2 | Japanese Skincare Routine: 7-Step Guide | C(ハウツー) | skincare routine, woman applying cream |
| 3 | Shiseido vs Kanebo vs SK-II | A(商品) | luxury skincare, japanese cosmetics |
| 4 | Best Japanese Hair Care Products | A(商品) | hair care, shampoo bottles |
| 5 | 10 Japanese Drugstore Beauty Products Under $15 | B(リスト) | drugstore cosmetics, colorful makeup |
| 6 | Best Japanese Eye Creams | A(商品) | eye cream, skincare close-up |
| 7 | DHC Deep Cleansing Oil Review | A(商品) | cleansing oil, face wash |
| 8 | 10 Best Japanese Sheet Masks | B(リスト) | sheet mask, face mask package |

### Japan Travel Essentials（6本）

| # | タイトル | テンプレ | 画像キーワード |
|---|---------|---------|------|
| 1 | Japan SIM Card vs eSIM: Which to Get? | C(ハウツー) | sim card, phone japan |
| 2 | Amazon Japan Hotel Delivery Hack | A(商品) | amazon box, hotel lobby |
| 3 | 10 Must-Have Items for Your Japan Trip | B(リスト) | travel essentials, packing |
| 4 | Best Pocket WiFi for Japan | A(商品) | pocket wifi, tokyo skyline |
| 5 | What to Buy in Japan: 20 Best Souvenirs | B(リスト) | japanese souvenirs, omiyage |
| 6 | Japan IC Cards: Suica & Pasmo Guide | C(ハウツー) | train station, suica card |

### Japanese Food & Snacks（6本）

| # | タイトル | テンプレ | 画像キーワード |
|---|---------|---------|------|
| 1 | Where to Buy Matcha KitKat Online | A(商品) | kitkat matcha, japanese candy |
| 2 | Best Japanese Instant Ramen (Top 10) | B(リスト) | ramen, instant noodles |
| 3 | Japanese Matcha Powder: Best Brands | A(商品) | matcha powder, tea ceremony |
| 4 | Japanese Snack Box Subscriptions Compared | B(リスト) | snack box, unboxing |
| 5 | Japanese Whisky Guide | A(商品) | whisky bottles, japanese whisky |
| 6 | Best Japanese Soy Sauce Brands | A(商品) | soy sauce, japanese cooking |

### How to Buy from Japan（5本）

| # | タイトル | テンプレ | 画像キーワード |
|---|---------|---------|------|
| 1 | How to Buy from Rakuten Japan | C(ハウツー) | online shopping, rakuten |
| 2 | ZenMarket vs Buyee vs Neokyo | B(リスト) | comparison, proxy service |
| 3 | How to Buy from Amazon Japan | C(ハウツー) | amazon japan, international shipping |
| 4 | Yahoo Auctions Japan Guide | C(ハウツー) | auction, bidding |
| 5 | Japan Shopping Fees Explained | C(ハウツー) | calculator, shipping cost |

### Japanese Home & Kitchen（5本）

| # | タイトル | テンプレ | 画像キーワード |
|---|---------|---------|------|
| 1 | Best Japanese Kitchen Knives Guide | A(商品) | chef knife, cutting board |
| 2 | Japanese Cast Iron Teapots (Top 5) | B(リスト) | tetsubin, japanese teapot |
| 3 | Japanese Rice Cookers Compared | A(商品) | rice cooker, zojirushi |
| 4 | 10 Japanese Kitchen Tools You Need | B(リスト) | kitchen tools, cooking |
| 5 | Japandi Interior: 8 Items from Japan | B(リスト) | minimalist room, japandi |

---

## Canva量産ワークフロー

### Step 1: テンプレート作成（3種類）
1. Canvaで「カスタムサイズ 1000x1500」を作成
2. テンプレートA/B/Cをそれぞれ1つ作成
3. ブランドカラーとフォントを設定
4. 「テンプレートとして保存」

### Step 2: 量産（1本あたり2-3分）
1. テンプレートを複製
2. 画像を差し替え（Canva素材から検索）
3. タイトルテキストを変更
4. PNGでダウンロード

### Step 3: Pinterest投稿
1. Pinterest → 「+」→「ピンを作成」
2. 画像アップロード
3. タイトル・説明文を pinterest-pin-content.json からコピペ
4. ボードを選択
5. リンク先URLを設定
6. 公開

### 目標ペース
- 1日5-10本 × 1週間 = 35-70本
- 最初の30本を1週間で完了が目標
