---
name: camp-topics
description: Camp Gear Lab の週次ネタ選定を担当する小スキル。季節・既存記事重複・観測データから週3本のテーマ候補を作り、台帳へ起案として登録する。執筆・画像・審査は行わない。
---

# camp-topics — ネタ選定

## 用途
週3本の企画枠に対し、テーマ候補と公開予定日を起案する。選定は本スキル、執筆は camp-writing へ引き継ぐ。

> Slack統合のうち**未配備なのは記事版承認→公開接続・画像プレビュー・複数候補・SNS別承認・内部台帳/cap の新設計**。**既存Slack本文配信と本人確認結果の受付は 2026-10-30 から live**（ただし公開許可は false）。本人確認結果の受付を記事版公開承認と同一視しない。本書は設計と参照先を示すだけで、実行主体ではない。

## 必要時参照
- `../../../docs/editorial-pipeline.md`（全体像・cap・台帳。repo相対は `docs/editorial-pipeline.md`）
- `scripts/article-researcher-agent.js`（既存の選定ロジック・季節マップ・重複チェック）
- 既存資料: `data/article-season-map.json`, `data/categories.json`

## 入力
- 対象週（JST。週境界はJST固定）
- 季節カテゴリ、Analystフィードバック、任意の観測データ
- 既存記事の一覧（重複回避用）

## 手順
1. 対象週の残枠を確認する（週3件cap・承認待ち上限3。詳細は `../../../docs/editorial-pipeline.md`）。
2. 季節カテゴリを優先しつつ、既存記事と切り口が重複しない候補を出す。
3. 既存 `scripts/article-researcher-agent.js` の出力形式（themeId / slug / title / categoryId / targetKeywords / scheduledPublishDate 等）に合わせて起案する。
4. 候補を台帳に「起案」段階で登録する（台帳の正本は1つ。詳細はパイプライン文書）。
5. 起案をSlackに示す。**企画の本人承認を追加の必須関門にしない**（今回の設計案。追加許可を無用に増やさない方針にすぎない）。本人確定を要する承認は最終記事版承認（設計案。詳細はパイプライン文書）。既存liveとは主張しない。

## 出力 / 引継ぎ
- 週次プラン（themeId, slug, title, categoryId, targetKeywords, scheduledPublishDate）
- 次工程: camp-writing を呼び出し、執筆（本文制作）を引き継ぐ。
- 台帳更新: 起案

## 台帳境界（重要）
- 新設計の台帳（内部 JSON または SQLite、正本一つ）は**未配備**。本スキルはそれを前提に**設計上の登録先**を示すだけで、稼働中の正本を断定しない。
- 既存 `data/articles.json` は**公開データ投影 / 互換境界**として区別する。新設計の内部台帳と二重正本を作らない。現行パイプラインの実体は `data/articles.json` と Supabase 同期の既存経路であり、新台帳の導入でこれを置き換える設計は未配備。

## 停止条件
- kill switch が有効
- 週3件cap または 承認待ち上限3 に到達（新規制作停止。保留/失敗で無限補充しない。再試行は同一記事の枠）
- 全候補が既存記事と重複
