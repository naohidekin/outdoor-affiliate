# X (@camp_gear_lab) 運用ルール

最終更新: 2026-04-11（4軸拡張・10タイプ対応）

## アカウント

- アカウント: @camp_gear_lab
- 中の人: ギア男（37歳・2児の父・長野・キャンプ歴10年・小児科医だが基本伏せる・Claude Code愛用）
- トーン: Lake & Sky（淡々/知的/煽らない）。詳細は docs/x-post-skill.md 参照

## 発信の4軸

| 軸 | 配分 | 目的 |
|----|------|------|
| キャンプ・ギア | 40% | サイト誘導の本流 |
| AI・Claude Code | 25% | エンジニア層リーチ |
| 子育て×アウトドア | 20% | パパママ層リーチ |
| 医師×健康 | 15% | 信頼性UP |

## 投稿頻度

- **週10-12件**を目標
- 平日: 1日2スロット（朝07:30 / 夜20:00）
- 休日: 1日1スロット（昼12:15）
- IFTTT 経由の物理的な投稿上限は **1日3投稿**。超過分は翌日繰越

## 投稿タイプと配分

| タイプ | 軸 | 週頻度 | 推奨スロット | 承認 |
|--------|------|--------|-------------|------|
| article_promo | キャンプ | 2 | 昼 | まとめ承認 |
| outdoor_tip | キャンプ | 1 | 朝 / 昼 | 自動承認 |
| poll_question | 全軸 | 2 | 夜 | 自動承認 |
| failure_story | キャンプ/子育て | 1 | 夜 | 自動承認 |
| gear_thread | キャンプ | 1 | 夜（連投） | まとめ承認 |
| ai_dev_log | AI | 1-2 | 朝 / 夜 | 自動承認 |
| parenting_outdoor | 子育て | 1 | 昼 / 夜 | 自動承認 |
| doc_health_tip | 医師 | 1 | 朝 | 必ず手動承認 |
| seasonal_hook | 全軸 | 1 | 朝 | まとめ承認 |
| repost_rewrite | 全軸 | 0-1 | 昼 | まとめ承認 |

## 承認フロー

```
[Claude生成] → NGチェック自動実行
                ↓
        pass + 自動承認対象 → status=approved → queue-to-sheets.js
        pass + まとめ承認対象 → status=draft → 管理画面で週1承認
        pass + doc_health_tip → status=draft → 必ず手動承認
        fail → status=draft + validationErrors
                ↓（承認後）
        queue-to-sheets.js → 「X投稿管理」Sheets書き込み
                ↓
        IFTTT が監視・投稿 → sync-posted-status.js → status=posted
```

### 自動承認対象
- outdoor_tip, poll_question, failure_story, ai_dev_log, parenting_outdoor
- 条件: NGチェック全pass かつ URLを含まない

### まとめ承認対象（週1、月曜朝に確認）
- article_promo, gear_thread, seasonal_hook, repost_rewrite
- リンク含む or 連投のため目視確認

### 必ず手動承認
- doc_health_tip（医療情報のため常に手動確認）

## ネタシード管理

- `data/x-content-seeds.json` に250件以上のネタシードを格納
- 4軸 × テーマ × 切り口のマトリクスで自動ローテーション
- `used_count` が少ないシードを優先選択
- 季節フィルタで今月に合うシードのみ対象

## NGワード/誇大表現/PRラベル

- src/lib/x-content-checks.mjs で生成時に必須チェック
- 違反検出時は autoApprove フラグに関係なく status="draft" に強制
- カテゴリ:
  - 政治・宗教・差別: block
  - 薬機法・医療法: block（doc_health_tipで特に厳格）
  - 景表法: block
  - 誇大表現（最高/最強/絶対/神/100%等）: block
  - AI定型表現（〜してみてはいかがでしょうか等）: block
  - 煽り表現（見なきゃ損/知らないと損等）: block
- アフィリエイトリンク含む投稿は "*広告を含みます" を自動付与

## UTMパラメータ

リンクを含む全投稿に以下を自動付加:
```
?utm_source=x&utm_medium=social&utm_campaign={post_type}
```

## エラー対応

- /admin/x-posts に「予定超過バナー」(scheduledDate < 今日 && status !== posted) を表示
- バナー出現時の確認手順:
  1. Sheets「X投稿管理」シートで該当行があるか
  2. IFTTT のレシピが有効か / 直近の実行履歴
  3. 該当行の status (ready/posted/error)
  4. ANTHROPIC_API_KEY / GOOGLE_CREDENTIALS の有効性

## バックアップ

- 週次: scripts/backup-sheets.js を実行し data/backups/sheets-YYYYMMDD-HHMMSS.json を保存
- Sheets列の追加・スキーマ変更前にも必ず実行
- backups ディレクトリは .gitignore 済 (ローカル保管)

## Sheets スキーマ（拡張版）

| 列 | フィールド | 内容 |
|----|-----------|------|
| A | id | 投稿ID |
| B | type | 投稿タイプ（10種） |
| C | text | 投稿本文（gear_threadは[THREAD]プレフィクス+JSON） |
| D | articleSlug | 記事スラッグ（該当なしは空） |
| E | url | リンクURL（UTM付き） |
| F | hashtags | ハッシュタグ |
| G | status | draft/approved/queued/posted/error |
| H | scheduledDate | 投稿予定日 |
| I | generatedAt | 生成日時 |
| J | postedAt | 投稿日時 |
| K | axis | 軸（camp/ai/parenting/doctor） |
| L | seedId | 使用シードID |
| M | validationErrors | NGチェック結果 |
| N | autoApproved | 自動承認フラグ |

## 監視指標（週次レポート対象）

- 投稿数 (タイプ別・軸別)
- インプレッション (X Analytics 手動エクスポート)
- エンゲージ率
- フォロワー増減
- X 経由サイトPV (utm_source=x)
- X 経由アフィクリック数
- 違反検出件数 (validationErrors にメッセージのある投稿)

## 関連ファイル

- docs/x-post-skill.md: 投稿タイプ別トーン・フォーマット仕様（SKILL.md）
- docs/x-generate-spec.md: generate-x-posts.js 改修仕様
- src/lib/x-post-prompts.mjs: 共通プロンプト + タイプ別テンプレート
- src/lib/x-content-checks.mjs: NGワード・PRラベル
- src/lib/x-hashtags.mjs: ハッシュタグ自動選出
- src/lib/sheets-xposts.ts: Sheets I/O（A〜N列）
- src/app/admin/x-posts/page.tsx: 管理画面
- scripts/generate-x-posts.js: CLI生成（10タイプ対応）
- scripts/queue-to-sheets.js: キュー投入
- scripts/popular-repost.js: GA4 起点リポスト
- scripts/backup-sheets.js: バックアップ
- data/x-content-seeds.json: ネタシード（250件）
- data/rakuten-sale-calendar.json: 楽天セール日程
- data/amazon-deal-calendar.json: Amazonセール日程
