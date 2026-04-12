# X投稿自動化 データスキーマ・採点・KILL SWITCH

最終更新: 2026-04-12

関連: docs/x-automation-spec.md / docs/x-automation-agents.md

---

## 1. データファイル一覧

| ファイル | 用途 | 作成フェーズ |
|---------|------|------------|
| data/kill-switch.json | 緊急停止フラグ | 1 |
| data/post-history.json | 投稿履歴キャッシュ（類似チェック用） | 1 |
| data/analyst-feedback.json | Analyst → Writer フィードバック | 1 |
| data/first-line-patterns.json | 書き出しパターンライブラリ | 1 |
| data/theme-tree.json | テーマ階層ツリー | 1 |
| data/weekly-report-YYYYWNN.json | 週次レポート | 2 |

---

## 2. kill-switch.json

```json
{
  "enabled": false,
  "reason": "",
  "enabledAt": null,
  "enabledBy": "manual"
}
```

| フィールド | 型 | 説明 |
|-----------|---|------|
| enabled | boolean | true で全エージェント停止 |
| reason | string | 停止理由（ログ・管理画面表示用） |
| enabledAt | string\|null | ISO8601 日時 |
| enabledBy | string | "manual" / "supervisor"（異常検知時） |

---

## 3. post-history.json

直近100件の投稿テキストを保持。類似チェック・パターン分類に使用。

```json
{
  "version": 1,
  "maxEntries": 100,
  "entries": [
    {
      "id": "xp-20260410-a1b2",
      "type": "outdoor_tip",
      "axis": "camp",
      "text": "春キャンプ、昼は暑いのに夜は5度とか...",
      "firstLinePattern": "seasonal_start",
      "selfScore": 7.8,
      "postedAt": "2026-04-10T07:30:00Z",
      "seedId": "seed-017",
      "engagements": null
    }
  ]
}
```

| フィールド | 型 | 説明 |
|-----------|---|------|
| firstLinePattern | string | 15カテゴリのいずれか（agents.md 参照） |
| selfScore | number\|null | 自己採点スコア（0.0〜10.0） |
| engagements | object\|null | フェーズ3で追加。impressions/likes/retweets/replies |

### engagements（フェーズ3）

```json
{
  "impressions": 1200,
  "likes": 45,
  "retweets": 12,
  "replies": 3,
  "urlClicks": 8,
  "fetchedAt": "2026-04-11T07:00:00Z"
}
```

---

## 4. analyst-feedback.json

```json
{
  "version": 1,
  "updatedAt": "2026-04-12T09:00:00Z",
  "period": "2026-03-15 ~ 2026-04-12",
  "topPerformingTypes": ["outdoor_tip", "failure_story"],
  "lowPerformingTypes": [],
  "effectivePatterns": [
    { "pattern": "experience_share", "reason": "体験共有型はNG通過率95%" },
    { "pattern": "number_hook", "reason": "数値フックはGA4経由PV高め" }
  ],
  "avoidPatterns": [
    { "pattern": "おすすめ", "reason": "AI定型NGに頻出" }
  ],
  "axisFeedback": {
    "camp": "安定。outdoor_tip が特に高品質",
    "ai": "ClaudeCode以外のネタ開拓が必要",
    "parenting": "季節ネタとの組み合わせが有効",
    "doctor": "NG通過に注意。薬機法表現が多い"
  },
  "seasonalInsight": "4月はGW準備ネタが刺さる。寒暖差ネタも反応良い",
  "writerHints": [
    "数値を含む投稿のパフォーマンスが高い傾向",
    "結論先出し型の書き出しを増やしてみる",
    "doc_health_tipは「本職柄」の入れ方を工夫する"
  ]
}
```

---

## 5. first-line-patterns.json

265件以上の書き出しパターン。Writer がローテーションに使用。

```json
{
  "version": 1,
  "categories": [
    {
      "id": "conclusion_first",
      "name": "結論先出し",
      "examples": [
        "○○を3年使った結論。",
        "ファミキャンのテント、答えは出てる。",
        "バーナー選びは2択でいい。"
      ]
    },
    {
      "id": "failure_open",
      "name": "失敗オープン",
      "examples": [
        "○○を知らなかった頃の話。",
        "去年これで失敗した。",
        "初心者のとき、やらかしたこと。"
      ]
    },
    {
      "id": "number_hook",
      "name": "数値フック",
      "examples": [
        "夜は−5℃。昼は22℃。",
        "設営5分。撤収3分。",
        "6年で3台買い替えた。"
      ]
    },
    {
      "id": "contrast",
      "name": "対比",
      "examples": [
        "○○と△△、どっちがいいか聞かれたら",
        "安い方と高い方、3年後の差。"
      ]
    },
    {
      "id": "question",
      "name": "疑問提起",
      "examples": [
        "テントの△△、気にしたことある？",
        "ペグに金かけてる人、どれくらいいる？"
      ]
    },
    {
      "id": "paradox",
      "name": "逆説",
      "examples": [
        "○○は高い。でもこれ以外に戻る気がしない。",
        "重い。面倒。でも手放せない。"
      ]
    },
    {
      "id": "experience_share",
      "name": "体験共有",
      "examples": [
        "先週、○○したら△△だった。",
        "この前のキャンプで気づいたこと。"
      ]
    },
    {
      "id": "seasonal_start",
      "name": "季節起点",
      "examples": [
        "4月のキャンプ場、夜は5℃を下回る。",
        "梅雨入り前にやっておくこと。"
      ]
    },
    {
      "id": "product_compare",
      "name": "製品比較",
      "examples": [
        "○○か△△か、と聞かれたら",
        "この2つ、迷ってる人が多いので書く。"
      ]
    },
    {
      "id": "parenting",
      "name": "子育てネタ",
      "examples": [
        "子供に△△って聞いたら○○と返ってきた。",
        "息子がキャンプで一番喜んだもの。"
      ]
    },
    {
      "id": "ai_dev",
      "name": "AI/開発",
      "examples": [
        "Claude Codeに○○をやらせてみた。",
        "AIに記事を書かせて気づいたこと。"
      ]
    },
    {
      "id": "doctor_view",
      "name": "医師視点",
      "examples": [
        "本職柄、○○にはちょっとうるさい。",
        "キャンプ場での△△、半分正解で半分間違い。"
      ]
    },
    {
      "id": "hack",
      "name": "ハック/工夫",
      "examples": [
        "○○のときは△△にすると解決する。",
        "地味だけど効果があった工夫。"
      ]
    },
    {
      "id": "poll",
      "name": "アンケート",
      "examples": [
        "○○するとき、どっち派？",
        "テント選びで一番重視するのはどれ？"
      ]
    },
    {
      "id": "summary",
      "name": "まとめ",
      "examples": [
        "○○について3点だけ。",
        "今季のキャンプ、やっておくこと。"
      ]
    }
  ]
}
```

---

## 6. theme-tree.json

4軸のテーマを階層管理。ギャップ検出に使用。

```json
{
  "version": 1,
  "axes": {
    "camp": {
      "children": {
        "gear": {
          "children": {
            "tent": { "used_count": 5, "last_used": "2026-04-05" },
            "burner": { "used_count": 3, "last_used": "2026-03-28" },
            "sleeping_bag": { "used_count": 2, "last_used": "2026-03-15" },
            "lantern": { "used_count": 1, "last_used": "2026-02-20" },
            "table_chair": { "used_count": 0, "last_used": null }
          }
        },
        "technique": {
          "children": {
            "setup": { "used_count": 2, "last_used": "2026-04-01" },
            "fire": { "used_count": 3, "last_used": "2026-04-08" },
            "cooking": { "used_count": 1, "last_used": "2026-03-10" },
            "rain_camp": { "used_count": 0, "last_used": null }
          }
        },
        "location": {
          "children": {
            "nagano": { "used_count": 2, "last_used": "2026-03-20" },
            "highland": { "used_count": 1, "last_used": "2026-02-15" }
          }
        }
      }
    },
    "ai": {
      "children": {
        "claude_code": { "used_count": 4, "last_used": "2026-04-10" },
        "site_building": { "used_count": 2, "last_used": "2026-03-25" },
        "prompt_tips": { "used_count": 1, "last_used": "2026-03-01" }
      }
    },
    "parenting": {
      "children": {
        "family_camp": { "used_count": 3, "last_used": "2026-04-07" },
        "kids_gear": { "used_count": 1, "last_used": "2026-03-12" },
        "kids_reaction": { "used_count": 2, "last_used": "2026-03-30" }
      }
    },
    "doctor": {
      "children": {
        "heat_stroke": { "used_count": 1, "last_used": "2026-03-20" },
        "insect_bite": { "used_count": 0, "last_used": null },
        "first_aid": { "used_count": 1, "last_used": "2026-02-28" },
        "hydration": { "used_count": 1, "last_used": "2026-03-15" }
      }
    }
  }
}
```

---

## 7. 自己採点プロンプト仕様

Writer が生成テキストを Claude API で再評価する際のプロンプト構造:

```
あなたは X 投稿の品質審査員です。
以下の投稿を10基準で採点してください（各0〜10点）。

## 投稿
タイプ: {type}
軸: {axis}
テキスト:
{text}

## 採点基準
1. Lake & Sky トーン: 淡々・知的・非煽り
2. 体験ベース: 一人称体験感があるか
3. 具体性: 数値・製品名・状況の具体性
4. 文字数適正: 200〜280文字の範囲
5. ハッシュタグ適正: 2〜3個で本文と整合
6. タイプ適合: 投稿タイプの目的に合致
7. 軸適合: 発信軸のトーンに合致
8. オリジナリティ: 既視感がないか
9. フック強度: 1行目の引きつけ力
10. アクション明確: 読後行動が促されるか

## 出力形式（JSONのみ）
{ "scores": [8, 7, 9, 8, 7, 8, 9, 6, 7, 8], "total": 7.7, "comment": "..." }
```

### 閾値とリトライ

```
スコア >= 7.0 → 合格（通常フローへ）
スコア < 7.0（1回目） → 同シード・別表現で再生成
スコア < 7.0（2回目） → 同シード・別表現で再生成
スコア < 7.0（3回目） → status="discarded" で記録、この投稿はスキップ
```

---

## 8. 類似チェック仕様

### TF-IDF コサイン類似度

```
対象: post-history.json の直近100件 vs 新規生成テキスト
前処理:
  1. ハッシュタグ・URL を除去
  2. 形態素分析（kuromoji or 簡易分割）で単語分割
  3. TF-IDF ベクトル化
  4. コサイン類似度を計算

閾値: 0.6
  > 0.6 → 再生成（1回まで）
  再生成後も > 0.6 → draft + "類似投稿あり" エラー
```

### 簡易実装（フェーズ1）

フェーズ1では形態素分析ライブラリなしで動作する簡易版を実装:
- bigram（2文字単位）で分割
- Set の Jaccard 係数で類似度を算出
- 閾値は同じく 0.6

---

## 9. Sheets スキーマ拡張

フェーズ1で「下書き管理」シートに列を追加:

| 列 | フィールド | 内容 | 追加時期 |
|----|-----------|------|---------|
| A〜N | （既存） | docs/x-operations.md 参照 | 既存 |
| O | selfScore | 自己採点スコア（0.0〜10.0） | フェーズ1 |
| P | firstLinePattern | 書き出しパターン分類 | フェーズ1 |
| Q | similarityScore | 最大類似度スコア | フェーズ1 |
| R | retryCount | リトライ回数（0/1/2） | フェーズ1 |
