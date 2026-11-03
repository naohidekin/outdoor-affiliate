---
name: camp-topics
description: Camp Gear Lab の週次ネタ選定を担当する小スキル。季節・既存記事重複・観測データから週3本のテーマ候補を作り、台帳へ起案として登録する。執筆・画像・審査は行わない。
---

# camp-topics — ネタ選定

## 用途
週3本の企画枠に対し、テーマ候補と選定根拠を起案する。選定は本スキル、執筆は camp-writing へ引き継ぐ。

> 実装・配備・実通信の確認結果は `../../../docs/editorial-pipeline.md` を正本とする。スキルの存在だけで稼働・承認・公開済みとは判断しない。

## 必要時参照
- `../../../docs/editorial-pipeline.md`（全体像・cap・台帳。repo相対は `docs/editorial-pipeline.md`）
- `scripts/editorial/runtime.py`, `models.py`, `catalog.py`, `ledger.py`（現runnerの選定・根拠・枠）
- `scripts/article-researcher-agent.js`（旧フローの季節マップ・出力形式の参照）
- 既存資料: `data/article-season-map.json`, `data/categories.json`

## 入力
- 対象週（JST。週境界はJST固定）
- 季節カテゴリ、Analystフィードバック、任意の観測データ
- 既存記事の一覧（重複回避用）

## 手順
1. 対象週の残枠を確認する（週3件cap・承認待ち上限3。詳細は `../../../docs/editorial-pipeline.md`）。
2. 季節カテゴリを優先しつつ、既存記事と切り口が重複しない候補を出す。
3. 現modelsの形式 `slug / title / categoryId / productIds / query / selectionReason` で重複しない3候補を作る。現runtimeが渡す商品・既存記事・queuedテーマ・季節・モールクリックだけを根拠とし、未供給の検索量/GSC値を補わない。旧weekly planのscheduledPublishDateを現runnerの公開予約と同一視しない。
4. 候補を台帳に「起案」段階で登録する（台帳の正本は1つ。詳細はパイプライン文書）。
5. camp-writingへ引き継ぎ、制作・校正・上位審査後の本文をSlackへ提示する。現runtimeは候補だけを自動配信する段階を持たない。**企画の本人承認を追加の必須関門にしない**。本人確定を要するのは最終exact版の公開承認。

## 出力 / 引継ぎ
- 週3枠の候補（slug, title, categoryId, productIds, query, selectionReason）
- 次工程: camp-writing を呼び出し、執筆（本文制作）を引き継ぐ。
- 台帳更新: 起案

## 台帳境界（重要）
- `stateRoot/ledger.sqlite3` が実装済みの内部正本。Git外private領域で管理し、公開データやJSONを別正本にしない。
- 単一macpro、300秒tick。JST水曜09時以降に1記事ずつ制作し、JST月曜区切りの候補3枠・未公開上限3を適用する。公開日の水/金/日固定や週3本公開を保証しない。
- 保留/失敗も未公開枠を使う。週跨ぎcandidateは同一jobで再開し、errorを自動再試行するとは扱わない。
- 現自動候補抽出は型番・対応メーカー・画像・楽天/Amazon URLが揃う既存商品に限定。品質検証のNA対応とは範囲が異なる。

## 停止条件
- generationEnabledがfalse、または配備/接続検証が完了していない
- 週3件cap または 承認待ち上限3 に到達（新規制作停止。保留/失敗で無限補充しない。再試行は同一記事の枠）
- 全候補が既存記事と重複
