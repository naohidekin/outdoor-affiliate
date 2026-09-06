# 2026-09-06 寝袋3記事の出典確認と公開記録

認証済み管理画面から本番DBへ公開済み。既存slugは維持した。Git内のJSONとMarkdownは原稿・履歴の保存であり、本番DBへの自動同期ではない。プログラム本体の変更はない。

## 公開した内容

| 記事 | 主な変更 |
|---|---|
| nanga-sleeping-bag-comparison | NANGA5モデルの温度表示・素材・サイズの比較へ整理。永久保証の有償項目・対象外条件を明記。別注・旧モデルを名称だけで同一仕様と扱わない |
| spring-sleeping-bag-guide | NANGA450DX、LOGOS72602010、Coleman2000034775の3候補へ整理。LOGOSの「適正温度」をComfortに読み替えない。洗濯・連結・家族分の収納を購入判断に加える |
| winter-sleeping-bag-ranking | NANGA600DX・750DXとモンベル1121424（シームレス バロウバッグ#1）の3候補へ整理。温度条件に合わない製品を補助暖房で代用する誘導を撤去 |

3記事とも、確認できない使用体験・診療経験・口コミの集計、季節と標高だけで決めた気温表、温度改善の足し算、使用条件の保証、恒常的な品薄をあおる表現を取り除いた。NANGA記事内の古い寄付額・ポイント獲得を含むふるさと納税の説明も削除し、返礼品の型番等の確認点へ絞った。

購入リンクは商品名と確認目的が分かる文言へ変更。新たな商品IDやAmazon ASINは推測して追加していない。モンベル#1は公式の購入ページへ案内する。本文内の旧商品カード・旧比較表トークンを取り除き、関連商品の選択も解除したため、今回確認していない台帳の評価・説明文が当該記事のカードへ再表示されない。記事の概要・SEO説明文・FAQも本文に合わせて更新した。

## 主要な確認先

- NANGA 温度表示: https://nanga.jp/_classic_/knowledge/european-norm/
- NANGA 現行商品ページ: https://store.nanga.jp/products/aurora-tex-light-450dx-1 / https://store.nanga.jp/products/aurora-tex-light-600-dx-1 / https://store.nanga.jp/products/aurora-tex-light-750-dx-1 / https://store.nanga.jp/products/udd-bag-450dx / https://store.nanga.jp/products/udd-bag-630dx-1
- NANGA UDDの素材説明: https://store.nanga.jp/blogs/news/what-udd-bag
- NANGA 修理条件: https://nanga.jp/after-care/sleeping-bag/ / https://store.nanga.jp/pages/after-careについて
- LOGOS72602010: https://www.logos.ne.jp/products/info/3614
- Coleman2000034775: https://ec.coleman.co.jp/category/240/2000034775.html
- Coleman 春秋の選び方: https://ec.coleman.co.jp/category/206_13/
- モンベル1121424: https://webshop.montbell.jp/goods/disp.php?product_id=1121424
- NITE 電気毛布等: https://www.nite.go.jp/jiko/chuikanki/mailmagazin/2025fy/vol493_260127.html
- NITE 低温やけど: https://www.nite.go.jp/jiko/chuikanki/mailmagazin/2023fy/vol441_231128.html
- NITE 燃焼器具: https://www.nite.go.jp/jiko/chuikanki/mailmagazin/2022fy/vol423_230228.html

メーカーの温度表示を掲載しているが、全製品を同じ試験で再測定した比較ではない。確認日は2026-09-06。NANGAでは公開ブログ本文と現在の商品欄の価格が異なる例があったため、記事には固定価格や差額を掲載しない。販売終了・現行品との完全な同一仕様・在庫ありを推測で断定しない。

## 確認した動作

- 3つの本番URLを再読み込みし、タイトルと検索説明文の原稿一致を確認。
- 各記事の本文FAQ4問がFAQPageへ反映されていることを確認。既存FAQ抽出関数でも原稿を検証。
- 全記事に冒頭のPR表示。比較表は2～3列。旧商品トークンの露出なし。
- 購入リンクのhref・広告用rel・商品ID属性を確認。600DX/750DXは台帳ID、台帳と販売先が異なるリンクはモールの商品キーを利用する。全リンクが台帳の商品名へ統合されたとは扱わない。
- 内部リンクの参照先slugを照合。冬用記事のデスクトップ表示で横方向のページはみ出し・本文リンクの空ラベルなしを確認。
- `public-verification.json` に公開ページから読み取った結果を保存。

## 確認の範囲と残る作業

- 公開ページの購入先URLを検証したが、全販売店の在庫・決済画面の動作を保証するものではない。Colemanの楽天販売ページでは品番を再確認。既存のMOONLOID・LOGOS楽天リンクは参照が失敗し、この時点で販売ページ内容の再確認はできていない。取得失敗をリンク切れと断定していない。
- スマートフォン実機の操作確認、GA4画面での商品別集計、公開後の検索・報酬への効果は未確認。
- 他記事および商品台帳にある仕様・評価・口コミを全件監査したものではない。特に旧商品説明の温度や保証の断定は別途点検が必要。
- `before/`は変更前の公開本文と選択商品名を保持する。訂正した誤記を含むため、そのまま再公開しない。
- 個別アクセス・検索・注文・報酬の生データは保存しない。Xへの投稿操作は行っていない。
