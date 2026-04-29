# 楽天ROOM リサーチパイプライン + サイト連携 設計

## Context

楽天ROOM の165商品を全て投稿完了。次の課題は:
1. 新商品の継続的な発掘（在庫が0になった）
2. サイト（camp-gear-lab.com）からROOMへの導線構築
3. リサーチ対象をキャンプギアに限定せず、4軸全てに拡張

## Part A: SNS起点の商品自動発掘

### A-1. viral-scout に商品抽出機能を追加

**変更ファイル**: `src/lib/viral-scout-agent.mjs`

Phase 2 (Analyze) の Claude プロンプトに商品抽出指示を追加:
- バイラル投稿のテキストから「商品名・ブランド名・カテゴリ・推定価格帯」を抽出
- 既存の analysis オブジェクトに `products` フィールドを追加
- 出力例: `{ "products": [{ "name": "NANGA オーロラ600DX", "brand": "NANGA", "category": "シュラフ", "axis": "camp" }] }`

Phase 2 完了後に新ステップ「Product Lookup」を追加:
- 抽出された商品名で楽天商品検索 API を叩く
- ヒットしたら products.json に自動追加（既存の重複チェック利用）
- affiliate_url を自動生成
- Supabase同期は次回の sync-to-supabase.js 実行時に反映
- 翌朝の rakuten-room-supabase.js が ROOM に自動投稿

### A-2. YouTube researcher に商品抽出を追加

**変更ファイル**: `scripts/youtube-researcher.js`

YouTube 動画の字幕テキストから商品名を Claude で抽出:
- 既存の「トピック抽出」に「商品名抽出」を並行実行
- 同じ Product Lookup パイプを通す

### A-3. rakuten-ranking.js を4軸に拡張

**変更ファイル**: `scripts/research-sources/rakuten-ranking.js`

現在の SEASONAL_CATEGORIES（camp のみ）を4軸に拡張:

```
camp: テント、ランタン、焚き火台、チェア、タープ...（既存）
doctor: 血圧計、体温計、パルスオキシメーター、マッサージガン、健康家電...
ai: モニター、キーボード、USBハブ、ケーブル、スタンディングデスク...
parenting: キッズテント、子供用寝袋、知育玩具、チャイルドシート...
```

季節×軸のマトリクスでカテゴリを動的生成。

### A-4. 共通: Product Lookup モジュール

**新規ファイル**: `src/lib/product-lookup.mjs`

全リサーチャーが共通で使う商品登録パイプ:
1. 商品名で楽天商品検索 API を叩く
2. products.json との重複チェック（正規化名前マッチ）
3. ヒットしたら products.json に追加
4. アフィリエイト URL を自動生成
5. 追加結果を返す（追加済み/重複/検索結果なし）

## Part B: サイトへのROOM導線

### B-1. フッターにROOMバナー追加

**変更ファイル**: レイアウトコンポーネント（Footer）

- 「僕の楽天ROOM」リンクをフッターに常設
- account-config.json の rakutenRoomUrl を参照
- シンプルなテキストリンク + アイコン

### B-2. 記事内の楽天リンクをROOM経由に（将来検討）

現状の affiliateUrl は直接の楽天アフィリエイトリンク。
ROOM経由にするには各商品のROOM個別URLが必要だが、
ROOMのURLは商品追加時に自動取得できない（ROOM側で生成される）。

**現実的な対応**:
- フッターの ROOM ページリンクで十分（ユーザーがROOMページで回遊して購入）
- 個別商品のROOM URLは Playwright で取得可能だが工数大。Phase 2 として保留

## 実装順序

| 順 | タスク | 効果 |
|----|--------|------|
| 1 | Product Lookup 共通モジュール | 全リサーチャーの基盤 |
| 2 | viral-scout に商品抽出追加 | 日次で4軸のバズ商品を自動発掘 |
| 3 | rakuten-ranking.js 4軸拡張 | カテゴリの幅を一気に拡大 |
| 4 | サイトフッターにROOMリンク | サイト→ROOM導線 |
| 5 | YouTube researcher 商品抽出 | 動画からの商品発掘 |
| 6 | launchd で rakuten-ranking.js 週次自動化 | 放置運用の完成 |

## 検証方法

1. viral-scout --dry-run で商品抽出結果を確認
2. 抽出された商品が products.json に追加されることを確認
3. 翌朝の ROOM 自動投稿で新商品が投稿されることを確認
4. X 投稿生成で rakuten_room_pick に新商品が含まれることを確認
5. サイトのフッターに ROOM リンクが表示されることを確認
