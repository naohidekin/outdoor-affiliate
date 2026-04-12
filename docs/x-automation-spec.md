# X投稿自動化 実装仕様書

最終更新: 2026-04-12

## 1. 目的と背景

@camp_gear_lab の X 投稿を「生成 → 承認 → 投稿 → 結果取得 → 学習」の一連サイクルで
**完全自動化**する。現在は単発スクリプトの組み合わせにとどまっているが、
本仕様では各スクリプトを「判断と学習を持つエージェント」へ再設計する。

### 1.1 現状の問題点

| 問題 | 現在の状況 | 目指す状態 |
|------|-----------|------------|
| フィードバックなし | 投稿後の反応が次回生成に反映されない | Analyst が結果を学習し Writer に渡す |
| パターン固定化 | 同じ文体・構成が繰り返される | 15+ パターンローテーション＋類似チェック |
| 品質管理なし | NGチェックのみ。クオリティ基準がない | 10基準×10点の自己採点（閾値7.0） |
| 人手依存 | 週次バッチを手動実行 | Orchestrator が曜日・時刻で自動起動 |
| X API未連携 | IFTTT経由でBlackBox | X API v2 取得後にFetcherで直接取得 |

### 1.2 X API v2 について

**現時点では X API v2 未契約のため、Fetcher Agent のエンゲージメント取得機能はフェーズ3以降で実装する。**
フェーズ1・2では Google Analytics（GA4）と Google Sheets の情報のみで動作させる。

---

## 2. 現行スクリプト → エージェントマッピング

```
現行ファイル                      → 対応エージェント
─────────────────────────────────────────────────────
scripts/generate-x-posts.js      → Writer Agent（コア）
scripts/queue-to-sheets.js       → Poster Agent（コア）
scripts/sync-posted-status.js    → Fetcher Agent（フェーズ1は Sheets ベース）
scripts/popular-repost.js        → Researcher Agent（GA4起点の素材）
scripts/backup-sheets.js         → Supervisor Agent（バックアップ含む監視）
src/lib/x-post-prompts.mjs       → Writer Agent 内部で参照
src/lib/x-content-checks.mjs     → Writer Agent + Supervisor Agent
src/lib/x-hashtags.mjs           → Writer Agent 内部で参照
```

---

## 3. ターゲットアーキテクチャ（6エージェント + Orchestrator）

```
┌─────────────────────────────────────────────────────────┐
│                    Orchestrator                         │
│  週次パイプライン / 日次パイプライン / 緊急停止制御       │
└────┬──────┬──────┬──────┬──────┬──────────────────────┘
     │      │      │      │      │
     ▼      ▼      ▼      ▼      ▼
┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐ ┌──────────┐
│Resear│ │Analys│ │Writer│ │Poster│ │Fetch │ │Superviso │
│-cher │ │-t    │ │      │ │      │ │-er   │ │-r        │
└──────┘ └──────┘ └──────┘ └──────┘ └──────┘ └──────────┘
```

### 3.1 エージェント役割一覧

| エージェント | 役割 | 主な入力 | 主な出力 |
|-------------|------|---------|---------|
| Researcher | ネタ収集・素材整理 | seeds.json, GA4, 季節カレンダー | 選定済みシード + 文脈情報 |
| Analyst | パフォーマンス分析・フィードバック生成 | GA4, Sheets投稿履歴, エンゲージ(※) | analyst-feedback.json |
| Writer | 投稿テキスト生成・自己採点 | Researcher出力 + Analyst FB | 採点済み投稿草稿 |
| Poster | 承認管理・Sheets投入 | Writer出力 | Sheets「下書き管理」→「X投稿管理」 |
| Fetcher | 投稿後データ取得・status同期 | Sheets, X API(※フェーズ3) | post-history.json 更新 |
| Supervisor | 全体監視・KILLスイッチ・異常検知 | 全エージェントのログ | アラート / 強制停止 |

※ X API v2 取得後に有効化

---

## 4. Orchestrator パイプライン

### 4.1 週次パイプライン（月曜 09:00 実行）

```
1. Supervisor: KILL SWITCH チェック → data/kill-switch.json を確認
2. Supervisor: バックアップ → scripts/backup-sheets.js 実行
3. Researcher: シード選定 → 今週の生成プランを作成（11〜13件）
4. Analyst: フィードバック生成 → 過去4週の成績から学習ヒントを更新
5. Writer: 全タイプ生成 → 自己採点付き下書きを「下書き管理」シートへ
6. Supervisor: 品質チェック → 採点 < 7.0 の投稿を draft 強制
7. Poster: まとめ承認対象を管理者通知（月曜朝レビュー促進）
```

### 4.2 日次パイプライン（毎日 07:00 実行）

```
1. Supervisor: KILL SWITCH チェック
2. Poster: 本日投稿分を「X投稿管理」へ移動（queue-to-sheets.js 相当）
3. Fetcher: 前日投稿の status 同期（sync-posted-status.js 相当）
4. Fetcher: X API v2 エンゲージ取得（フェーズ3〜）
5. Analyst: 直近データを analyst-feedback.json に追記
```

### 4.3 パイプライン設定ファイル

```
scripts/orchestrate.js          # Orchestrator 本体
  --pipeline weekly             # 週次パイプライン
  --pipeline daily              # 日次パイプライン
  --dry-run                     # 実行確認のみ
```

---

## 5. 実装フェーズ

### フェーズ1（基盤整備）— 現在〜

**目標**: 既存スクリプトをエージェント化し、Orchestrator で統合

実装内容:
- [ ] `scripts/orchestrate.js` 作成（週次 / 日次パイプライン）
- [ ] `data/kill-switch.json` 作成
- [ ] `data/post-history.json` 作成（投稿履歴ローカルキャッシュ）
- [ ] `data/analyst-feedback.json` 作成（Analyst フィードバック格納）
- [ ] `data/first-line-patterns.json` 作成（265+ 書き出しパターン）
- [ ] `data/theme-tree.json` 作成（テーマ階層ツリー）
- [ ] Writer Agent: 自己採点ロジック追加（10基準）
- [ ] Writer Agent: 類似チェック追加（直近100件 vs 新規）
- [ ] Writer Agent: パターンローテーション（15+パターン、直近3つを回避）
- [ ] Analyst Agent: GA4 + Sheets ベースのフィードバック生成
- [ ] Supervisor Agent: 異常検知 + KILL SWITCH 監視

### フェーズ2（品質向上）

**目標**: フィードバックループを本稼働させる

実装内容:
- [ ] Researcher Agent: テーマツリーのギャップ検出（未使用テーマの優先化）
- [ ] Analyst Agent: 投稿タイプ別・軸別の成績分析
- [ ] Writer Agent: 書き出しパターンライブラリから構造学習
- [ ] Supervisor Agent: 週次レポート自動生成
- [ ] 管理画面 `/admin/x-posts` へのエージェント状態表示

### フェーズ3（X API 連携）— X API v2 取得後

**目標**: エンゲージメントデータを直接取得してフィードバックループを強化

実装内容:
- [ ] Fetcher Agent: X API v2 でインプレッション / いいね / RT を取得
- [ ] Analyst Agent: エンゲージ率ベースの高精度フィードバック
- [ ] Writer Agent: エンゲージ率上位パターンの強化学習
- [ ] Fetcher Agent: リプライ自動検出（doc_health_tip の医療相談リプ監視）

---

## 6. 関連ファイル一覧

### 既存（維持・拡張）
```
scripts/generate-x-posts.js     Writer Agent のコア（自己採点・類似チェック追加）
scripts/queue-to-sheets.js      Poster Agent のコア（そのまま利用）
scripts/sync-posted-status.js   Fetcher Agent フェーズ1（そのまま利用）
scripts/popular-repost.js       Researcher Agent の GA4 機能
src/lib/x-post-prompts.mjs      Writer Agent が参照（拡張）
src/lib/x-content-checks.mjs    Writer + Supervisor が参照（拡張）
src/lib/x-hashtags.mjs          Writer Agent が参照
```

### 新規作成（フェーズ1）
```
scripts/orchestrate.js          Orchestrator 本体
scripts/researcher-agent.js     Researcher Agent
scripts/analyst-agent.js        Analyst Agent
scripts/supervisor-agent.js     Supervisor Agent
data/kill-switch.json           緊急停止フラグ
data/post-history.json          投稿履歴ローカルキャッシュ
data/analyst-feedback.json      Analyst フィードバック
data/first-line-patterns.json   書き出しパターンライブラリ（265+件）
data/theme-tree.json            テーマ階層ツリー
```

### 参照仕様書
```
docs/x-automation-spec.md      本ファイル（概要・アーキテクチャ・フェーズ）
docs/x-automation-agents.md    6エージェント詳細仕様
docs/x-automation-data.md      データスキーマ・自己採点・KILLスイッチ
```
