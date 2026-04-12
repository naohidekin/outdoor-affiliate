# X投稿自動化 エージェント詳細仕様

最終更新: 2026-04-12

関連: docs/x-automation-spec.md（概要・フェーズ）/ docs/x-automation-data.md（データスキーマ）

---

## 1. Researcher Agent

**ファイル**: `scripts/researcher-agent.js`  
**役割**: ネタシード選定・記事候補整理・季節コンテキスト生成

### 1.1 処理フロー

```
1. data/kill-switch.json を確認（enabled=true なら即終了）
2. data/x-content-seeds.json を読み込み
3. 今月の月番号でシードをフィルタ（season に月番号が含まれるもの）
4. used_count が少ない順 → last_used が古い順でソート
5. data/theme-tree.json を参照し、未使用・低使用テーマを優先
6. 各タイプに1件ずつシードを割り当て（週次プランを構成）
7. data/articles.json から publishedかつ recentSlugs に含まれない記事を選定
8. 結果を Orchestrator に返す（週次生成プランオブジェクト）
```

### 1.2 週次生成プランの構造

```json
{
  "week": "2026-W16",
  "month": 4,
  "seasonContext": "春キャンプ本番。GWキャンプの計画時期。",
  "plan": [
    { "type": "article_promo",     "count": 2, "axis": "camp",      "seedId": "seed-042" },
    { "type": "outdoor_tip",       "count": 1, "axis": "camp",      "seedId": "seed-017" },
    { "type": "poll_question",     "count": 2, "axis": "rotate",    "seedId": "seed-103" },
    { "type": "failure_story",     "count": 1, "axis": "camp",      "seedId": "seed-055" },
    { "type": "gear_thread",       "count": 1, "axis": "camp",      "seedId": "seed-089" },
    { "type": "ai_dev_log",        "count": 2, "axis": "ai",        "seedId": "seed-201" },
    { "type": "parenting_outdoor", "count": 1, "axis": "parenting", "seedId": "seed-156" },
    { "type": "doc_health_tip",    "count": 1, "axis": "doctor",    "seedId": "seed-178" },
    { "type": "seasonal_hook",     "count": 1, "axis": "all",       "seedId": "seed-033" }
  ],
  "selectedArticles": ["burner-comparison", "tent-family-2024"]
}
```

### 1.3 テーマツリー参照ロジック

- `data/theme-tree.json` の各リーフノードに `used_count` と `last_used` を持つ
- 同じ親テーマ内で直近3回連続使用されたテーマは除外
- 4軸（camp/ai/parenting/doctor）の配分が `docs/x-operations.md` の比率に近づくよう調整

---

## 2. Analyst Agent

**ファイル**: `scripts/analyst-agent.js`  
**役割**: パフォーマンス分析・Writer へのフィードバック生成

### 2.1 データソース（フェーズ別）

| フェーズ | 利用データ |
|---------|-----------|
| フェーズ1 | GA4（X経由PV）+ Sheets投稿履歴 |
| フェーズ2 | フェーズ1 + 投稿タイプ・軸別クロス分析 |
| フェーズ3 | フェーズ2 + X API v2（インプレッション・いいね・RT） |

### 2.2 処理フロー（フェーズ1）

```
1. GA4 から utm_source=x の過去28日セッション数・PV数を取得
2. Sheets「下書き管理」から過去28日の投稿履歴を取得
3. 記事 slug と GA4 データを突合 → 記事別 X 経由PV を算出
4. タイプ別・軸別の「Sheets書き込み数 / approved率 / NGチェック失敗率」を集計
5. 高パフォーマンス投稿の text を抽出し、共通パターンを識別
6. data/analyst-feedback.json を更新
```

### 2.3 フィードバック構造

`data/analyst-feedback.json` に出力する内容（詳細は docs/x-automation-data.md 参照）:

- `topPerformingTypes`: 直近4週でNG通過率・approved率が高いタイプ
- `lowPerformingTypes`: NG失敗率 > 20% のタイプ
- `effectivePatterns`: 高PV記事に使われた投稿パターン
- `avoidPatterns`: NGに引っかかった頻出表現
- `seasonalInsight`: 現在月の傾向メモ（Analyst が自由記述）

---

## 3. Writer Agent

**ファイル**: `scripts/generate-x-posts.js`（拡張）  
**役割**: 投稿テキスト生成・自己採点・類似チェック・パターンローテーション

### 3.1 既存機能（維持）

- Claude API（claude-sonnet-4-6）による10タイプ生成
- ネタシード参照（used_count 管理）
- NGチェック（x-content-checks.mjs）
- 承認区分判定（auto / batch / manual）
- Google Sheets「下書き管理」書き込み

### 3.2 追加機能：自己採点（フェーズ1）

生成した各投稿を Claude API で再評価する二段階生成。

**採点基準（10項目 × 各10点 = 100点満点）**:

| # | 基準 | 説明 |
|---|------|------|
| 1 | Lake & Sky トーン | 淡々・知的・非煽り。NG表現なし |
| 2 | 体験ベース | 「個人的には」「使ってみたら」等の一人称体験感 |
| 3 | 具体性 | 数値・製品名・状況が含まれる |
| 4 | 文字数適正 | 200〜280文字（URLなし）/ 240〜280文字（URLあり） |
| 5 | ハッシュタグ適正 | 2〜3個、本文と整合 |
| 6 | タイプ適合 | 当該タイプの目的（engagement / 誘導 / 共感）に合致 |
| 7 | 軸適合 | 発信4軸の配分・トーンと合っている |
| 8 | オリジナリティ | 直近100件と類似していない（類似チェックで補完） |
| 9 | フック強度 | 1行目で読者を引きつける書き出し |
| 10 | アクション明確 | 読んだ後の行動（リプ/RT/クリック）が自然に促される |

**採点フロー**:
```
1. 生成テキストを採点プロンプトで Claude API に送信
2. 10項目の点数（0〜10）をJSON形式で取得
3. 合計点 / 10 = 最終スコア（0.0〜10.0）
4. スコア < 7.0 → 最大2回リトライ（同シード、異なるプロンプト表現）
5. 2回リトライ後もスコア < 7.0 → status="discarded" で記録・スキップ
6. スコアを Sheets 列 O（selfScore）に記録
```

### 3.3 追加機能：類似チェック（フェーズ1）

直近100件の投稿との重複・マンネリを防ぐ。

```
1. data/post-history.json から直近100件の text を読み込む
2. 新規生成テキストと TF-IDF コサイン類似度を計算
3. 最大類似度 > 0.6 → 同シードで再生成（1回まで）
4. 再生成後も > 0.6 → status="draft" + validationErrors に「類似投稿あり」を記録
```

### 3.4 追加機能：パターンローテーション（フェーズ1）

`data/first-line-patterns.json` の265+件の書き出しパターンから構造を学習し、
同じパターンが連続しないようプロンプトに指示を追加する。

```
1. data/post-history.json から直近3件の「書き出しパターン分類」を取得
2. 直近3件と同じパターン分類をプロンプトの NG パターンとして明示
3. first-line-patterns.json から別カテゴリのパターン例を2〜3件プロンプトに追加
```

**パターン分類（15カテゴリ）**:

| カテゴリ | 例 |
|---------|---|
| 結論先出し | 「○○を3年使った結論。」 |
| 失敗オープン | 「○○を間違えて△△した話。」 |
| 数値フック | 「夜は−5℃。昼は22℃。」 |
| 対比 | 「○○と△△、どっちがいいか聞かれたら」 |
| 疑問提起 | 「テントの△△、気にしたことある？」 |
| 逆説 | 「○○は高い。でもこれ以外に戻る気がしない。」 |
| 体験共有 | 「先週、○○したら△△だった。」 |
| 季節起点 | 「4月のキャンプ場、夜は5℃を下回る。」 |
| 製品比較 | 「○○か△△か、と聞かれたら」 |
| 子育てネタ | 「子供に△△って聞いたら○○と返ってきた。」 |
| AI/開発 | 「Claude Codeに○○をやらせてみた。」 |
| 医師視点 | 「本職柄、○○にはちょっとうるさい。」 |
| ハック/工夫 | 「○○のときは△△にすると解決する。」 |
| アンケート | 「○○するとき、どっち派？」 |
| まとめ | 「○○について3点だけ。」 |

---

## 4. Poster Agent

**ファイル**: `scripts/queue-to-sheets.js`（現行維持）  
**役割**: 承認済み投稿を「X投稿管理」シートに移し、IFTTT 経由で投稿

### 4.1 現行動作（維持）

- 「下書き管理」から `status=approved` かつ `scheduledDate <= 今日` の行を抽出
- 「X投稿管理」シートに追記（IFTTT が監視・投稿）
- 「下書き管理」の status を `queued` に更新
- `--max=N` で1日の投稿上限制御（IFTTT 上限: 3件/日）

### 4.2 gear_thread 展開（フェーズ1追加）

```
1. text が "[THREAD]" で始まる行を検出
2. JSON パースして tweets 配列を取得
3. 「X投稿管理」に複数行として展開
4. 各ツイートの scheduled_at に1分間隔を付与
```

---

## 5. Fetcher Agent

**ファイル**: `scripts/sync-posted-status.js`（フェーズ1）/ `scripts/fetcher-agent.js`（フェーズ3）  
**役割**: 投稿後データ取得・status 同期・post-history.json 更新

### 5.1 フェーズ1: Sheets ベース同期（現行維持＋拡張）

```
1. 「X投稿管理」シートで status が ready/posted の行を取得
2. 「下書き管理」とテキスト突合 → queued → posted に更新
3. 投稿日時を postedAt 列に記録
4. data/post-history.json に投稿済みレコードを追記
```

### 5.2 フェーズ3: X API v2 連携（X API 取得後に実装）

```
必要スコープ: tweet.read, users.read, offline.access
取得データ:
  - impression_count
  - like_count
  - retweet_count
  - reply_count
  - url_link_clicks（article_promo など）

取得タイミング: 投稿から24時間後（エンゲージが安定する時間）
保存先: data/post-history.json の engagements フィールド
```

### 5.3 doc_health_tip 監視（フェーズ3）

- リプライを取得し、医療相談・診断を求める内容が含まれる場合は Supervisor に通知
- キーワード: 「教えてください」「診断」「どうすれば」「うちの子」+ 症状系ワード

---

## 6. Supervisor Agent

**ファイル**: `scripts/supervisor-agent.js`  
**役割**: 全体監視・KILL SWITCH 制御・異常検知・週次レポート

### 6.1 KILL SWITCH チェック

すべてのパイプライン起動時に最初に実行する。

```javascript
// data/kill-switch.json
{
  "enabled": false,
  "reason": "",
  "enabledAt": null,
  "enabledBy": "manual"
}
```

`enabled=true` の場合:
- 全エージェントの処理を即停止
- ログに理由を記録
- Orchestrator に停止ステータスを返す

KILL SWITCH の有効化方法:
```bash
node scripts/supervisor-agent.js --kill "炎上対応のため一時停止"
node scripts/supervisor-agent.js --resume
```

### 6.2 異常検知

| 検知条件 | 対応 |
|---------|------|
| NGチェック失敗率 > 30% | Slack/メール通知（将来実装）+ ログ記録 |
| 自己採点 < 5.0 が連続3件 | Writer に警告フラグ、Analyst 再実行要求 |
| Sheets 書き込み失敗 | リトライ（最大3回）→ ログ + 通知 |
| scheduledDate 超過投稿が3件以上 | 管理画面バナー表示（既存機能） |
| kill-switch.json が存在しない | 自動作成（enabled=false）してログ警告 |

### 6.3 週次レポート生成（フェーズ2）

```
出力: data/weekly-report-YYYYWNN.json
内容:
  - 投稿数（タイプ別・軸別）
  - 自己採点平均
  - NGチェック失敗件数・失敗理由
  - 類似チェックブロック件数
  - GA4: X経由PV・セッション（フェーズ1〜）
  - X API: エンゲージ率（フェーズ3〜）
```

### 6.4 バックアップ実行

週次パイプライン開始時に `scripts/backup-sheets.js` を実行。
`data/backups/sheets-YYYYMMDD-HHMMSS.json` として保存（.gitignore 済み）。
