---
name: camp-eyecatch
description: Camp Gear Lab の記事画像（アイキャッチ/本文画像）を扱う小スキル。既存の画像取得スクリプトを参照し、画像プレビューをSlackの記事版承認に載せる。画像生成モデルの選定は行わない。
---

# camp-eyecatch — 画像

## 用途
記事に紐づく画像の取得・選定・重複回避を行い、Slackの記事版承認に画像プレビューとして載せる。画像は camp-writing の本文と対で記事版に紐づける。

> 実装・配備・実通信の確認結果は `../../../docs/editorial-pipeline.md` を正本とする。スキルの存在だけで稼働・承認・公開済みとは判断しない。

## 必要時参照
- `../../../docs/editorial-pipeline.md`（repo相対は `docs/editorial-pipeline.md`）
- `scripts/editorial/catalog.py`, `quality.py`, `render-preview.mjs`, `slack.py`, `publish.mjs`（現検証・プレビュー・配信・公開前後の画像再照合）
- `scripts/fetch-unsplash-eyecatch.mjs`（既存の割当・重複排除方針。新runtimeからの自動呼出しではない）
- 既存資料: `docs/image-guidelines.md`, `data/products.json`, `data/articles.json`

## 入力
- 対象記事の slug, categoryId, productIds
- 商品画像の有無と画質（クリーン判定は既存スクリプトのロジックに従う）

## 手順（既存方針の継承）
1. **クリーンな商品画像が1枚でもある記事は eyecatch を持たせない**。カード/ヒーローとも商品画像が優先表示されるため、Unsplash汎用写真より内容が伝わる。
2. **クリーンな商品画像が無い（または低画質な）記事だけ** Unsplash の eyecatch を持つ。その際は**サイト全体で写真IDが重複しないよう排他**し、未使用写真を確保する。
3. **楽天 thumbnail（`thumbnail.image.rakuten.co.jp`）はバッジ・加工入りのためカード/ヒーローに不適**。クリーン判定から除外する（既存 `isCleanImage` と同じ扱い）。
4. **本文中の商品画像は必須**。eyecatch の有無とは別レイヤーであり、本文の商品セクションには商品画像を入れる。
5. eyecatch を変更した記事は `updatedAt` を更新する（同期の更新比較のため。既存スクリプト参照）。忘れると同期で反映されない。
6. Catalogで商品ID/型番ページ・画像URL・実bytesを照合し、verified・SHA-256・sizeをbundleへ結び付ける。rendererがdesktop/mobileで画像表示とCTAを検証する。Slackは記事の同じexact版に商品画像URLのimage blockを配信する実装。privateスクリーンショットのSlackアップロードとは区別する。
7. 画像変更は旧承認を失効させ、再校正/検証/上位審査/版承認へ戻す。公開前後はpublisherが承認画像のSHA/sizeを再取得照合する。新経路で既存全体同期を実行しない。

## 出力 / 引継ぎ
- 記事ごとの画像URL、重複チェック結果、クリーン判定結果
- 次工程: camp-review を呼び出し、記事版の指紋に画像内容を含めて審査を引き継ぐ。
- 台帳更新: 画像確定を記事版に紐づける（実装済みSQLite台帳。新経路の稼働確認は別）

## 停止条件
- 適切な画像が確保できない（現状維持で保留）
- 既存方針と矛盾する指示（確認/保留。勝手に基準を変えない）
