---
name: camp-eyecatch
description: Camp Gear Lab の記事画像とOG・SNSカードを扱う小スキル。検証済みの商品写真から決定的なカードを作り、記事版の画像証拠として審査に渡す。
---

# camp-eyecatch — 画像

## 用途
記事に紐づく画像の取得・選定・重複回避を行い、Slackの記事版承認に画像プレビューとして載せる。画像は camp-writing の本文と対で記事版に紐づける。

> 実装・配備・実通信の確認結果は `../../../docs/editorial-pipeline.md` を正本とする。スキルの存在だけで稼働・承認・公開済みとは判断しない。

## 必要時参照
- `../../../docs/editorial-pipeline.md`（repo相対は `docs/editorial-pipeline.md`）
- `scripts/editorial/catalog.py`, `quality.py`, `render-preview.mjs`, `slack.py`, `publish.mjs`（現検証・プレビュー・配信・公開前後の画像再照合）
- `scripts/editorial/social_cards.py`, `render-social-card.mjs`, `social-card-storage.mjs`（商品写真から作るOG・SNSカード。renderer・runtimeの配線と稼働状況は実コードと検証記録で確認）
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
8. 記事のOG・SNSカードは本文用 `eyecatch` と分ける。選択済み商品のverified画像から最大2枚を安全に再取得し、SHA/sizeを照合した実写真を決定的なテンプレートへ合成する。存在しない製品写真や未検証の性能・価格表現を描かない。
9. 完成PNGは1200×630、2MB以下で検証し、`article.generationMeta.socialCard` と `bundle.images` の `role: social-card` に同一URL・SHA・size・元画像の証拠を記録する。公開bucket `editorial-social-cards` は別の明示的な `node scripts/editorial/social-card-storage.mjs --setup` 操作で作成し、通常のbuildは作成しない。内容ハッシュのパスへ上書きなしで保存し、公開GETの実バイトを照合する。同一パスの既存画像やPOST結果不明時は再POSTせず公開GETの完全一致だけを成功とする。
10. カードを追加・変更したら記事版の指紋・審査・Slack承認を取り直す。将来のAI背景生成は実プロバイダ・出典・画像審査の実装が揃うまで未対応として扱う。
11. カード見出しは記事タイトルに全角 `｜` がちょうど1つあり両側が非空のときだけ右側を逐語的に使う。それ以外はタイトル全文を使い、商品名は別欄に表示する。rendererの表示文言・レイアウト・元画像crop・エンジン/フォント・ハッシュを版に保存し、ローカル出力パスや一時プロファイルは保存しない。

## 出力 / 引継ぎ
- 記事ごとの画像URL、重複チェック結果、クリーン判定結果
- 次工程: camp-review を呼び出し、記事版の指紋に画像内容を含めて審査を引き継ぐ。
- 台帳更新: 画像確定を記事版に紐づける（実装済みSQLite台帳。新経路の稼働確認は別）

## 停止条件
- 適切な画像が確保できない（現状維持で保留）
- 既存方針と矛盾する指示（確認/保留。勝手に基準を変えない）
