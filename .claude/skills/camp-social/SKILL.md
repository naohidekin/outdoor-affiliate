---
name: camp-social
description: Camp Gear Lab の公開後SNS告知を担当する小スキル。公開URLの本文・画像を含むreadback確認後に告知案を生成し、記事承認とは別にSlackでSNS承認を取る。承認後は手動投稿用outboxへ引き継ぐ。自動投稿・予約は行わない。
---

# camp-social — 公開後SNS

## 用途
公開済み記事の告知案を生成し、独立承認後にmanual post handoffへ進める。**X旧自動投稿は廃止済みで、復活させない**（既存方針）。

> 実装・配備・実通信の確認結果は `../../../docs/editorial-pipeline.md` を正本とする。スキルの存在だけで稼働・承認・公開済みとは判断しない。

## 必要時参照
- `../../../docs/editorial-pipeline.md`（repo相対は `docs/editorial-pipeline.md`）
- `CLAUDE.md`（サイト全体の運用方針の起点）
- `docs/x-post-skill.md`（既存SNS指示）
- 既存の生成/投稿規則: `src/lib/x-post-prompts.mjs`, `scripts/post-to-x.js`, `data/account-config.json`
- 既存資料: `docs/author-profile.md`（Xアカウント・ペルソナ）

※ 上記の既存SNS指示・生成/投稿規則は、既存制限を守るための**参照先**である。既存のURL配置・投稿間隔・実行単位の投稿上限は、当該参照先で確認し遵守する（数値や規則自体は本スキルへ複製しない）。既存SNS文書中の古いURL配置/自動承認/旧投稿再稼働手順は継承しない。**SNS別承認**（実装済み）・**旧X自動投稿廃止**（既存方針）と既存投稿規則を優先し、不一致は保留する。新認証/課金/旧レール復活は行わない。

## 入力
- 公開URL
- 公開記事の本文・画像（readback用）
- 媒体（現実装はplatform=x）。予約日時は現proposal schemaにない

## 手順
1. 記事公開のverified URL・readback・fingerprint一致を確認し、本文・画像を告知案の根拠にする。
2. Claudeで `text / replyText / url / images / platform=x` を生成する。本文にURLを置かず、正確な公開URLは返信へ置く。広告表記を保つ。
3. Gemini 3.8 Flash校正と保護要素検証後、上位7.5以上の最終審査を行う。SNS本文の数値/URL/画像/文字数と医療表現もruntimeで検査する。
4. 告知案全体の独立fingerprintで、記事とは別にSlack SNS承認を取る。提案画像だけをSNS承認へ提示し、変更時は再審査・再承認する。
5. 承認後は `stateRoot/social-outbox/<revision>.json` に `approved_manual_post_pending` を記録し、Slackへ「投稿待ち」と通知する。**自動投稿・予約はしない**。
6. 本人が原稿を利用するか、Codexアプリへ記事ID付きで投稿を別途依頼する。手動投稿後の投稿ID/readback収集は現runnerの実装完了範囲に含めない。
7. 未知送信は照合まで再送しない。記事公開とSNSの成否を分離し、SNS失敗で記事を巻き戻さない。

## 出力 / 引継ぎ
- 上位審査済告知案、独立SNS承認、manual post handoffのprivate outboxとSlack通知
- `ledger.sqlite3`にSNS原稿/審査/承認を記録。記事公開の承認をSNSに流用しない。
- 新しい認証/課金/旧X自動投稿は追加しない。Telegramは使わない。修正・運用連絡のbackupはCodexアプリ。

## 停止条件
- 公開readback・版・記事内容/画像が一致しない
- 校正保護要素/上位審査/独立SNS承認が成立しない
- 未知送信を照合できない
