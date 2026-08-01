# 自動化マップ（2026-07-30 X自動投稿廃止版）

> 2026-07-11 の棚卸監査に基づく再設計に、2026-07-30 の方針転換を反映した確定版。
> 監査で判明した重要事実: **大半のジョブは移設前から実質稼働していなかった**（git履歴の定時実行痕跡で確認）。

## ⚠️ 2026-07-30 方針転換: X自動投稿レールの全廃

- **notion-poster / gearman-reply-fill を退役**。X APIコスト（有料プラン）が高すぎるため、X APIによる自動投稿をやめた
- 判明していた事実: notion-poster は 7/11 の移設時に `.env.local` から NOTION_TOKEN 等が欠落し、7/11〜7/30 の間ずっとエラー空走していた（`logs/notion-poster-error.log`）。復旧ではなく廃止を選択
- **新レール**: Claudeルーティン（claude.ai の scheduled agent、サブスク内でAPI課金なし）が毎朝Web検索で時事ネタを収集しギア男ペルソナで投稿文を生成 → Notion「ギア男 X Posts」DBに下書き投入 → **人間がスマホでXアプリに手動コピペ投稿** → Notionでpostedにマーク
- ローカルの v2 パイプライン（`npm run x:v2`、Anthropic+OpenAI API課金あり）は温存するが定常運用からは外す。アンブロ（san-pedinvestor-x）側の launchd 4本（morning/noon/sync/engage-scout）も同時退役（6/2からiCloud退避EAGAINで全停止していた）

---

## 1. 最終形: ジョブ一覧と判定

### 🟢 稼働させる4本（`scripts/setup-launchd.sh` が自動インストール）

| ジョブ | スケジュール | 役割（平たく言うと） |
|---|---|---|
| **article-daily** | 毎朝10:00 | **予約公開の執事**。公開予定日が来た記事を品質チェック→公開→Google Indexing通知→Supabase反映 |
| **link-check** | 日曜6:30 | **売り場の棚卸し係**。全Amazonリンクの生死を点検しレポート化（`data/link-check-report.json`）。結果は /admin/link-check で閲覧 |
| **link-fix** | 日曜7:00 | **売り場の自動修理係**。link-checkのbrokenを**Creators API** getItemsで確定判定（CAPTCHAの影響なし。キー無し時はHTTP再検証にフォールバック）→死亡確定は amazonUrl を自動で空に（楽天ボタンは残る）→Creators APIで代替候補を検索し提案化。差し替えは /admin/link-check で1クリック承認。※旧PA-API v5は2026年5月廃止。認証はアソシエイト・セントラルで発行した認証情報ID(amzn1...)+Secret（.env.localのAMAZON_ACCESS_KEY/SECRET_KEYに格納、バージョン3.3=日本） |

### 🟡 条件付きの2本

| ジョブ | 状態 | 条件 |
|---|---|---|
| **article-weekly**（水曜9:00） | **「下書き止まり」に改造して稼働**（本改修で writer が `scheduledPublishDate` を付けなくなった） | テーマ選定＋楽天商品調査＋AI初稿までを自動生成。**公開は絶対にしない**。人間が管理画面で仕上げて公開予定日を設定して初めて article-daily が公開する |
| **price-monitor**（日曜6:00） | **保留（未インストール）** | 復活の3条件: (a) ~~PA-APIキー~~ → **Creators API認証情報は取得済み（2026-07-11確認）**。ただしスクリプト本体が旧PA-API署名のままなのでCreators API対応の改修が必要 (b) 価格のSupabase反映経路 (c) セール告知の保存先をSheets→Notionへ付け替え |

### 🔴 退役9本（`launchd/retired/` へ移動。setup-launchd.sh が自動アンロード）

| ジョブ | 退役理由 |
|---|---|
| notion-poster | **2026-07-30退役**。X API自動投稿の廃止（コスト削減）。7/11移設時の.env.local欠落で以降ずっと空走していた。手動投稿へ移行 |
| gearman-reply-fill | **2026-07-30退役**。同上（生成にAnthropic+OpenAI API課金。投稿先レール自体を廃止したため）。リプ運用再開時はClaudeルーティン化を検討 |
| nightly-analyst | 死んだSheetsを読む分析係。X管理はNotionへ移行済みでデータが来ない。旧モデルID残存で指示書生成も空振り |
| analyze-x | 同上（分析対象=Sheetsのposted行が今後増えない）。学習ループ自体は価値があるので、投稿レール安定後（1〜2ヶ月後）にNotion読み取り版を作るか再判断 |
| sync-posted-status | Sheets前提の同期係。対象データが来ない |
| x-trend-researcher | Sheetsに下書きを書く旧レール。ネタ出しは v2 パイプライン（scripts/x/pipeline.mjs）が代替済み |
| threads-poster | Sheets読み＋60日期限トークン手動更新の二重負債。Threads転載を再開するならNotion読み＋トークン自動更新で作り直し |
| weekly-pipeline | X投稿の旧週次工場。品質ゲートがより厳格な v2 に丸ごと代替済み。復活させると二重生成＋失敗時に記事系を道連れ停止する副作用 |
| queue-to-sheets | Notion一本化により不要。**地雷あり: 復活させると4〜5月の古い下書き6件が自動投稿される** |

---

## 2. 修正後のタイムライン

### 毎日
```
朝06:30    [Claudeルーティン] ギア男時事ポスト … Web検索で時事→3本生成→Notionに下書き（Mac不要・クラウド実行）
朝07:00    [Claudeルーティン] アンブロ時事ポスト … 同上（アンブロ X Posts DBへ）
朝10:00    article-daily       … 予約日が来た記事を公開・Google通知・本番反映
（随時）   人間: Notionの下書きを確認→Xアプリに手動コピペ投稿→postedにマーク
```

### 週次
```
日曜6:30   link-check          … Amazonリンク301件の生死点検→レポート
日曜7:00   link-fix            … 死亡リンクを自動隔離+代替候補を提案（差し替えは管理画面で1クリック）
水曜9:00   article-weekly      … テーマ3本選定＋商品調査＋AI初稿（下書き止まり・公開しない）
```

---

## 3. データの流れと「人間の関門」

### 記事（収益の本流）
```
[自動] article-weekly: 成績分析→テーマ選定→楽天商品調査→AI初稿（status=draft のまま）
   ↓
【関門①】人間: 管理画面で記事を仕上げ、公開予定日を設定（ここが品質の門番）
   ↓
[自動] article-daily: 予定日到来→機械チェック(2000字/FAQ2/スコア6+)→公開→Google通知→Supabase
   ↓
[自動] link-check が売り場（Amazonリンク）を週次点検
   ↓
収益: 記事内の Amazon / 楽天 / ValueCommerce リンク
```

### X（集客の補助輪）— 2026-07-30〜「ルーティン生成＋手動投稿」
```
[自動] Claudeルーティン（毎朝06:30）: Web検索で時事収集 → ギア男ペルソナで3本生成
        → NGワード・opsec自己チェック → Notion「ギア男 X Posts」DBに下書き投入
   ↓
【関門】人間: Notionでスマホから下書きを確認（微修正OK）
   ↓
[手動] Xアプリにコピペして投稿 → Notionのステータスをpostedに変更
   ↓
X→サイト流入 → アフィリ収益（効果は GA4 / /admin/affiliate で測る）
```
- X APIは使わない（自動投稿なし・API課金なし）
- 生成はclaude.aiのルーティン（サブスク内）。Macが起きていなくても動く
- ローカルv2パイプライン（`npm run x:v2`）は予備として温存（API課金あり・定常運用外）

### あなたの日常運用（1日10分の編集長）
1. **自分の投稿に来たリプへ返信**（最優先。2〜3分）
2. Notionの時事下書き3本を確認 → 良いものをXアプリにコピペ投稿 → postedにマーク（3分）
3. 記事は自分のペースで仕上げて予約設定
4. 週1回 /admin/link-check を見て「差し替え承認待ち」を1クリック処理（隔離は自動済み）

KPIはフォロワー数ではなく **GA4のX経由流入**。

---

## 4. kill-switch（非常停止）の新仕様

一本化: **`data/kill-switch.json` が唯一の正**（旧 `~/.claude/context/kill_switch.json` は廃止）。

```jsonc
{
  "enabled": false,          // true = 全システム停止（※trueで停止、の意味に注意）
  "articleEnabled": false,   // true = 記事系のみ停止
  "researchEnabled": false,  // true = リサーチ系のみ停止
  "business": {              // true = その事業のSNS投稿のみ停止（notion-posterがDB別に参照）
    "gearman": false, "amble": false, "labo": false, "kodomo": false, "jsh": false, "drAuto": false
  },
  "reason": "", "disabledAt": "", "disabledBy": ""
}
```

- 操作: `/admin/kill-switch`（**ローカルMacのdev画面専用**。Vercel本番からは書き込めない仕様）または直接JSON編集
- 事業別フラグにより「キャンプの都合で全事業を止める」事故を解消
- ⚠️ このファイルはgit管理下にある。スイッチ操作でリポジトリがdirtyになるため、**非常停止中に `git checkout data/` や `git reset --hard` をしない**こと（停止が解除されてしまう）
- article-weekly は3連続失敗で `articleEnabled=true` を自動セット（記事系のみ自己停止。全体は道連れにしない）

---

## 5. Mac側の復旧手順（1回だけ）

```bash
cd ~/dev/outdoor-affiliate
git pull origin main

# 0. 滞留中の予約記事を先に公開（7/10予定分が止まっている）
npm run article:daily

# 1. launchd 再インストール（生かす4本を登録、退役9本を自動アンロード）
./scripts/setup-launchd.sh

# 3. 確認
launchctl list | grep outdoor-affiliate
```

---

## 6. 判断ログ（2026-07-11 確定）

| # | 論点 | 決定 |
|---|---|---|
| 1 | 別事業UI/レールの分離 | **当面共用継続**。kill-switchの事業別フラグのみ追加。本格分離は他事業の投稿量が増えてから |
| 2 | Sheets→Notion差し替え | **全面差し替えはしない**。旧Sheets前提ジョブは退役。必要になったものだけNotion対応で作り直す |
| 3 | kill-switch | **案A（ローカル完結・data/kill-switch.jsonに一本化）＋事業別フラグ** |
| 4 | 記事パイプライン | **日次=即復活（純粋に便利・リスクなし）。週次=下書き止まりに改造して半自動**（無人公開は脱AI品質基準と衝突するため封印） |
| 5 | X分析（analyze-x等） | **当面停止**。投稿レール安定後1〜2ヶ月でNotion読み取り版を作るか再判断 |
| X運用方針 | 交流の省力化 | **方針A採用**: reply-fill＋notion-poster復旧、1日10分ルーティン。viral-scout の自動探索追加は1ヶ月運用後に再検討 |

## 7. 将来の再検討リスト

- [ ] price-monitor 復活（Creators API対応の改修＋Supabase反映経路＋Notion付け替えが揃ったら）
- [ ] analyze-x のNotion読み取り版（投稿レール安定後）
- [ ] viral-scout の定期実行化（「URL探しすら面倒」になったら）
- [ ] Threads転載の作り直し（Notion読み＋トークン自動更新）
- [ ] 別事業レールの本格分離（他事業の投稿量が増えたら）
- [ ] x-posts 管理画面のNotion読み替え（当面はバナーで案内のみ）

## 2026-08-01 追記: MacBook Pro側の残骸ジョブを全停止（実行環境の一本化）

Camp Gear Labの記事データ同期でトラブルが続いた調査の過程で、**MacBook Pro側に
outdoor-affiliateのlaunchdジョブが8個登録されたまま残っており、全て起動不能だった**
ことが判明した。

**判明した事実**:
- Proの8ジョブ（article-daily/weekly, nightly-analyst, price-monitor, queue-to-sheets,
  sync-posted-status, threads-poster, weekly-pipeline）は exit code 78 (EX_CONFIG) を返し続けていた
- 真因: plistが `/opt/homebrew/bin/node`（Apple Silicon系パス）を指していたが、
  **Proのnodeは `/usr/local/bin/node`（Intel系パス）にある**。存在しないバイナリを叩いていた
- 加えてProのデスクトップにあった作業フォルダはiCloud同期の抜け殻（.git も .env.local も無い）で、
  実体を伴わない。つまりProのジョブは移設以降**一度も稼働していない**
- **実際に毎朝10:00に稼働している本物の実行環境は MacBook Air の `~/dev/outdoor-affiliate`**

**実施した対処（2026-08-01）**:
- Proの8ジョブを `launchctl bootout` で停止し、plistを `~/launchagents-backup-20260801/` へ退避（削除ではない）
- Proのデスクトップにあった抜け殻フォルダを `~/icloud-shell-backup-20260801/` へ退避
- Proの `~/dev/outdoor-affiliate/.env.local` にAirの完全版キーを配置（予備＋SSH経由の同期経路確保）
- Pro側で `npm run db:sync -- --dry-run` の動作確認済み（categories 21 / products 377 / articles 117）
  ※ Pro側でnpmを使う場合は `export PATH=/usr/local/bin:$PATH` が必要

**運用上の結論**:
- **定時実行の正本は Air の `~/dev/outdoor-affiliate` のみ**。Proは手動実行できる予備環境という位置づけ
- 作業フォルダをiCloud同期対象（デスクトップ・書類）に置かない。`~/dev` のような同期外の場所に置く
- 同一ジョブを複数マシンに登録しない（重複実行とデータ競合の温床）

## 2026-08-01 追記: 同期スクリプトに破損データガードを追加

日次パイプラインが `git stash pop` 由来の未解決コンフリクトを検知できず、
コンフリクトマーカー混入で**JSONとして壊れた articles.json をmainにコミット・push**する
事故が発生（コミット 95d5592、修復は 86e95de）。既存のガードは `.git/MERGE_HEAD` の
存在を見ていたが、stash popのコンフリクトはMERGE_HEADを作らないためすり抜けた。

対処: `scripts/sync-to-supabase.js` の冒頭に、同期対象3ファイル（articles/products/categories）の
**コンフリクトマーカー検知とJSON.parse検証**を追加。破損時は同期せず exit 1 で停止する。

