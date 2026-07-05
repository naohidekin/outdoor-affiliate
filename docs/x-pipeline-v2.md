# ギア男 X投稿 段階分割パイプライン v2（amble踏襲）

`scripts/x/` の段階分割パイプライン。旧モノリス `scripts/generate-x-posts.js`
の弱点（①自己採点で点が甘い ②ネタと投稿の噛み合い・校閲が抜ける
③探索が広すぎてPR/キャンペーンを拾う）を、amble（Dr-amble）が通った
段階分割アーキテクチャの移植で構造的に解消する。

## パイプライン

```
researcher → writer → reviewer → evidence → opsec → (人間承認) → 既存キュー → 投稿
  ネタ収集    ドラフト  独立採点   校閲/整合  ガード
```

status 遷移（`data/x/posts.jsonl`）:
`draft → cross_reviewed → evidence_ok → reviewed → approved`（各段で落ちたら `rejected`）

| 段 | ファイル | 役割 | 3欠陥との対応 |
|----|---------|------|--------------|
| researcher | researcher.mjs | 手キュレーション検索プール(camp0.7/doctor0.2/parenting0.1)＋PR除外＋軸40%超自動抑制＋dedup | ③PR拾い是正 |
| writer | writer.mjs | ネタ→ドラフト生成。**自己採点なし**。SimHash重複のみ弾く | ①自己採点廃止 |
| reviewer | reviewer.mjs | **GPT-4o独立採点**(WISE-GEARMAN)。passはサーバ側再計算 | ①甘さ排除 |
| evidence | evidence-checker.mjs | 投稿がネタから逸れていないか＋検証不能な断定スペック検出 | ②校閲欠落是正 |
| opsec | opsec-checker.mjs | 機械regex(車種/専門科/学年/薬機法)＋LLM意味検査(未所有ギア/効能断定/身バレ) | 捏造・コンプラ |

## 実行（あなたのMac）

前提: リポジトリを Mac にクローン済みで `.env.local` にキーがあること。

```bash
cd <repo>
git pull origin main

# まずドライラン（何も書き換えず流れを確認）
npm run x:v2:dry

# 本番（ネタ10・ドラフト6目安）
npm run x:v2 -- --ideas 10 --posts 6

# reviewed を確認 → 承認（doctor軸は個別承認）
npm run x:v2:approve -- --list
npm run x:v2:approve -- --all              # doctor軸以外を一括
npm run x:v2:approve -- --id gx-YYYYMMDD-xxxx

# 承認分は既存 data/post-queue.json に入り、既存 queue-to-sheets が投稿
```

途中段からの再実行: `npm run x:v2 -- --from reviewer`

## 必要な環境変数（.env.local）

| 変数 | 用途 | 無い場合 |
|------|------|---------|
| `ANTHROPIC_API_KEY` | 生成・フォールバック採点 | writer/researcherがスキップ |
| `OPENAI_API_KEY` | **別ベンダー独立採点(GPT-4o)** | Claude haikuへフォールバック（独立性低下・警告表示） |
| `BRAVE_API_KEY` | researcherのWeb検索 | 検索スキップ（news-feedのみ） |

**推奨: `OPENAI_API_KEY` を設定する。** 無いと採点が同ベンダー(Claude)になり、
自己採点の甘さを完全には排除できない（v2の主目的が半減する）。

## kill-switch

`data/kill-switch.json` の `enabled=true` で全体停止、`researchEnabled=true` で
researcher段のみ停止（既存セマンティクスに準拠）。

## 既存パイプラインとの関係

- 生成脳（ペルソナ・NGワード・軸比率）は `data/account-config.json` を共有。
  v2は `scripts/x/lib/persona.mjs` が同 config から system プロンプトを構築する。
- 投稿・計測は既存 `queue-to-sheets.js` / `sync-posted-status.js` / `analyst-agent.js`
  をそのまま使う（approve.mjs が既存キュー形状で橋渡し）。
- 旧 `x:generate` / `x:orchestrate:*` は当面残す。v2が安定したら weekly を
  `npm run x:v2` に差し替える（launchd の weekly plist を変更）。

## データドリブン化の次段（未実装・設計メモ）

analyst-agent が既に `high-performer-patterns.json` / `analyst-feedback.json` を
生成している。次段では researcher がこれらを読み、伸びた投稿の軸/フォーマットへ
QUERY_POOLS の重みを寄せる（＝GSC/GA相当のシグナル→ネタ選定のクローズドループ）。
記事側も同型（GSC gap クエリ→トピック→draft→独立採点→evidence→公開→GSC測定）に
展開可能。
