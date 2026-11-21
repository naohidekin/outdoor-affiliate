# trend_deepdive 仕様書（トレンド深掘り→記事誘導）

ギア男（@camp_gear_lab）の X 投稿タイプ `trend_deepdive` の仕様。
アウトドアの時流に乗ってバズを深掘りするスレッドを作り、camp-gear-lab.com の記事へ誘導する
「ニッチ内ニュースジャック」。汎用バズ寄生ではなく、既存ブランドの文脈内に限定する。

- 機械可読の定義: `data/account-config.json` の `postTypes.trend_deepdive`
- 位置づけ: 既存 `news_comment`（時事への一言・auto）の深掘り版。スレッド形式（`gear_thread` と同じ `isThread`）で、記事誘導（`article_promo` と同じ着地）を伴う。
- **実レールは claude.ai のクラウドルーティン**（毎朝 Notion 下書き）。このリポジトリのローカル v2 パイプライン（`npm run x:v2`）は温存で、その自己チェック実装（後述）を仕様の参照元とする。

---

## 大前提（既存方針との整合・破ってはいけない）

- **X API を使わない／課金を復活させない**（2026-07-30 にコスト理由で全廃）。検知は無料経路のみ。
- **自動投稿しない・無人公開しない**。生成 → Notion 下書き → 人間が手動コピペ投稿。記事は下書き止まり＋人間が公開日設定。
- **`queue-to-sheets` を復活させない**（古い下書きが暴発する地雷）。
- **リンクは本文に入れない**。`account-config.json` の `linkRules`（`noUrlInBody:true` / `urlInReply:true` / `ctaText:"詳細はリプ欄へ。"`）に従い、URL は最初の自己返信に置く。Xのリンク抑制を避けるための必須設計。
- 頻度は本物のトレンド時のみ **週1〜2本**（`weeklyCount:1` / `maxWeekly:2`）。該当するトレンドが無ければ**生成しない**（無理にひねり出さない）。既存の camp70/doctor20/parenting10 構成に上乗せし、既存投稿と人間の日次QAを溺れさせない。

---

## 発火の3ゲート

3つすべてを満たすトレンドだけを深掘りする。1つでも欠けたら見送る。

### ゲート1: オンブランドか
- アウトドア/キャンプ文脈のトレンドか（新ギア発売、バズったキャンプ/登山の話題、季節性の盛り上がり、道具の使い方論争 等）。
- 除外: AI/テック・身バレ性の高い時事（AI軸は 2026-05-02 に廃止済み）。政治・宗教・センシティブ。
- **災害・事故・炎上・逮捕・スキャンダルには乗らない**（`x-content-checks.mjs` の `NG_NEWS_SENSITIVE` が該当語を block）。人の不幸・事件に寄生しない。

### ゲート2: 着地先（記事）があるか
「詳細はリプ欄へ」で送る先が用意できるトレンドだけ深掘る。着地先は次の2択（ハイブリッド）:

- **マッチあり（既存記事へ送客）**: `data/articles.json` の **比較・レビュー記事**にトレンドが噛み合えばそこへ。ranking系・カテゴリページは SEO 実績が弱いので避ける。
- **マッチなし＋Evergreen価値あり（新規記事の種を投入）**: 検索需要が続きそうなトレンドのみ、既存の週次記事フローにテーマの種を渡す（`scripts/article-orchestrate.js` の週次 → `article-researcher-agent.js`）。生成物は `status=draft`・公開日なしで止まり、**人間が管理画面で仕上げて公開日を設定**（無人公開は封印のまま）。X スレッドは記事公開まで待つか、暫定で最も近い既存記事へ送る。

### ゲート3: ペルソナを通過するか
生成前に「この固有名詞は事実確認済みか？」をセルフチェック。抵触しそうなら**抽象化 or 沈黙**。詳細は下の「自己チェック」。

---

## トレンド検知の入力（無料経路のみ・新規構築なし）

既存レールを再利用する。X API 依存のもの（viral-scout / x-trend-researcher）は温存オフのまま使わない。

- **RSS**: `scripts/fetch-news.js`（BE-PAL / CAMP HACK / Google News キャンプ / NHK → `data/news-feed.json`）
- **Web検索**: `scripts/x/researcher.mjs` の `braveSearch()`。PR除外は同ファイルの `isPromoJunk()`。
- **個別バズ投稿の中身確認**: 必要時のみ **fxtwitter（無料）** で元ポストを読む（リプライ体制と同じ手法）。

---

## スレッドの作り方（雛形）

`gear_thread` と同じスレッド形式。1ツイート最大280字、ですます調、一人称「僕」、絵文字0〜1個、**ハッシュタグ禁止**。

1. **フック（1ツイート目）**: 今バズっている事実を1行で。煽らず、ギア男の視点で「なぜ今これが話題か」を提示。断定的誇張（最高/神/絶対 等）は使わない。
2. **深掘り（2〜3ツイート目）**: ギア男の**実体験・失敗談・比較の観点**を入れる。知識の羅列でなく体温を通す（AIが知識だけで書いた文章は不合格）。数値スペック・価格・型番の断定は事実確認済みのものだけ。
3. **実用価値＋CTA（最終ツイート）**: 読者が持ち帰れる結論。締めに `linkRules.ctaText`（「詳細はリプ欄へ。」）。
4. **最初の自己返信**: 記事URL（着地先）をここに置く。**本文ツイートにURLを入れない**（入れても `applyChecksAndLabels` が強制除去する）。

---

## 自己チェック（生成段で必ず通す・既存3チェッカーのミラー）

claude.ai ルーティンの指示にこのチェックリストを埋め込む。ローカル v2 では各 `.mjs` が実行する。

### A. 機械弾き（regex 即NG）— `scripts/x/opsec-checker.mjs` `mechanicalScan()` / `src/lib/x-content-checks.mjs`
- 車種・ブランド・モデル名（`personaGuards.carModels`）→ 「外車のSUV」まで。具体名NG。
- 医療専門科の特定（`personaGuards.medicalSpecialties`）→ 内科・小児科までは可、それ以外の科・症例・医薬品名・医療機器名NG。
- 子供の学年（`personaGuards.childGradeLevels`）→ 「小学生の息子」程度まで。
- 効能断定（`ngWords.medical` / `NG_MEDICAL_STRICT`）・景表法（`ngWords.landmark`）・政治（`ngWords.political`）・誇大（`ngWords.hype`）→ `x-content-checks.mjs` の `checkXPostContent()` が block。
- **災害・事故・炎上・逮捕（`NG_NEWS_SENSITIVE`）→ ネタにしない**（同 `checkXPostContent()` が block）。
- 1ツイート280字以内・**本文にURLを入れない**（`checkXPostContent()` の文字数チェック／`applyChecksAndLabels()` のURL強制除去）。
- **ハッシュタグ `#` を一切付けない**（生成プロンプト `src/lib/x-post-prompts.mjs:90` ＋ safety net `src/lib/x-post-generator.mjs` `stripHashtags()`。`checkXPostContent()` はハッシュタグを検出しないので、生成段で確実に落とす）。

なお車種・専門科・学年は `checkXPostContent()` では検出されず、`opsec-checker.mjs` の `mechanicalScan()`（`personaGuards` 参照）が担当する。両方を必ず通すこと。

### B. opsec 意味検査（LLM）— `scripts/x/opsec-checker.mjs` `semanticScan()`
- `unownedGearClaim`: 所有ギア allowlist（`docs/author-gear.md` / opsec-checker の `OWNED_GEAR`）以外を「愛用/所有/○年使った」と書かない（「気になる/欲しい」は可）。
- `medicalEfficacy`: 薬機法/景表法に触れる効能の断定・暗示。
- `medicalAdvice`: 個別の医療相談への具体回答（「かかりつけ医に相談」で返す）。
- `privacyLeak`: 東京より細かい地名・医院名・学校名・家族の個人名・専門科の特定。
- `hype`: 煽り・過度な宣伝・断定的誇張。

### C. 校閲（元トレンドとの整合・事実）— `scripts/x/evidence-checker.mjs`
- `coherence`（元トレンドの topic/angle から逸れていないか。ズレたら作り直し）。
- `claimsToVerify`（数値スペック・価格・型番・「○年で△△」等の事実主張を列挙 → **人間の最終確認に回す**。誤情報の拡散防止）。
- `dangerousClaim`（事実と異なると炎上/誤情報になる断定はNG）。

スレッド全体の一括検査は `checkThreadContent(tweets, {type:"trend_deepdive"})` を使う。

---

## 承認・投稿フロー

1. ルーティンが本文スレッド＋最初の自己返信（記事URL）の下書きを **Notion「ギア男 X Posts」DB** に投入（`approval: batch`）。
   - DB識別子は着手時に現物確認する。ローカルのページ作成系は `scripts/x/lib/notion.mjs` の DB ID `1d9bbe0c-30a5-4bfd-86b3-ced628cf05eb`、クラウドルーティン側は data source `6c7f4a32-4cb8-45b9-9712-c3c8bb471ae4` を参照している可能性がある。
2. 人間がスマホで確認・微修正（特に `claimsToVerify` の事実確認）。
3. X アプリに手動コピペ投稿（**本体スレッド → 最初の自己返信の順**）。
4. Notion でステータスを posted に。**自動投稿レールには一切戻さない**。

---

## 効果測定

- KPIは既存どおり **GA4 の X経由流入**＋アフィリクリック（`/admin/affiliate` の自前 `affiliate_clicks`）。
- 分析ループ（analyze-x）は当面停止中のため、当面は手動/定期で確認。効果が見えたら Notion 読み取り版の分析を後日検討。
- **天井の認識**: Xのリンク抑制でリプ欄URLのCTRは控えめ。狙いは増分トラフィックとオンブランドの権威で、一発逆転ではない。割に合うか冷静に見てから頻度を上げる。

---

## やらないこと（地雷まとめ）

- X API 復活（viral-scout / x-trend-researcher の定常運用）。
- `queue-to-sheets` 復活（古い下書き暴発）。
- 記事の無人公開・X の自動投稿。
- トレンドごとの薄い記事の乱造（Google HCU で沈む）。着地先は既存の強い比較・レビュー記事、または人間ゲートを通した新規記事に限る。
