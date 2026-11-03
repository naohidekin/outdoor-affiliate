---
name: camp-writing
description: Camp Gear Labの記事本文を既存Claude執筆フローで作成・修正し、Gemini校正と上位最終審査へ渡す。未確認体験や購入先を捏造しない。
---

# camp-writing — 執筆・修正

> 実装・配備・実通信の確認結果は `../../../docs/editorial-pipeline.md` を正本とする。スキルの存在だけで稼働・承認・公開済みとは判断しない。

## 正本と品質基準

最初にルートの `CLAUDE.md`、`docs/writing-style.md`、`docs/author-gear.md` を実読取する。
ギア男の文体・装備・実体験はこれらを正本とし、装備の現状は装備マスターの根拠を確認する。
ルート `SKILL.md` の WISE + Supervisor 11項目×10点、合格7.5、形式別字数、
内部記事リンク2〜3、FAQ3〜5を維持する。publisher旧機械ゲートの数値も変更しない。
`docs/writing-style.md` のテンプレートにタイトル行があっても、本文contentにはH1を入れない。

## 入力と執筆仕様

記事本文の前に、次の全項目を持つ確定した執筆仕様（brief）を作る。

- `purpose` 目的、`reader` 読者、`conclusion` 結論、`headings` 見出し構成
- `facts` 確定事実と根拠、`numbers` 確定数値、`links` リンク
- `requiredExpressions` 必須表現、`protected` 禁止変更事項
- `style` 文体、`length` 文字量、`cta` CTA、`format` 出力形式
- `externalSafe: true` 公開可能な入力へ整理済みであること（現modelsの必須項目）

事実・数値・使用体験は出典と確認範囲を記録する。確定項目のない配列は空にし、埋めるために作らない。
調査・構成・結論・事実制約は上位モデルが確定する。所有していることだけで使用年数、
失敗、感情、購入経緯、家族の反応を創作しない。正本や本人確認にない体験は書けない。
一次体験が足りなければ確認を求めるか、未使用・調査記事と明示して上位審査に戻す。
「実体験が必要」という品質条件を、体験捏造で満たさない。

## フロー

1. **執筆仕様を確定**し、根拠・画像・購入先とともに記事bundleに結び付ける。
2. **既存Claude執筆フローで本文作成・修正**。既定の執筆モデルを変えない。
   本文はH2から。商品/比較/ランキングshortcodeのIDは記事productIdsと実在商品に一致させ、
   タイトル「◯選」と選定数を合わせる。内部記事Markdownリンク2〜3、FAQ3〜5、
   現modelsのdraft条件はexcerpt20字以上、metaDescription50〜160字。ランキング/比較はcomparisonタグを入れる。
3. **Gemini 3.8 Flashで校正候補を生成**。入力は確定仕様と本文だけを必要最小限で渡す。
   患者・個人情報・機密文書は送らない。Geminiは新しい事実・数値・URL・根拠・医学的助言・
   商品条件・結論を追加変更しない。全見出し・URL（相対リンク含む）・数値・shortcode・
   商品ID・表・コード・広告表記・Markdownリンク先の内容と順序を厳密に保持する。
   元本文sourceは不変で保管し、候補candidateは別に扱い、自動置換しない。現runtimeはprivate research/artifacts配下にsource.jsonとcandidate.jsonを保存し、上位審査へ元本文も渡す。
   実行環境が使えなければ校正未実施と記録し、実行済みと主張しない。
4. **機械検証**。`scripts/editorial/quality.py` の `inspect_polish(source, candidate)` には
   本文文字列だけを渡す。保護要素の変更・追加・削除・並べ替えは差し戻す。
   `inspect_bundle(bundle)` で構造と提供メタデータを検証する。
   両関数とも入力を変更せず、`passed` は機械検証の範囲だけを表す。
5. **上位最終審査**。`camp-review` に仕様、元本文、候補、根拠、画像、商品、検証結果を渡す。
   意味・結論の同一性、事実完全性、体験の真偽、医療・法令・広告表現、品質スコアを確認する。
   本文修正が必要ならこのスキルへ戻り、校正・検証・最終審査をやり直す。
6. **Slackで記事版の本人承認**。承認対象に本文・画像・商品・リンクの版を結び付ける。
   承認後の変更は承認を無効にし再審査・再承認する。既存Slackの本文配信や本人確認受付を
   記事版の公開承認と取り違えない。exact版承認・公開接続は実装済みだが、新runtimeのmacpro preflight/稼働検証は残る。Codex backup承認も本人の明示的な記事ID・完全版指定公開指示を要する。

## 商品・画像・証跡の契約

- 各商品のimageUrlと画像metadataのproductId・URLを一致させ、main runnerがlive検査した
  `verified: true` を必要とする。quality単体ではsha256は任意だが、現publisherは承認画像のSHA-256とsizeを必須にして公開前後で再照合する。
  このモジュールはネット取得や実画像の同一性判定をしない。
- 楽天affiliateUrlは正規の `hb.afl.rakuten.co.jp`、Amazonは商品ASIN形式とtagを検査する。
  runnerは `affiliateConfig.amazonPartnerTag` に `AMAZON_PARTNER_TAG` の期待値を渡す。
  account tagをコードに固定しない。商品にasinがあればURLのASINも一致させる。
- 購入先がない場合は該当商品を記事・shortcodeから削除するか、明示NA判断を根拠付きで渡す。
  Amazonと楽天の両方が必ず存在するとは扱わず、URLや在庫を捏造しない。
  `purchaseEvidence` は `{productId, channel: amazon|rakuten|yahoo, status: NA,
  reason, checkedAt: 時差付きISO日時, reviewedBy}` の配列。NAは商品・購入先単位。
  どの購入先も有効でない商品は掲載対象から外す。YahooはURLがあれば検査し、
  `yahooAvailable: true` ならURLか明示NA証跡を必要とする。
- URLの誤記・不正scheme・localhost/private IPを拒否する。runner側でもDNS解決先、
  全リダイレクト先、取得結果を確認する。URLの文字列検証だけでは安全な接続を保証できない。
- bundleの `mandatory_evidence` は常にpendingを返す。画像live確認、アフィリエイトの到達・
  対象商品一致、実render、事実・医療・広告・意味同一性、品質とSlack承認は別途確認する。
  metadataの存在や `passed: true` を根拠に実体験・事実・公開可を自己認定しない。

## 出力

執筆仕様、元本文、校正候補、記事・商品・references・imagesを含むbundle、機械検証結果、
未確認証跡を上位審査に渡す。`references` のURLと時差付き `checkedAt` は確認記録であり、
本文の全事実を保証するものではない。未確認事項は埋めずに残す。

## 実装への引継ぎ
`scripts/editorial/models.py` / `catalog.py` / `quality.py` / `runtime.py` / `ledger.py` が現経路。
制作は単一macproの300秒tick、JST水曜09時以降、週3候補・未公開上限3。既存実体験正本と品質閾値を変えない。
品質moduleの明示NA対応と異なり、現在の自動候補抽出は楽天/Amazon URLが揃う商品を対象にする。
SNSは独立承認後のmanual post handoffまで。Telegramなし。詳細・配備結果はパイプライン文書を参照する。
