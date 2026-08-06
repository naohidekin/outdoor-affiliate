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
| **price-monitor**（日曜6:00） | **手動運用可。launchd登録は保留** | (a) ~~PA-API署名の改修~~ → **2026-08-06にCreators APIへ移行済み**。変動率ガード付きで手動実行できる (b) ~~価格のSupabase反映経路~~ → **完了**（実行後に `sync-to-supabase --no-pull` を自動実行） (c) セール告知の保存先をSheets→Notionへ付け替え **← 未着手。launchd登録はこれが済んでから** |

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

- [ ] price-monitor のlaunchd登録（~~Creators API対応~~ ~~Supabase反映経路~~ は2026-08-06に完了。残るはセール告知のNotion付け替え）
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


## 複数マシンで触るときの同期手順（2026-08-01 追記）

`sync-to-supabase.js` は既定で「Supabase → ローカルJSON書き戻し（auto-pull）」を先に実行する。
このとき記事・商品が `updated_at` 順に並べ替えられるため、**git上の並びと食い違って
全行が差分として出る**（実害はないが、次回の `git pull` が
"Your local changes would be overwritten" で止まる原因になる）。

### 推奨フロー

リモート（Claude Code / Web）で編集 → Macに取り込んで本番反映する場合:

```bash
cd ~/dev/outdoor-affiliate
git pull                                    # 先にgitを最新にする
node scripts/sync-to-supabase.js --no-pull  # 書き戻しをせずSupabaseへ反映
```

`--no-pull`（または `SKIP_AUTO_PULL=1`）を付ければローカルJSONは書き換わらず、
gitの状態がきれいなまま保たれる。

### auto-pull を使うべきケース

**管理画面（/admin）でSupabase側を直接編集した直後**は auto-pull が必要。
その編集はgitに存在しないため、`--no-pull` で同期するとローカル（＝git）の内容で
上書きされて失われる。この場合は素直に auto-pull ありで実行し、
書き戻しで出た差分はコミットしてgitに戻す。

### 並び替え差分が出てしまったときの片付け

書き戻し差分は「並び替えのみ」であることがほとんど（追加行数と削除行数がほぼ同数なら並び替え）。
記事の欠落がないことを確認してから捨てる:

```bash
git stash push -m "sync-writeback" data/articles.json data/products.json
node -e 'const a=require("./data/articles.json");console.log("記事数",a.length,
  "／公開",a.filter(x=>x.status==="published").length)'
git stash drop   # 欠落がなければ捨てる
```

### 定時パイプラインの自動コミット（2026-08-01 修正）

`article-orchestrate.js`（日次）と `orchestrate.js`（週次）は実行後に
`data/` を自動コミット＆プッシュする。以前は commit 直後に push していたため、
リモートが先に進んでいると push が弾かれ、**ローカルにコミットだけが取り残された**。
翌日以降 `git pull` が divergent branches で止まり、手作業の復旧が必要になっていた。

現在は `commit → git pull --rebase → push` の順に修正済み。競合時は
`rebase --abort` して中断しエラーを返す（データJSONを機械的に片側へ倒すと
記事・商品が丸ごと消えるため、人が中身を見て判断する）。

**パイプラインが「rebase失敗」で終了していたら**、Mac上で状況を確認して手動で解決する:

```bash
cd ~/dev/outdoor-affiliate
git log --oneline origin/main..HEAD   # ローカルにだけあるコミット
git log --oneline HEAD..origin/main   # リモートにだけあるコミット
git status --short
```

そのうえで `git pull --rebase` を実行し、競合したファイルは中身を見て解決する。
`git checkout --ours/--theirs` は使わない（JSONが片側に倒れてデータが消える）。

---

## 2026-08-06: アフィリエイトリンクの取りこぼし一斉修正とCreators API移行

### 何が起きていたか

7月最多クリックの コロナ PA-F85A（511クリック）が楽天成果ゼロだった件を
起点に調べたところ、同じ構造の取りこぼしが広範囲にあった。

- 楽天 `affiliateUrl` … 81件が検索結果ページ行き
- Amazon `amazonUrl` … 77件が `/s?k=...` の検索結果ページ行き

Amazon側の混入時期を追うと壊れ率は **2026-04:14% → 06:28% → 07:76%** と上昇。
PA-API v5 の段階的停止（OffersV2は1月末、本体は5/15）でASINが取得できず、
フォールバックの検索URLが入り続けたのが原因だった。

**検索結果ページに着地した読者は迷子になり、成約しない。**

### 直した結果

| 対象 | 修正 | 残 |
|---|---|---|
| 楽天リンク | 20件を商品直リンクへ | 61件 |
| Amazonリンク | 39件を商品直リンクへ | 38件 |
| Amazon価格 | Creators APIへ移行し92件を更新 | — |
| 異常価格 | 誤ASIN由来の7件を差し戻し | — |

### 追加・改修したスクリプト

| スクリプト | 用途 |
|---|---|
| `fix-search-affiliate-links.mjs` | 楽天。信頼度3段階・`--explain`・`--only` を追加 |
| `fix-amazon-search-links.mjs` | **新規**。Amazon版。Creators API searchItems を使う |
| `price-monitor.js` | **Creators APIへ移行**。`--dry-run` と変動率ガードを追加 |
| `apply-held-price.mjs` | **新規**。ガードで保留した価格を目視後に個別適用 |
| `revert-price-anomalies.mjs` | **新規**。異常な価格更新を差し戻す。`--fix-drift` で復旧 |
| `src/lib/amazon-creators-api.mjs` | **新規**。トークン取得・429リトライ・getItems/searchItems |
| `src/lib/product-match.mjs` | **新規**。商品名照合ロジック（楽天/Amazon共通） |

### 踏んだ落とし穴（再発させないこと）

1. **`updatedAt` を進めないと同期で巻き戻る**
   `pull-from-supabase` は「ローカルの updatedAt がリモートより新しい」行だけを
   push待ちとして保持する。価格やURLだけ書き換えたスクリプトは、次の
   `sync-to-supabase` の auto-pull で旧値に上書きされる。実際に差し戻した7件が消えた。
   **データを直接書き換えるスクリプトは必ず `updatedAt` を進める。**

2. **同期は `npm run db:sync -- --no-pull` を使う**
   まだDBに無いローカルの修正を auto-pull が旧値で潰す。二重の保険として付ける。

3. **楽天APIはIPv4のIP許可リスト。IPv6回線だと永久に一致しない**
   `curl -s ifconfig.me` がIPv6を返す環境では、その値を登録しても無意味。
   `curl -4 -s ifconfig.me` でIPv4を確認して登録する。スクリプト側は
   `dns.setDefaultResultOrder("ipv4first")` で固定済み。
   許可IPはCIDR表記も使える（`143.189.126.0/24` 等）。移動のたびに追記が必要。

4. **同一ASINを複数商品が共有している**
   おにやんま君（`chair-006` / `insect-repellent-001`）、
   スランバーシュラフ・2（`sb-kids-003` / `sb-budget-002`）など。
   片方だけ更新すると価格が食い違う。`find` ではなく `filter` で全件そろえる。

5. **低信頼の提案は半数近くが別商品**
   楽天で低13件中6件、Amazonで低10件中3件が誤り（WAVE 2→WAVE 3、
   本体→ソーラーパネルセット、別ブランドなど）。
   **`--apply` は高・中のみ。低は目視して `--only` で通す。**

6. **Amazonの検索結果は実行ごとに揺らぐ**
   同じ商品・同じキーワードでも、順位変動で別ASINが返る。
   「一致率100%」が毎回出るとは限らない。適用後の再検証が要る。

### 帰国後のチェックリスト

- [ ] `data/price-held-back.json` の7商品を確認。ASINが本体を指しているか
      （焚火台L `B000AR4TJQ`／マナイタセットM `B07RR9HQ7V`／
      ヘリノックス ビーチチェア `B0BD4FFN59` が特に怪しい）。
      正しければ `apply-held-price.mjs <ID>`、誤りなら `amazonUrl` を差し替え
- [ ] 8/9（日）の `link-check` / `link-fix` が動いたか確認
- [ ] 適用済み59件のASIN・URLを `getItems` で再検証（上記6のため）
- [ ] スキップ分の追い込み（楽天61件・Amazon38件）。
      Amazonは「一致率不足」が28件と最多。商品名が冗長で一致率が構造的に下がる
- [ ] 重複商品の統合とID整理（おにやんま君が `chair-006`、
      岩鋳のスキレットが `tent-015` など、IDとカテゴリが不整合）
- [ ] 楽天リンク修正の効果測定（適用から3〜4週後）
- [ ] `price-monitor` のセール告知をSheets→Notionへ付け替え（launchd登録の前提）
