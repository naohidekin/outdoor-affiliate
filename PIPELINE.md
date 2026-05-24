# ギア男HP 記事生成パイプライン（WISE + Codexレビュー）

設計書 `/Users/NaohideKin/.claude/plans/toasty-fluttering-sphinx.md` の「新パイプライン設計」に準拠。

## 全体フロー

```text
[weekly launchd: Wed 09:00 JST]
  |
  v
[1] Analyst
    - GA4 + affiliate-clicks
    - effectivePatterns 生成（Claude Sonnet）
  |
  v
[2] Researcher
    - season map + analyst feedback
    - GSC rank11-30 & 100imp+ query 注入
    - Brave insights 注入
  |
  v
[3] Product Agent
    - 楽天APIで商品収集
  |
  v
+---------------- QUALITY LOOP (max 2 cycles) ----------------+
| [4] Writer (WISE prompt + affiliate rules)                  |
|     -> draft article                                         |
| [5] Codex Reviewer (cycle 1 only)                           |
|     -> wise_scores + revised_content                         |
| [6] Supervisor (10 criteria, threshold 7.5/10)              |
|     -> fail on cycle1 => feedback inject and regenerate      |
|     -> fail on cycle2 => rejected.json                       |
+-------------------------------------------------------------+
  |
  v
[7] Publisher
    - internal link / shortcode check
    - publish + indexing + X promo draft
  |
  v
[8] sync / git / daily follow-up
```

## エラー処理方針

- Researcher の GSC / Brave 取得失敗は `try/catch` でスキップ（非ブロッキング）。
- Codex Reviewer 失敗時は警告のみ。元本文を保持して継続。
- Supervisor fail は cycle 1 なら再生成、cycle 2 なら `rejected.json` 記録。
- Publisher は品質要件不足の記事を公開せずスキップ。

## Kill Switch

- `kill-switch.json` の `enabled` または `articleEnabled` が真なら記事パイプライン停止。
- Orchestrator は実行中の連続失敗3回で `articleEnabled=true` を自動設定。
- `supervisor-agent.js --resume` で全体 Kill Switch を復帰。
- Kill Switch 状態は各エージェント起動時に先頭チェックする。

## 時刻基準

- 公開判定・日付計算は JST（UTC+9）基準で運用。
