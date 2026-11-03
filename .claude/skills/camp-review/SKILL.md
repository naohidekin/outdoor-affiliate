---
name: camp-review
description: Camp Gear Lab の記事審査を担当する小スキル。文章校正（Gemini 3.8 Flash）と上位モデルによる最終審査の2層を扱う。校正は確定事実・数値・リンク・結論を変えない。合否は上位審査が出す。
---

# camp-review — 審査

## 用途
本文を校正し、上位モデルで最終審査して、記事版承認に載せられる状態にする。既存の執筆モデル既定は勝手に変えない。指摘時は camp-writing を呼び出して本文修正を依頼する。

> 実装・配備・実通信の確認結果は `../../../docs/editorial-pipeline.md` を正本とする。スキルの存在だけで稼働・承認・公開済みとは判断しない。

## 必要時参照
- `../../../docs/editorial-pipeline.md`（repo相対は `docs/editorial-pipeline.md`）
- `scripts/editorial/models.py`, `quality.py`, `runtime.py`, `ledger.py`, `render-preview.mjs`, `publish.mjs`（審査・証跡・exact版接続）
- ルート `SKILL.md`（WISE + Supervisor 11項目×10点、合格7.5、形式別字数、内部リンク2〜3、FAQ3〜5）
- 既存資料: `docs/writing-style.md`, `docs/sense-definition.md`, `docs/author-gear.md`

## 入力
- 執筆済み本文（camp-writing の出力。必要な修正は camp-writing を呼び出して依頼する）
- 執筆仕様と事実根拠（所有/使用の根拠は `docs/author-gear.md`。未確認体験は調査記事と本文で明示。現modelsの捏造禁止条件）
- 記事の画像一式（camp-eyecatch の出力）
- 記事に紐づく商品内容とリンク（Amazon / 楽天導線、内部リンク、比較タグ）
- 対象記事の形式（ranking / comparison / guide / how-to / review）

## 手順
1. **校正（Gemini 3.8 Flash）**: 文章校正のみ。**確定事実・数値・リンク・結論は変えない**。Gemini には合否を出させない。
2. **最終審査（上位モデル）**: 校正後に上位モデルで審査し、**合否を出すのはこちら**。下位の旧機械ゲート（publisher の qualityScore 6.0 / 2000字 / FAQ2）で最終審査を代用しない。
3. 審査観点: 既存の WISE + Supervisor（合格 7.5）および形式別字数・内部リンク2〜3・FAQ3〜5。層が異なるため混同しない。旧数値基準は変更しない。
4. `inspect_polish` と `inspect_bundle` を通し、Catalogの事実/画像/購入先証跡とdesktop/mobile実renderを上位審査へ渡す。qualityのmandatory_evidenceはpendingで、意味同一・事実完全性・医療・実体験を機械検証だけで認定しない。
5. **記事版指紋**はcanonical JSONのbundle全体を束縛する（本文/FAQ/brief/根拠/画像SHA/商品/リンク）。SQLite台帳は上位score>=7.5、独立証跡flags、gemini-3.8-flash校正済み、版一致を要求する。
6. 修正が入ったら承認を無効化し、**camp-writing を呼び出して本文修正を依頼**したうえで、校正/審査/再承認をやり直す。

## 出力 / 引継ぎ
- 審査結果（項目別スコア・指摘。合否は上位審査の結論）
- 修正時: camp-writing への差戻し（本文修正依頼）
- 記事版承認用の本文全文・画像プレビュー（Slack配信・記事版承認→公開の実装あり。macpro新runtime preflight/配備確認は残る）
- 台帳更新: 審査段階 → 承認待ち（実装済みSQLite台帳）

## 停止条件
- 校正で事実・数値・リンク・結論の変更が必要になった（勝手に変えず確認/保留）
- 合格基準（7.5）に到達しない
- 承認待ち上限3 に到達

## 本人承認への境界
- Slackは全文/FAQ・画像・版指定カードを配信し、認証済受信spoolの本人/route/card/nonce/完全hash/期限を台帳で照合する。過去の本人確認受付を公開承認に流用しない。
- Codex backupは本人の実メッセージによる明示的な記事ID・完全revision付き公開指示のみ。自己承認や曖昧なOKでは通さない。詳細はパイプライン文書。
- exact draft/商品、共通SEOロック、CAS更新、DB/cache/public HTMLと画像bytesのreadbackが揃って公開verifiedとなる。上位審査や本人承認だけで本番到達を認定しない。
