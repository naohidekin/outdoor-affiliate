# 記事自動生成パイプライン設計

**作成日**: 2026-04-13
**ステータス**: 承認済み — 実装待ち

---

## 概要

6エージェント体制でアフィリエイトブログ記事を週3本自動生成・公開するパイプライン。
既存のX投稿パイプラインと並列の独立パイプラインとして構築する。
Supervisorのみ既存を共用し、Kill Switch・エラー通知を一元管理。

### 要件サマリ

| 項目 | 決定事項 |
|------|---------|
| 更新頻度 | 週3本（新規記事のみ） |
| テーマ選定 | 季節性 + GA4データドリブンのハイブリッド |
| 商品データ | エージェントが楽天APIで自動調査・products.jsonに追加 |
| 公開フロー | 品質スコア >= 7.0 → 自動公開 / < 7.0 → 管理画面でレビュー |
| 記事規模 | Phase 1: やや軽め（選び方+3商品+比較表）→ 安定後フルボリュームに拡張 |
| アーキテクチャ | X投稿パイプラインと独立。article-orchestrate.js で統括 |

---

## 1. 6エージェント構成

```
article-orchestrate.js
  ├── article-researcher-agent.js   テーマ選定（季節+GA4）
  ├── article-analyst-agent.js      記事PV・クリック分析
  ├── article-product-agent.js      商品調査・追加（楽天API+Amazon）
  ├── article-writer-agent.js       記事本文生成（Claude API）
  ├── article-publisher-agent.js    品質判定→公開 or draft
  └── supervisor-agent.js           既存を共用（Kill Switch等）
```

### 1-1. Article Researcher Agent

**ファイル**: `scripts/article-researcher-agent.js`
**入力**: `categories.json`, `articles.json`, GA4データ, `data/article-season-map.json`
**出力**: `data/article-weekly-plan.json`

ロジック:
- GA4で検索流入が多いカテゴリを特定
- 季節マッピング（`data/article-season-map.json`）とクロスさせて優先度算出
- 既存記事と重複しない切り口を選定（例: テントに「ファミリー5選」があれば「ソロ向け」を提案）
- 各テーマに想定キーワード・ターゲット読者を付与
- 3記事に `scheduledPublishDate` を割り当て（水/金/日）

### 1-2. Article Product Agent

**ファイル**: `scripts/article-product-agent.js`
**入力**: Researcherの週次プラン
**出力**: `products.json` への商品追加 + テーマ別商品リスト

ロジック:
- 楽天商品検索APIでカテゴリ・キーワード検索 → レビュー評価順で上位10件取得
- 各商品から抽出: 商品名・ブランド・価格・アフィリエイトURL・画像URL・スペック
- スペック構造化: `itemCaption` をClaude APIで構造化（`data/category-specs.json` の項目に準拠）
- 既存products.jsonとの重複チェック（商品名の類似度で判定）
- 価格帯バランスで3商品選定（エントリー / ミドル / ハイエンド）
- Amazon URL: `https://www.amazon.co.jp/s?k={商品名}&tag=nao78-22`（検索リンク）
- 画像URL: ASINがあればAmazon画像、なければ楽天画像を使用

**必要な環境変数**: `RAKUTEN_APP_ID`（楽天APIアプリID）

### 1-3. Article Writer Agent

**ファイル**: `scripts/article-writer-agent.js`
**入力**: 週次プラン + 商品データ + Analystフィードバック + CLAUDE.mdガイドライン
**出力**: `articles.json` への記事追加（status=draft or ready）

プロンプト構成（3層）:
1. **システムプロンプト**: CLAUDE.md記事ガイドライン + writing-style.md + Analystフィードバック
2. **テーマ指示**: タイトル・切り口・ターゲットキーワード・季節コンテキスト
3. **商品データ**: 3商品のスペック・価格・特徴 + 比較軸

生成する記事構成（Phase 1）:
```markdown
# {タイトル}【2026年版】

リード文（結論ファースト、2-3文）

---

## {カテゴリ名}を選ぶ{N}つのポイント

### 1. {選び方ポイント1}
### 2. {選び方ポイント2}

---

## おすすめランキング TOP3

### 1位: {商品名}
- スペック概要
- 良い点・注意点

### 2位: {商品名}
...

### 3位: {商品名}
...

---

## スペック比較表

{{comparison:id1,id2,id3}}

---

## まとめ

結論の再掲 + CTA
```

自己採点基準（10項目 × 10点 → 10点満点に正規化）:

| # | 基準 | 説明 |
|---|------|------|
| 1 | ギア男ボイス | 断言型・淡々・知的。NGワードなし |
| 2 | 構成完成度 | リード→選び方→ランキング→比較表→まとめが揃っている |
| 3 | SEO適合 | タイトル・見出しにターゲットキーワードが自然に含まれる |
| 4 | 商品情報正確性 | スペック・価格がProduct Agent提供データと一致 |
| 5 | 比較の公平性 | 特定商品を過度に持ち上げず各商品の強み弱みを記述 |
| 6 | 読者価値 | 初心者〜中級者が読んで選び方がわかる内容 |
| 7 | CTA適切さ | 押しつけがましくない自然な誘導 |
| 8 | 文字数適正 | 2000〜4000文字（Phase 1目安） |
| 9 | オリジナリティ | 既存記事と切り口が異なる |
| 10 | メタ情報 | excerpt・metaDescription・tagsが適切 |

公開判定:

| スコア | アクション |
|--------|-----------|
| >= 7.0 | status=ready → Publisherが自動公開 |
| 5.0〜6.9 | 1回リトライ → まだ低ければ status=draft（レビュー待ち） |
| < 5.0 | status=draft + 管理画面に警告表示 |

### 1-4. Article Analyst Agent

**ファイル**: `scripts/article-analyst-agent.js`
**入力**: GA4データ, `articles.json`, `data/affiliate-clicks.json`
**出力**: `data/article-analyst-feedback.json`

ロジック:
- 既存記事のPV・セッション・アフィリエイトクリック率を分析
- 高パフォーマンス記事の構成パターンを抽出（Writerへのフィードバック）
- カテゴリ別の検索流入トレンドをResearcherにフィード

### 1-5. Article Publisher Agent

**ファイル**: `scripts/article-publisher-agent.js`
**入力**: Writer出力（status=ready の記事）
**出力**: `articles.json` の status 更新

ロジック:
- スコア >= 7.0 の記事を自動公開（status → published, publishedAt 設定）
- スコア < 7.0 は status=draft のまま → 管理画面でレビュー待ち
- 公開後に Google Indexing API でインデックス登録リクエスト
- X投稿パイプラインに article_promo 投稿を自動生成依頼
- `scheduledPublishDate` に基づいて公開タイミングを制御（水/金/日）

### 1-6. Supervisor Agent（既存共用）

**ファイル**: `scripts/supervisor-agent.js`（既存を拡張）

追加機能:
- Kill Switch に `articleEnabled` フィールド追加（記事パイプラインのみ停止可能）
- バックアップ対象に `articles.json`, `products.json` を追加
- 品質チェック（スコア異常の検知）
- 週次レポートに記事パイプラインの結果を追加

---

## 2. パイプラインフロー

### 2-1. 週次パイプライン（水曜 09:00）

```
article-orchestrate.js --pipeline weekly

1. Supervisor:    Kill Switch チェック + バックアップ
2. Analyst:       既存記事のPV・クリック分析 → フィードバック生成
3. Researcher:    今週の3テーマ選定（季節+GA4） → article-weekly-plan.json
4. Product Agent: 各テーマの商品調査・products.json追加 → テーマ別商品リスト
5. Writer:        3記事生成（Claude API） → articles.json に draft/ready で追加
6. Publisher:     スコア >= 7.0 → 自動公開 / < 7.0 → draft（レビュー待ち）
7. Supervisor:    品質チェック + 週次レポート更新
```

### 2-2. 公開スケジュール

週3本を日をずらして公開:

```
水曜 10:00  1本目公開（パイプライン実行直後）
金曜 10:00  2本目公開
日曜 10:00  3本目公開
```

Publisher が `scheduledPublishDate` を各記事に付与し、日次パイプラインで該当日に公開。

### 2-3. 日次パイプライン（毎日 10:00）

```
article-orchestrate.js --pipeline daily

1. Supervisor:  Kill Switch チェック
2. Publisher:   本日公開予定の記事を published に変更 + Indexing API
3. Publisher:   新記事の article_promo 投稿をX投稿パイプラインに連携
4. Analyst:     直近7日の記事PVを article-analyst-feedback.json に追記
```

### 2-4. launchd スケジュール

| ジョブ | plistファイル | スケジュール |
|--------|-------------|-------------|
| article-weekly | `com.outdoor-affiliate.article-weekly.plist` | 水曜 09:00 |
| article-daily | `com.outdoor-affiliate.article-daily.plist` | 毎日 10:00 |

---

## 3. データ構造

### 3-1. article-weekly-plan.json（Researcher出力）

```json
{
  "week": "2026-W16",
  "generatedAt": "2026-04-15T09:00:00Z",
  "articles": [
    {
      "themeId": "theme-016-01",
      "categoryId": "tarp",
      "title": "タープ選び方ガイド【初心者向け】",
      "slug": "tarp-beginner-guide",
      "angle": "初心者が最初の1枚を選ぶための比較",
      "targetKeywords": ["タープ おすすめ 初心者", "タープ 選び方"],
      "seasonRelevance": "春キャンプ本番。日差し対策需要",
      "scheduledPublishDate": "2026-04-15",
      "productCount": 3,
      "priority": "high",
      "reason": "GA4で『タープ』関連の検索流入が前月比+40%"
    }
  ]
}
```

### 3-2. article-analyst-feedback.json（Analyst出力）

```json
{
  "updatedAt": "2026-04-15T09:00:00Z",
  "topArticles": [
    { "slug": "family-tent-ranking", "pv28d": 450, "clicks28d": 12, "ctr": 2.7 }
  ],
  "categoryTrends": [
    { "categoryId": "tarp", "pv7d": 85, "pv28d": 280, "trend": "up" }
  ],
  "effectivePatterns": [
    "結論ファーストのリード文がPV滞在時間を伸ばしている",
    "比較表の直後にCTAを置いた記事のクリック率が高い"
  ],
  "suggestions": [
    "cooler カテゴリは夏前に需要急増予測。6月に向けて準備推奨"
  ]
}
```

### 3-3. articles.json 追加フィールド

既存スキーマに以下を追加:

```json
{
  "autoGenerated": true,
  "qualityScore": 7.8,
  "scheduledPublishDate": "2026-04-15",
  "generationMeta": {
    "themeId": "theme-016-01",
    "model": "claude-sonnet-4-6",
    "retryCount": 0,
    "generatedAt": "2026-04-15T09:05:00Z"
  }
}
```

### 3-4. products.json 自動追加フィールド

既存スキーマに以下を追加:

```json
{
  "autoAdded": true,
  "addedBy": "article-product-agent",
  "addedAt": "2026-04-15T09:03:00Z",
  "sourceApi": "rakuten"
}
```

### 3-5. article-season-map.json（季節マッピング）

```json
{
  "1":  ["sleeping-bag", "wear"],
  "2":  ["sleeping-bag", "wear"],
  "3":  ["tent", "tarp", "backpack"],
  "4":  ["tent", "tarp", "chair", "table"],
  "5":  ["tent", "tarp", "chair", "table", "burner"],
  "6":  ["wear", "shoes", "backpack"],
  "7":  ["cooler", "light", "chair"],
  "8":  ["cooler", "light", "tarp"],
  "9":  ["tent", "firepit", "sleeping-bag"],
  "10": ["firepit", "sleeping-bag", "light"],
  "11": ["firepit", "sleeping-bag", "wear"],
  "12": ["sleeping-bag", "wear", "light"]
}
```

### 3-6. category-specs.json（カテゴリ別スペック項目）

```json
{
  "tent":         ["収容人数", "サイズ", "重量", "耐水圧", "構造", "素材"],
  "tarp":         ["サイズ", "重量", "耐水圧", "素材", "付属品"],
  "sleeping-bag": ["使用温度", "重量", "収納サイズ", "素材", "形状"],
  "light":        ["明るさ", "点灯時間", "電源", "防水", "重量"],
  "burner":       ["出力", "燃料", "重量", "サイズ", "点火方式"],
  "backpack":     ["容量", "重量", "背面長", "素材", "レインカバー"],
  "wear":         ["素材", "耐水圧", "透湿性", "重量", "サイズ展開"],
  "shoes":        ["重量", "ソール", "防水", "サイズ展開", "用途"],
  "firepit":      ["サイズ", "収納サイズ", "重量", "素材", "耐荷重"],
  "chair":        ["耐荷重", "重量", "座面高", "収納サイズ", "素材"],
  "table":        ["サイズ", "収納サイズ", "重量", "耐荷重", "素材"],
  "cooler":       ["容量", "保冷力", "重量", "サイズ", "素材"]
}
```

---

## 4. Kill Switch 拡張

既存の `data/kill-switch.json` に `articleEnabled` フィールドを追加:

```json
{
  "enabled": false,
  "articleEnabled": false,
  "reason": ""
}
```

- `enabled: true` → X投稿 + 記事パイプライン両方停止
- `articleEnabled: true` → 記事パイプラインのみ停止

---

## 5. 管理画面の変更

### 5-1. /admin/articles の拡張

- フィルタ追加: 「自動生成」「手動作成」（`autoGenerated` フラグ）
- フィルタ追加: status（draft / ready / published）
- 品質スコア表示（スコアバーで視覚化）
- 記事詳細: 10項目内訳表示 + 「公開する」「リジェクト」ボタン + プレビュー
- 生成メタ情報表示（テーマID・モデル・生成日時・リトライ回数）

---

## 6. 公開後の連携

1. **Google Indexing API** でインデックス登録リクエスト（既存の仕組みを流用）
2. **X投稿連携**: `article_promo` タイプの投稿を自動生成 → 「下書き管理」シートに追加
3. **sitemap.xml**: Next.js が動的生成するので追加作業なし

---

## 7. 新規ファイル一覧

| ファイル | 種別 | 用途 |
|---------|------|------|
| `scripts/article-orchestrate.js` | 新規 | 記事パイプラインオーケストレーター |
| `scripts/article-researcher-agent.js` | 新規 | テーマ選定（季節+GA4） |
| `scripts/article-product-agent.js` | 新規 | 商品調査・追加（楽天API） |
| `scripts/article-writer-agent.js` | 新規 | 記事本文生成（Claude API） |
| `scripts/article-analyst-agent.js` | 新規 | 記事PV・クリック分析 |
| `scripts/article-publisher-agent.js` | 新規 | 公開判定・インデックス登録 |
| `data/article-weekly-plan.json` | 新規 | Researcher出力 |
| `data/article-analyst-feedback.json` | 新規 | Analyst出力 |
| `data/article-season-map.json` | 新規 | カテゴリ×月の季節マッピング |
| `data/category-specs.json` | 新規 | カテゴリ別スペック項目定義 |
| `launchd/com.outdoor-affiliate.article-weekly.plist` | 新規 | 週次スケジュール（水曜09:00） |
| `launchd/com.outdoor-affiliate.article-daily.plist` | 新規 | 日次スケジュール（毎日10:00） |

### 修正ファイル

| ファイル | 変更内容 |
|---------|---------|
| `scripts/supervisor-agent.js` | articleEnabled Kill Switch + 記事バックアップ + 週次レポート拡張 |
| `data/kill-switch.json` | `articleEnabled` フィールド追加 |
| `src/app/admin/articles/page.tsx` | 自動生成フィルタ・スコア表示・公開/リジェクトボタン |

### 必要な環境変数（追加）

| 変数 | 用途 |
|------|------|
| `RAKUTEN_APP_ID` | 楽天商品検索API |

---

## 8. 実装フェーズ

### Phase 1（本スペックのスコープ）
- 6エージェント + オーケストレーター実装
- 週3本の記事自動生成（選び方 + 3商品 + 比較表）
- 品質スコアベースの自動/手動公開
- 管理画面拡張
- launchdスケジュール登録

### Phase 2（Phase 1安定後）
- 記事構成をフルボリュームに拡張（口コミ + FAQ追加）
- 既存記事のリライト機能
- Amazon PA-API連携（個別ASIN取得・正確な価格データ）
- A/Bテスト（タイトル・リード文のバリエーション）
