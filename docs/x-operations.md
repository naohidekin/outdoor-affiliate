# X (@camp_gear_lab) 運用ルール

最終更新: Phase 1 完了時点

## アカウント

- アカウント: @camp_gear_lab
- 中の人: ギア男（37歳・2児の父・長野・キャンプ歴10年・本職は医師だが基本伏せる）
- トーン: Lake & Sky（淡々/知的/煽らない）。詳細は CLAUDE.md「X 投稿のトーン」参照

## 投稿頻度

- 平日: 1日3スロット（朝07:30 / 昼12:15 / 夜20:00）
- 休日: 1日1スロット（昼12:15）
- ただし IFTTT 経由の物理的な投稿上限は **1日3投稿**。超過分は翌日繰越

## 投稿タイプと推奨スロット

| タイプ | 説明 | 推奨スロット |
|---|---|---|
| article_promo | 既存記事紹介 | 昼 |
| outdoor_tip | 豆知識 | 昼 / 夜 |
| article_repost | 人気記事リポスト (GA4起点) | 昼 / 夜 |
| seasonal | 季節・天候連動 | 朝 |
| rakuten_sale | 楽天マラソン/スーパーセール連動 | 夜 |
| amazon_deal | Amazonタイムセール連動 | 夜 |
| news_comment | ニュースにひとこと | 朝 |
| gear_story | 愛用ギアの小話 (※author-gear.md 完成後に有効化) | 夜 |

## 承認フロー

```
[Claude生成] → status=draft → 管理画面で承認 → status=approved
                                 ↓
                         queue-to-sheets.js
                                 ↓
                         status=queued + 「X投稿管理」に書き込み
                                 ↓
                         IFTTT が監視・投稿
                                 ↓
                         sync-posted-status.js (IFTTT実行後)
                                 ↓
                         status=posted
```

- **当面は全投稿承認制**
- 自動承認の解禁条件: 「Phase 1 実装完了 + 3週間誤爆ゼロ」両方達成後
- 自動承認解禁時も、対象は news_comment / outdoor_tip のみ。article_promo / sale系は承認制継続

## NGワード/誇大表現/PRラベル

- src/lib/x-content-checks.mjs で生成時に必須チェック
- 違反検出時は autoApprove フラグに関係なく status="draft" に強制
- カテゴリ:
  - 政治・宗教・差別: block
  - 薬機法・医療法: block
  - 景表法: block
  - 誇大表現（最高/最強/絶対/神/100%等）: block
  - AI定型表現（〜してみてはいかがでしょうか等）: warn
- アフィリエイトリンク含む投稿は "*広告を含みます" を自動付与

## エラー対応

- /admin/x-posts に「予定超過バナー」(scheduledDate < 今日 && status !== posted) を表示
- バナー出現時の確認手順:
  1. Sheets「X投稿管理」シートで該当行があるか
  2. IFTTT のレシピが有効か / 直近の実行履歴
  3. 該当行の status (ready/posted/error)
  4. ANTHROPIC_API_KEY / GOOGLE_CREDENTIALS の有効性
- エラー時の Gmail 通知は Phase 5 (自動化フェーズ) で実装

## バックアップ

- 週次: scripts/backup-sheets.js を実行し data/backups/sheets-YYYYMMDD-HHMMSS.json を保存
- Sheets列の追加・スキーマ変更前にも必ず実行
- backups ディレクトリは .gitignore 済 (ローカル保管)

## 自動化の制約（Phase 5 までは破らない）

- X API 直接利用は禁止（Phase 3 で承認後のみ）
- scheduled-tasks/cron による定期発火は Phase 5 解禁まで未設定
- 全投稿の手動承認制を維持

## 監視指標（週次レポート対象）

- 投稿数 (タイプ別)
- インプレッション (X Analytics 手動エクスポート)
- エンゲージ率
- フォロワー増減
- X 経由アフィクリック数 (Phase 4 で utm_source=x 実装後)
- 違反検出件数 (validationErrors にメッセージのある投稿)

## 関連ファイル

- src/lib/x-post-prompts.mjs: 共通プロンプト（Lake & Sky トーン）
- src/lib/x-content-checks.mjs: NGワード・PRラベル
- src/lib/x-hashtags.mjs: ハッシュタグ自動選出
- src/lib/sheets-xposts.ts: Sheets I/O（A〜N列）
- src/app/admin/x-posts/page.tsx: 管理画面
- scripts/generate-x-posts.js: CLI生成
- scripts/queue-to-sheets.js: キュー投入
- scripts/popular-repost.js: GA4 起点リポスト
- scripts/backup-sheets.js: バックアップ
- scripts/replace-kenta.js: 「ケンタ」→「ギア男」一括置換
- data/rakuten-sale-calendar.json: 楽天セール日程（手動メンテ）
- data/amazon-deal-calendar.json: Amazonセール日程（手動メンテ）
