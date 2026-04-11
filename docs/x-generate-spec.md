# generate-x-posts.js 改修仕様

## 目的

現行の2タイプ（article_promo + outdoor_tip）生成スクリプトを、10タイプ対応に拡張する。
ネタシード（`data/x-content-seeds.json`）を参照し、ローテーション管理を行う。

---

## 変更点

### 1. シード参照の追加
- `data/x-content-seeds.json` を読み込む
- 今月の季節（月番号）に合うシードをフィルタ
- `used_count` が少ない順に優先選択
- 生成後に `used_count` をインクリメント、`last_used` を今日の日付に更新
- seeds.jsonはスクリプト終了時にファイルに書き戻す

### 2. タイプ別生成ロジック

週次バッチ生成の配分:

| タイプ | 件数 | 軸 |
|--------|------|-----|
| article_promo | 2 | camp |
| outdoor_tip | 1 | camp |
| poll_question | 2 | 全軸（週替わりで軸を変える） |
| failure_story | 1 | camp/parenting |
| gear_thread | 1 | camp（3-5ツイート分をまとめて生成） |
| ai_dev_log | 1-2 | ai |
| parenting_outdoor | 1 | parenting |
| doc_health_tip | 1 | doctor |
| seasonal_hook | 1 | 全軸 |
| repost_rewrite | 0-1 | 全軸（過去投稿データがある場合のみ） |

合計: 11-13件/週

### 3. プロンプト分離
- タイプ別プロンプトを `src/lib/x-post-prompts.mjs` に外出し
- エクスポート: `getPromptForType(type, context)` 関数
- contextには季節情報、選択されたシード、記事データ等を渡す
- 共通部分（ペルソナ設定・季節コンテキスト）は共通プロンプトとして維持

### 4. UTMパラメータ自動付与
リンクを含む投稿に以下を自動付加:
```
?utm_source=x&utm_medium=social&utm_campaign={type}
```
対象: article_promo, gear_thread（最終ツイート）, seasonal_hook（リンクあり時）, parenting_outdoor（リンクあり時）

### 5. 自動承認ロジック

生成後のステータス振り分け:

```
NGチェック → fail → status="draft" + validationErrors にメッセージ
           → pass → タイプ判定
                     → 自動承認対象 → status="approved"
                     → まとめ承認対象 → status="draft"
                     → doc_health_tip → status="draft"（常に手動）
```

自動承認対象: outdoor_tip, poll_question, failure_story, ai_dev_log, parenting_outdoor
まとめ承認対象: article_promo, gear_thread, seasonal_hook, repost_rewrite
必ず手動: doc_health_tip

### 6. CLIオプション追加

```bash
node scripts/generate-x-posts.js                    # 週次バッチ（全タイプ）
node scripts/generate-x-posts.js --type ai_dev_log   # 特定タイプのみ
node scripts/generate-x-posts.js --count 5            # 件数指定
node scripts/generate-x-posts.js --dry-run             # 生成のみ（Sheets書き込みなし）
node scripts/generate-x-posts.js --axis camp           # 特定軸のみ
```

### 7. 出力スキーマ拡張

Sheets列の追加（既存A〜J列の後ろに追加）:

| 列 | フィールド | 内容 |
|----|-----------|------|
| K | axis | camp / ai / parenting / doctor |
| L | seedId | 使用したシードID（seed-001等） |
| M | validationErrors | NGチェック結果（空ならpass） |
| N | autoApproved | true / false |

### 8. gear_thread のスレッド対応

- gear_thread は `tweets` フィールドに配列で格納
- Sheets上は `text` 列に `[THREAD]` プレフィクス + JSON文字列
- queue-to-sheets.js 側で `[THREAD]` を検出し、複数行に展開してIFTTT連携
- 各ツイートの投稿間隔: 1分（IFTTT側で制御）

---

## 新規ファイル

### src/lib/x-post-prompts.mjs

```javascript
// エクスポート
export function getCommonPrompt(persona, seasonContext) { ... }
export function getPromptForType(type, context) { ... }
export const POST_TYPES = { ... }
export const APPROVAL_RULES = { ... }
```

### NGチェック拡張: src/lib/x-content-checks.mjs

既存のNGワードリストに以下を追加:
- 薬機法カテゴリ: 「治る」「効く」「改善する」「副作用」
- 医療法カテゴリ: 「診断」「処方」「投薬」「〜すべき」（医療文脈で）
- doc_health_tip タイプは上記カテゴリを厳格チェック（他タイプではwarn止まり）

---

## スケジュール（npm scripts追加）

```json
{
  "x:generate": "node scripts/generate-x-posts.js",
  "x:generate:dry": "node scripts/generate-x-posts.js --dry-run",
  "x:generate:camp": "node scripts/generate-x-posts.js --axis camp",
  "x:generate:ai": "node scripts/generate-x-posts.js --axis ai"
}
```
