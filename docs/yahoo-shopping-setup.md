# Yahoo!ショッピング アフィリエイト導入手順

## 導入状況（2026-07-03 時点）

- ✅ バリューコマース登録済み（サイトID: 3774986、**適正審査中**）
- ✅ Yahoo!ショッピング（プログラムID: 2025875）と提携済み
- ✅ LinkSwitch 有効化・タグ組み込み済み（vc_pid: 892651120、layout.tsx）
- ✅ 主要20記事の95商品に yahooUrl（Yahoo!検索URL）設定済み
- ⏳ **残り: バリューコマースのサイト審査完了待ち**（完了と同時に
  リンク変換が自動で動き出す。審査結果メールが来たら特に作業は不要）
- 審査完了後の拡張候補: 残り商品への yahooUrl 展開、スノーピーク公式・
  アルペン等の高料率プログラム提携申請

コード側は対応済み（2026-07-03）。products.json の `yahooUrl` フィールドに
URLを入れれば、全CTAコンポーネント（ProductCard / RankingList /
ComparisonTable / RecommendationCTA）に「Yahoo!で見る」ボタンが自動表示され、
GA4 `affiliate_click`（store: yahoo）+ /api/track-click で計測される。

## 残っている作業（人間側）

1. **バリューコマースに登録する**（Yahoo!ショッピングの公式アフィリエイトは
   バリューコマース経由。審査あり・通常数日）
   - https://www.valuecommerce.ne.jp/
   - サイト登録: camp-gear-lab.com
2. 管理画面で「Yahoo!ショッピング」プログラムと提携申請する（即時提携）
3. リンク生成は **LinkSwitch を使うのが最速**:
   - バリューコマース管理画面 → ツール → LinkSwitch → 発行される
     `<script>` タグ内の `vc_pid` を控える
   - LinkSwitch を有効にすると、ページ内の `shopping.yahoo.co.jp` への
     **直リンクが自動でアフィリエイトリンクに変換**される
   - その場合 `yahooUrl` には商品の通常URL
     （`https://store.shopping.yahoo.co.jp/...` / `https://shopping.yahoo.co.jp/search?p=...`）
     を入れるだけでよい
   - LinkSwitch スクリプトは `src/app/layout.tsx` の GA タグの下に
     `<Script src="//aml.valuecommerce.com/vcdal.js" strategy="afterInteractive" />`
     形式で追加する（vc_pid 設定込み。導入時に依頼してくれれば実装します）
4. LinkSwitch を使わない場合は、管理画面の「MyLink」で商品URLごとに
   生成した `ck.jp.ap.valuecommerce.com/servlet/referral?...` 形式のURLを
   `yahooUrl` に設定する

## yahooUrl 設定ルール（products.json）

- 検索結果URLより **商品ページ or ストア内検索URL** を優先
- 全商品一括でなくてよい。まずは売れ筋（テント・シュラフ・バーナー上位）から
- 楽天・Amazonと同様、リンク切れチェック対象に含める（check-amazon-links.js の
  拡張は未対応 → 対応時に依頼）

## 期待効果の目安

- Yahoo!ショッピング経由の料率は 1%（バリューコマース報酬）+ ストア独自設定
- 楽天とユーザー層が近いが、PayPayポイント経済圏のユーザーを取りこぼさなくなる
- 相場感: 現在の楽天クリック144/月の 2〜3割が Yahoo! に分散して上乗せされるイメージ
