# 自動化マップ（2026-07-11 再設計版）

> 2026-07-11 の棚卸監査に基づく確定版。リポジトリ移設（`~/Desktop/AI関連/claude/outdoor-affiliate` → `~/dev/outdoor-affiliate`）を機に、launchd 自動化13本を「生かす4本＋条件付き2本＋退役7本」に再設計した。
> 監査で判明した重要事実: **大半のジョブは移設前から実質稼働していなかった**（git履歴の定時実行痕跡で確認）。今回は「復旧」ではなく、6月以降の実運用（手動の高品質記事運用＋Notion承認制X運用）に合わせた再設計である。

---

## 1. 最終形: ジョブ一覧と判定

### 🟢 稼働させる4本（`scripts/setup-launchd.sh` が自動インストール）

| ジョブ | スケジュール | 役割（平たく言うと） |
|---|---|---|
| **notion-poster** | 30分ごと | **投稿の実行係（最重要）**。Notionで「approved」にした投稿だけをXへ投稿。ギア男＋別事業4アカウント全部がこの1本に依存 |
| **article-daily** | 毎朝10:00 | **予約公開の執事**。公開予定日が来た記事を品質チェック→公開→Google Indexing通知→Supabase反映 |
| **gearman-reply-fill** | 10分ごと | **リプ下書き秘書**。NotionにURLを貼ると、ギア男口調の返信下書きを自動生成（opsec機械チェック＋GPT-4o独立採点付き）。対象が無ければ0円で即終了 |
| **link-check** | 日曜6:30 | **売り場の棚卸し係**。全Amazonリンクの生死を点検しレポート化（`data/link-check-report.json`）。※直すのは人間。月1でレポートを見ること |

### 🟡 条件付きの2本

| ジョブ | 状態 | 条件 |
|---|---|---|
| **article-weekly**（水曜9:00） | **「下書き止まり」に改造して稼働**（本改修で writer が `scheduledPublishDate` を付けなくなった） | テーマ選定＋楽天商品調査＋AI初稿までを自動生成。**公開は絶対にしない**。人間が管理画面で仕上げて公開予定日を設定して初めて article-daily が公開する |
| **price-monitor**（日曜6:00） | **保留（未インストール）** | 復活の3条件: (a) PA-APIキー取得（直近30日で売上3件以上が利用条件） (b) 価格のSupabase反映経路 (c) セール告知の保存先をSheets→Notionへ付け替え |

### 🔴 退役7本（`launchd/retired/` へ移動。setup-launchd.sh が自動アンロード）

| ジョブ | 退役理由 |
|---|---|
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
10分ごと   gearman-reply-fill  … NotionにURLが貼られていたら返信下書きを生成（無ければ0円）
30分ごと   notion-poster       … 承認済み投稿をXへ（1DB1件/30分）
朝10:00    article-daily       … 予約日が来た記事を公開・Google通知・本番反映
```

### 週次
```
日曜6:30   link-check          … Amazonリンク301件の生死点検→レポート
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

### X（集客の補助輪）— 方針A「省力交流」
```
[手動+自動] 投稿生成: v2パイプライン（npm run x:v2）→ AI採点・OPSEC→ Notionに下書き投入
[半自動]   リプライ: あなたがXで見つけた投稿のURLをNotionに貼る（3秒）
              → reply-fill が10分以内にギア男口調の下書きを生成
   ↓
【関門②】人間: Notionでスマホから「approved」を押す（全投稿があなたの目を通る）
   ↓
[自動] notion-poster が30分以内にXへ投稿
   ↓
X→サイト流入 → アフィリ収益（効果は GA4 / /admin/affiliate で測る）
```

### あなたの日常運用（1日10分の編集長）
1. **自分の投稿に来たリプへ返信**（最優先。2〜3分）
2. 中堅キャンプ垢（数百〜数千フォロワー）の**24時間以内の投稿にリプ2〜3件**＝URLをNotionに貼るだけ（3分）
3. Notionの下書きを承認（1〜2分）
4. 記事は自分のペースで仕上げて予約設定
5. 月1回 `data/link-check-report.json` を見てリンク切れを修理

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
    "gearman": false, "amble": false, "kodomo": false, "jsh": false, "drAuto": false
  },
  "reason": "", "disabledAt": "", "disabledBy": ""
}
```

- 操作: `/admin/kill-switch`（**ローカルMacのdev画面専用**。Vercel本番からは書き込めない仕様）または直接JSON編集
- 事業別フラグにより「キャンプの都合で全事業を止める」事故を解消
- article-weekly は3連続失敗で `articleEnabled=true` を自動セット（記事系のみ自己停止。全体は道連れにしない）

---

## 5. Mac側の復旧手順（1回だけ）

```bash
cd ~/dev/outdoor-affiliate
git pull origin main

# 0. 滞留中の予約記事を先に公開（7/10予定分が止まっている）
npm run article:daily

# 1. Notionの棚卸し: notion-poster復旧前に、停止中に溜まった
#    「approved のまま古くなった投稿」を Notion で削除/差し戻しする（重要）

# 2. launchd 再インストール（生かす5本を登録、退役7本を自動アンロード）
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

- [ ] price-monitor 復活（PA-API条件が揃ったら）
- [ ] analyze-x のNotion読み取り版（投稿レール安定後）
- [ ] viral-scout の定期実行化（「URL探しすら面倒」になったら）
- [ ] Threads転載の作り直し（Notion読み＋トークン自動更新）
- [ ] 別事業レールの本格分離（他事業の投稿量が増えたら）
- [ ] x-posts 管理画面のNotion読み替え（当面はバナーで案内のみ）
