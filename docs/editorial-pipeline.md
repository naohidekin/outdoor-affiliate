# Camp Gear Lab 編集パイプライン（実装と配備状況）

## 2026-11-08 本人指定の制作日程変更

制作週は金曜〜木曜。初回は11月8日（日）に開始し、本人承認後の11月12日（木）までの公開を目標とする。次回は11月13日（金）09時JST以降、その後も毎金曜09時以降に既存tickで処理する。`productionSchedule`を設定し、初回の期間キーは11月6日、次は11月13日とする。過去の月曜キー・履歴を変更しない。各制作期間最大3候補・未公開3件上限を維持し、承認待ちによって次期制作が停止する場合は補充しない。品質基準・記事/SNS別の本人承認は変更しない。木曜までの公開は承認・品質検証の完了が条件で、期限による自動承認はしない。

報告・SEOの集計週は従来どおり月曜〜日曜。制作日程の変更で週次・月次報告の日時は変更しない。以下の水曜制作・月曜制作枠の記載は旧運用の履歴であり、この設定がある稼働先には適用しない。設定なしのテスト・旧稼働先には従来の動作を維持する。マネージャーAIの実装・自動判断接続は別工程で、日程設定だけをもって実装済みとは扱わない。

SNSのCodex本人承認は明示的な `approve-social-from-codex` 操作で記録する。通常tickはチャットのGOやモデル出力から承認を推測しない。本人の実指示、参照チャット、operator観測日時、対象版・本文hash・画像SHA・記事URL・設定されたX accountを束縛し、同版の実配信履歴・審査・記事公開証拠を照合する。Slackの操作イベントや実在不明のmessage IDは作らない。記録だけでは投稿せず、通常publisherの認証・版・画像・journal/readback検査を経る。11月8日のSOTO保留撤回指示は、当時の特定審査済み版だけに対応する移行互換ケースであり、他記事・他版への包括承認ではない。

本人はギア男のXをBufferでも管理している。Bufferへの自動接続・予約同期は未確認。今回のSOTO記事はBufferに予約していないと本人が確認した。Buffer管理という事実だけで、別システムの予約変更や削除を行わない。

### 新記事の商品訂正を含む承認

`attach-catalog-correction` は同じ未制作jobへ公開商品の元行と訂正候補行をprivate保存する。訂正候補で実根拠・画像・購入先を再検証し、Claude執筆→Gemini校正→実表示→Claude審査→Astra品質確認の後にSlackへ送る。事前の公開draftや商品更新は行わない。Slack本文に訂正前後と、同商品の既存掲載記事にも反映される範囲を表示し、記事と訂正候補全体を同じ版へ束縛する。

`catalogCorrectionsPublicationEnabled` は既定false。本人承認とこの配備スイッチの両方が有効な場合だけ `publish-corrected` へ渡す。private台帳の実承認とin-flight効果を別の読取専用helperでも照合し、公開ロック・全商品baseline・fresh xmin・画像・cache・実ページ読戻しを通す。途中停止はprivate journalを残して自動再実行を止める。同一商品の訂正が別の承認記事で全字段・timestampまで完全一致する行として既に反映された場合だけno-opとし、第三の状態は拒否する。Astra品質確認待ちを本人承認待ちとして報告しない。

## 0. 現在状態（2026-11-03 JST）

**初回3記事は本人のexact版承認を経て、2026-11-03 19:52 JSTまでにDB・cache・公開HTMLのreadbackがverifiedとなり、公開済み。記事の公開承認待ちはない。** 公開後SNS原稿も3件ともClaude生成→Gemini 3.8検証→Claude最終審査を通過し、既存Slackスレッドへの配信とreadbackがverified。GS 8.8、CB 8.6、SOTO 8.6。GSは22:58 JSTにX投稿・readback verified。SOTO/CBの2件は**記事公開とは別のSNS承認待ち**。画像カード統合 `5fef0e4` は本番サイト/macproへ配備し、23:25 JSTに有効化済み。実画像の保存・読戻しと通常tick完了を確認。GS差替案は11月4日に本人が承認し、01:03 JSTに公開OG差替えと画像照合を完了。
analyticsは実データから既存記事改善候補3件をSEO state rootの `editorial-insights/latest.json` へ出力済み。`reportsEnabled: true` のGUI試運転は21:40:50 JSTに完了。週次2026-11-02週と月次2026-10月のSlack送達・readbackがverified。旧Air Codexの`camp-gear-lab-seo` automationはPAUSEDを確認済み。通常の`com.naohide.camp-slack-review`は継続する。次のSEO施策枠は11月5日（木）で、新しい改善施策はまだ実行していない。今週の新規記事候補3枠は使用済みで、次の通常制作開始は11月11日（水）09時JST以降。
「文書のみ」「台帳/cap/承認は未実装」という旧記述は現在のコードと一致しない。
実装・ローカル試験の完了を、macpro常駐・実Slack承認・本番公開の稼働確認と同一視しない。
本番の記事承認・公開の実績と、接続試験・合成データの試験を区別する。最新検証結果は末尾を参照する。

2026-10-30時点の既存Slack本文配信・本人確認結果受付（公開許可false）は過去の確認記録。
それだけでは、新しいexact版公開承認の配備・認証・稼働を証明しない。

## 実行時の資格情報

既存プロジェクトの `docs/local-files.md` に記載された `.env.local` を読み、
Geminiだけは既存 `gemini-writing` スキル専用の `~/.codex/gemini-writing/.env` も
実行設定の `geminiEnvFile` で明示して参照する。値は読み込み元からメモリにのみ保持し、
台帳・設定・ログ・別Mac・Gitへ複製しない。秘密値を外部モデルへ渡さない。

## 1. 実装の所在と責務

以下はコード実読で確認した実装。実環境への接続成功・配備成功は第10節で別に扱う。

| モジュール（`scripts/editorial/`） | 現在の実装 |
|---|---|
| `runtime.py` | 制作、校正、機械検証、render、上位審査、draft保存、Slack配信、承認spool処理、承認版公開、SNS引継ぎを統合。端末内flock、health・attention・usageを記録 |
| `ledger.py` | private SQLite正本、JST週枠、未公開上限、版指紋、審査、記事/SNS別承認、変更時失効、未知副作用の再実行停止、Codexバックアップ承認 |
| `models.py` | Claudeによる候補選定・執筆・上位審査・SNS原稿、Gemini 3.8 Flash校正、完全brief、厳格JSON・保護データ境界・usage記録。SNS生成はnative JSON schemaの `{text,replyText}` を要求し、公開URL・verified画像・platformをローカルで結合 |
| `catalog.py` | Supabase既存商品・記事・カテゴリ・クリックの読取、公式仕様の型番照合、画像取得とSHA-256、購入先のlive照合。public DNS固定・リダイレクト再検証 |
| `quality.py` | 本文H1、商品ID/shortcode/「◯選」、内部リンク、FAQ、metaDescription、画像metadata・購入先URL・NA証跡、校正保護要素の順序/内容を機械検証 |
| `render-preview.mjs` | 隔離Nextアプリで実コンポーネントをdesktop/mobile表示、privateスクリーンショット、画像・H1・overflow・shortcode・購入CTA計測と遷移先検査 |
| `publish.mjs` | draft stage、exact版・既存商品照合、共通SEO公開ロック、CAS公開、DB/cache/public HTML readback、承認画像bytes再照合 |
| `slack.py` / `presentation.py` / `slack-api.mjs` | 既存Bot/認証受信経路を利用。Markdown本文・商品カード・購入先・FAQ・画像を読みやすく表示し、記事/SNS承認ボタンはnonceと版を内部値で拘束。Bot identityと配信内容readback、送信間隔制御、署名検証済spool受渡しを維持 |
| `analytics.py` / `reporting.py` | GSC・GA4の収集済み指標から既存記事改善候補と週次／月次報告を組み立てる。改善候補3件の出力、週次2026-11-02週と月次2026-10月のSlack送達・readbackを実証済み。期間・欠測・平均掲載順位の意味を保つ |
| `install.py` | LaunchAgent生成と任意load。`com.naohide.camp-slack-review`、300秒間隔、RunAtLoad、JST、privateログ。資格情報はコピーしない |

`runtime.py --config <host-local-config> status|preflight|tick|produce|deliver|retry|approve-from-codex|report` が入口。
`preflight` はSlack auth.testとGemini接続検査であり、全経路の稼働保証ではない。
`produce` は明示的な手動制作入口。水曜09時以降の開始条件は定期実行の `tick` が適用する。
host-local設定の `reportsEnabled: true` で報告を有効化し、`seoStateRoot` はSEO収集結果、`seoRepo` は月次の専用収集処理、`analyticsRoot` は集計snapshotの保存先を指定する。`report --kind weekly|monthly|editorial` は手動実行入口で、同期間のverified受領情報を再利用する。通常は300秒tickが期日到来後に送る。送達結果が不明な場合は自動再送せず照合する。
`install.py --config <host-local-config>` はplist準備、`--load` 付きはGUI domainへのbootstrapを伴う。
本書更新では配備・load・外部送信・公開を実行しない。

## 2. 実行主体・週枠・再開

- 新経路は**単一macpro**に統合する。Airへ公開を中継する旧計画は採用しない。
  他Macで同じrunnerを稼働させない。端末内flockを端末間排他とは扱わない。
- LaunchAgentは**300秒ごと**にtickし、ログイン後のRunAtLoadでも再開する。
  **JST水曜09時以降、その週の日曜まで**制作が可能。毎水曜09時ちょうどの実行保証ではない。
  tickの制作は1記事ずつ。週3枠は候補作成数の上限であり、週3記事の公開保証ではない。
- 報告は同じtickで**週次は月曜20時、編集状況は木曜20時、月次は毎月5日20時JST**以降に処理する。月次は前月のJST暦月を対象とする。手動`report --kind`は期日前の同期間も対象にできるが、verified済み期間を重複送信しない。11月3日に検証済みの2026-10月分を11月5日枠の受領情報とし、通常の次回月次は12月5日の2026-11月分となる。
- 週境界は**JST月曜00時**。同週の候補は最大**3**。未公開でrejected以外のjobも最大**3**で、held/errorも枠を使う。
  上限で新規制作を止め、拒否・保留・失敗を理由に無限補充しない。同一slugは既存jobを再利用する。
- 週をまたいだcandidateは同じjobで再開可能。error/held/rejectedをtickが無条件に制作し直すとは扱わない。
  修正・再開では審査/承認失効と台帳状態を確認する。明示retryは未公開・未承認・bundle未保存のerror/held/rejectedだけを同一枠candidateへ戻す。bundle保存済みなら版の照合を先に行う。
- deliveryや公開の結果がunknown/in_flightなら、自動再送・再公開せず外部結果を照合する。
  記事公開とSNS処理の成否を分離し、SNS失敗で記事の公開状態を巻き戻さない。
- `generationEnabled` / `publicationEnabled` はhost-local設定。exampleでは両方false。
  **Telegramは使わない**。configも `telegramEnabled: false`、代替通知として復活させない。

## 3. 台帳と状態ファイル

- 設定 `stateRoot` 配下の **`ledger.sqlite3` が内部台帳の唯一の正本**。JSON/CSVを別正本にしない。
  Git外のprivateディレクトリ0700、DB0600。ownerを固定し、eventsは更新/削除不可。
- jobs / requests / decisions / effects / eventsで候補、bundle、版、審査、本人承認、送達、外部副作用を追跡する。
- research、previews、deliveries、usage、health.json、attention、social-outboxは証跡・成果物・状態投影。
  usageのresponse ID/model/tokenは取得値、`actualUSD` / `actualInvoiceUsd` のnullを実費確定値とは呼ばない。
- 既存 `data/articles.json` 等とSupabaseの公開データは互換・公開境界として区別する。
  新publisherは既存商品を書き換えず、既存記事の無断上書き・全体同期も行わない。

## 4. 制作・品質の接続

1. カタログ・季節・既存記事・queuedテーマ・供給された観測から重複しない3候補を選ぶ。
   現runtimeが選定へ渡す観測は商品/記事/季節/モールクリック。未接続のGSC値や検索量を創作しない。
2. `Catalog.gather` が既存商品、公式の型番と仕様、画像、購入先を確認する。
   価格・在庫・主観評価・descriptionを仕様照合だけで確認済みとは扱わない。
   現自動候補抽出は型番/対応メーカーとimageUrl・楽天・Amazon URLを持つ商品に限定される。
   品質moduleのNA対応が、そのまま全自動候補抽出へのNA対応を意味するわけではない。
   `sourceNotices` の必須告知はメーカーの許可ドメイン内で毎回取得し、空白正規化後の正確な引用を照合する。
   取得・引用照合に失敗した場合は停止。合格時は短い引用だけを `manufacturer-notice` 根拠として保持する。
3. **執筆仕様→既存Claude執筆**。正本は `CLAUDE.md`、ルート `SKILL.md`、
   `docs/writing-style.md`、`docs/author-gear.md`。briefは目的/読者/結論/見出し/確定事実/数値/リンク/
   必須表現/禁止変更事項/文体/文字量/CTA/形式と、公開可能な入力である `externalSafe: true` を持つ。
   未確認の所有・体験・購入者レビューを捏造しない。体験が未確認なら調査記事と本文で明示する。
   執筆応答はnative JSON schemaで `{article,brief}` に限定する。検証済みproducts/references/imagesは
   モデルに再生成させずローカルで組み立てる。商品shortcodeの不足は既存商品IDだけで補い、組立後も字数・IDを検証する。
4. **Gemini 3.8 Flash**は本文校正候補だけを生成。元sourceを変更せず、見出し/URL/数値/
   shortcode/商品ID/表/code/広告表記/相対リンク先の内容・順序を `inspect_polish` で比較する。
   Geminiは新事実・医学的助言・商品条件・結論を作らず、合否を決めない。privateなresearch/artifacts配下へsource.json/candidate.jsonを分離保存し、上位審査へ元本文と編集ルールも渡す。
   現在の校正応答は編集可能な段落への `{edits:[{index,text}]}` のみ。保護要素・必須表現を含む段落は変更不可とし、
   重複index・対象外段落・新しい保護要素を拒否する。編集なしも記録し、意味の同一性は別途上位審査する。
5. `inspect_bundle` の構造検査後、実renderと**上位最終審査7.5/10以上**を通す。
   facts/images/affiliate/medical/renderの独立証跡を必要とし、モデルの「確認済み」だけで合格にしない。
   qualityが返す `mandatory_evidence` はpending。意味同一・事実完全性・実体験・医療・live/renderを自己認定しない。
   現runtimeは医療/子どもの安全に関する助言を自動選定から避け、検出時は保留する。
   editorial最終審査もnative JSON schemaで11項目のnested `criteria` を要求する。
   未丸め平均と総合scoreの低いほうが7.5以上、全必須証拠が合格、必要修正の `issues` が空の場合だけ通過する。
   非阻害の観測は `observations` に分け、承認済テーマの制約と本文・抜粋・meta・FAQの主張も審査へ渡す。
6. 審査済bundleを台帳に保存し、公開前のdraftだけをstageしてSlackへ配信する。
   本人のexact版公開承認を待って公開へ進む。

モデル既定は `models.py` のClaude執筆 `claude-opus-4-8`、404時のみ `claude-sonnet-4-6` fallback、
候補/上位審査/SNSは `claude-sonnet-4-6`、校正は `gemini-3.8-flash`。
既存の明示的なARTICLE_WRITER_MODEL / ARTICLE_WRITER_FALLBACK_MODEL / ARTICLE_REVIEW_MODEL設定は尊重する。
接続未確認をモデル実行済みと主張しない。OpenRouterはこの実装経路に含まれない。

WISE + Supervisor 11項目、合格7.5、形式別字数（ranking/comparison 5000〜8000、guide/how-to 3000〜5000、
review 2000〜3500）、内部記事リンク2〜3、FAQ3〜5は維持。
新modelsのdraft検証はexcerpt20字以上、metaDescription50〜160字も要求する。
旧publisherの6.0/2000字/FAQ2は既存経路の機械条件として残るが、新経路の上位審査の代わりにはならない。

## 5. 画像とrender

- クリーンな商品画像がある記事はeyecatchを持たせず、無い/低画質の記事だけ汎用写真を使う既存方針を維持。
  `fetch-unsplash-eyecatch.mjs` の重複回避と楽天thumbnailの扱いを参照する。
  この既存scriptが新runtimeから自動呼出しされるとは扱わない。本文の商品画像は別に必要。
- Catalogは取得画像の構造・Content-Type・bytes・SHA-256と型番ページ上の画像URLを照合する。
  qualityは商品ID/URL/`verified: true` の一致を検証する。画像内容の適切さは審査も必要。
- rendererは秘密envを継承しない隔離アプリで実ページ/実コンポーネントを使い、desktop1280px・mobile390pxで確認。
  H1が1つ、shortcode未解決なし、横はみ出しなし、画像表示、各商品/モールCTAのクリックpayload・event・遷移先を検査する。
  外部購入ページへの実ナビゲーションはabortし、live到達確認はCatalogと分担する。
  structured FAQの実表示も検証対象とし、本文側に空のFAQ見出しを作らない。実コンポーネントのFAQ表示ケースを確認する。
- スクリーンショットはprivate出力。Slackへの配信は本文/FAQと商品画像URLのimage block。
  rendererスクリーンショットをSlackへアップロードする実装とは区別する。

## 6. exact版公開承認と公開

- fingerprintはcanonical JSONのbundle全体（本文・FAQ・brief・根拠・商品・リンク・画像SHA等）を束縛する。
  内容変更時は審査・記事/SNS承認・旧requestを失効させ、校正/検証/審査/本人承認をやり直す。
- Slackは全文分割・FAQ・画像と「この版の記事公開を承認」「修正依頼」「保留」を提示する実装。
  request ID、article ID、完全manifest hash、nonce、team/app/user/channel/thread、card ts、期限を照合する。
  表示用短縮hashだけの承認ではない。既存認証受信側の署名検証済spoolを前提とする。
  過去の本人確認受付や別user・旧版カードを公開権限へ流用しない。企画の追加本人承認は必須にしない。
- `publish.mjs` は台帳側で本人認証済みの承認を受け取る境界で、任意stdinだけを本人認証とは扱わない。
  共通SEO公開ロック内でexact draft/商品を再照合し、draftのCAS更新、DB readback、cache revalidate、
  public HTMLの本文hash/H1/画像/購入リンク、公開前後の承認画像SHA/sizeを検証して初めてverifiedを返す。
- **Codex backup**: 本人の実メッセージを確認した信頼できるoperatorだけが `approve-from-codex` を使う。
  `記事 <id> 版 <完全revision> を公開してください` または `publish <id> <完全revision>` の明示指示と
  source=codex / thread_id / message_id / text証跡が必要。曖昧な「OK」やモデルの自己承認は不可。
  既存承認/公開/副作用claimとの競合を拒否し、承認記録だけを作る。公開はpublicationEnabledと通常gateを別に通す。

## 7. SNS承認とX投稿モード（自動投稿は接続復旧待ち）

- 記事公開のDB/cache/public readbackがverifiedになった後だけSNS原稿を作る。
  公開本文・画像を根拠にClaude生成→Gemini 3.8校正→上位7.5審査→**記事と別のSNS承認**。
- ClaudeのSNS生成応答はnative JSON schemaの `text` / `replyText` のみ。本文にURLを置かず、返信は正確な公開URLのみとし、加重280文字を上限とする。公開URL・verified画像・`platform=x` はローカルで組み立てる。
  告知案全体の独立fingerprintを使い、変更時はSNS再審査・再承認。
  SNS予定日時/予約を現schemaが実装しているとは書かない。
- Slackの承認表示は内部ID・hash・点数・選定理由を本文に出さず、承認ボタンの内部値には正確なrequest・nonce・版を保持する。記事側は実ページに表示する商品説明・仕様・参考価格・画像・購入先を確認可能にし、本文にあるFAQを重複させない。SNSはモードなし／`manual`の旧提案なら手動表記を維持する。`auto_x`の新提案は「Xに投稿する」を表示し、承認した本文・画像と記事リンク返信の自動投稿を承認対象とする。投稿先IDは表示しない。
- モードなし／`manual`の提案は、SNS承認後に `social-outbox/<revision>.json` へ **`approved_manual_post_pending`** を記録しSlackへ通知する。
  **自動投稿・自動予約は行わない**。本人が原稿を利用するか、Codexアプリへ投稿を別途依頼する。
  手動投稿後の外部投稿ID/readback収集までをこのrunnerが実装済みとは扱わない。
- 新しい`auto_x`モードでは、投稿モード・投稿先アカウント・本文・返信・画像を同じ提案版に拘束し、記事公開とは別の承認を保存する。旧手動カードを自動投稿の承認には流用せず、移行時は旧カードを失効して新しいカードで再承認する。
- **接続の現状（2026-11-03 JST、主担当のread-only確認結果）**：公開アカウント`@camp_gear_lab`の参照は確認済みだが、OAuth 1.0aは両ホストでHTTP401／code89となり、`socialPostingEnabled: false`を維持する。公開アカウントの参照成功は、投稿用資格情報の有効性や投稿権限の確認ではない。
  無効中の新カードは「X接続の復旧待ちです。承認した内容は保存し、接続確認後に投稿します。」と表示する。承認は接続復旧後の自動投稿の意図として保存し、即時投稿の成功を約束しない。この変更に伴う実投稿・配備・カード移行が完了したとは扱わない。
- X旧自動投稿は復活させない。新経路も承認版・投稿先・画像バイトの一致と、本文投稿・リンク返信のreadbackを確認して初めて成功と扱う。結果不明の書込は自動再送しない。
  既存投稿制限は `docs/x-post-skill.md`、`src/lib/x-post-prompts.mjs`、`scripts/post-to-x.js`、
  `data/account-config.json` を参照。不一致は保留し、古い自動承認/再稼働指示を流用しない。

## 8. スキルと正本

| 役割 | スキル/参照先 |
|---|---|
| ネタ選定→執筆 | camp-topics → camp-writing |
| 画像→審査 | camp-eyecatch → camp-review |
| 校正/最終審査・本文差戻し | camp-review → 必要ならcamp-writing |
| 公開後の告知案/手動投稿引継ぎ | camp-social |
| 文体・体験根拠・採点 | CLAUDE.md、SKILL.md、docs/writing-style.md、docs/author-gear.md、docs/sense-definition.md |

各スキルは実装と運用上の役割を案内する。スキル文書そのものが常駐実行主体ではない。
プロフィール文例は体験証拠にしない。購入先欠落は商品削除か商品/モール単位の明示NA証跡で扱い、URLを捏造しない。
外部モデルへ渡すのは公開可能なrepo資料と検証済公開データだけ。機微Context/患者/認証情報は渡さない。

## 9. 検証結果と限界

| 検証 | 結果・根拠 |
|---|---|
| 全Python試験 | macpro runtime `05c4c3e` で211件成功。別途collector試験5件成功。実送達は別行のreadbackで確認 |
| 最新の限定試験 | `test_slack.py` 19件、`test_analytics.py` 18件、`test_models.py` 48件、`test_reporting.py` 11件、`test_runtime.py` 23件成功。各変更時点のローカル結果であり、配備後の実送達ではない |
| macproのpublish試験 | 22件成功。空201・readback必須・added_at暦日を含む |
| 先行するmacpro実render検証 | 33件成功、skip 0。この結果は今回のSlack修正後の再実行結果ではない |
| 新runtime GUI preflight | Slack認証・Gemini 3.8 Flash実呼出し成功 |
| 実商品素材 | 5商品・仕様41項目・購入先10件（楽天/Amazon）と公式掲載画像を実接続で確認。価格・在庫・全記事主張の包括認証ではない |
| 初回3記事とSNS | 記事は本人のexact版承認後、19:52 JSTまでに3件とも公開readback verified。SNSはGS 8.8、CB 8.6、SOTO 8.6で、3件ともGemini検証・独立審査・Slack配信readback verified。SNS承認待ちで、X投稿・予約なし |
| 定期報告のGUI試運転 | `reportsEnabled: true` で21:40:50 JST完了。週次2026-11-02週と月次2026-10月のSlack送達・readback verified。旧Air Codex automationはPAUSED、macproの通常SlackレビューLaunchAgentは継続 |

実装・ローカル試験は完了している。Pythonのcatalog/ledger/models/quality/runtime/slack試験、
Nodeのpublish/render契約試験とmacpro実render、GUI Slack単体認証は、新runtime preflight・常駐・本番公開とは別の検証。

```sh
python3 -B -m unittest discover -s scripts/editorial -p 'test_*.py'
node --test scripts/editorial/test-publish.mjs scripts/editorial/test-render-preview.mjs
```

実render統合ケースは `RUN_RENDER_TESTS=1` で有効化する（Node20/24、Playwright/Chromiumが必要）。
通常のNode契約試験でskipされた場合、それを実render成功件数に数えない。
ローカル試験の完了は、新パイプラインのlive稼働や全ての実商品/外部サービスの検証完了を意味しない。

## 10. 配備記録（2026-11-03 JST）

以下は時系列の記録。途中の停止・候補段階の記述を現在状態として扱わず、末尾の完了記録と第0節を参照する。

- macpro専用checkoutへ配備。資格情報は既存の明示パスからのみ参照し、複製していない。
- GUI実行で新runtimeのSlack Bot認証とGemini 3.8 Flash校正・保護検査が成功。
- 接続確認メッセージを既存Campスレッドへ送り、Slack APIから読み戻した本文の一致を確認。本人の既読は未確認。
- 13:44 JST、同じ `com.naohide.camp-slack-review` を新runnerへ切替。初回tickはexit0、300秒間隔。
  この時点は制作・公開flagsともfalse。旧plistはprivate rollbackへ保管した。
- 実装版 `bcba319`：macproでPython111件・公開/render31件すべて成功（実renderを含む、skipなし）。
  SSH試験ではNodeのPATH不足を確認し、本番LaunchAgentと同じPATHで再実行して通過した。
- 最終検証後、macproの新generation/publication flagsをtrueにし、旧SEO adapterのeditorial_enabledをfalseに変更。
  SEOの計測・施策枠は維持。Telegramはfalseのまま。公開flagは本人のexact版承認を免除するものではない。
- 初回の実候補選定と1本目の素材検証をGUIの単発実行で開始。通常は水曜09時JST以降に週3枠を処理する。
- この時点では承認済み実記事の公開はまだ実行していなかった。後続の公開結果は末尾に記録する。
- 実商品カタログでは仕様・画像の同一性・購入先が未確認の候補を観測。3枠の設定を3原稿完成と報告しない。
- SNSは公開確認後の原稿生成・独立審査・別承認・手動投稿引継ぎまで。X投稿や予約を済ませたとは報告しない。
- 初回3候補のうち1件は素材・仕様・購入先の未検証で本文制作前に停止、2件は候補段階。
  タイトルの未実施「実測」等と累計クリックからの購入・季節需要の推測を除去し、同じ候補IDで履歴を残して訂正。
- 楽天APIは新旧エンドポイントともHTTP403、診断はIP許可エラー。現在設定はWeb用アプリ、別途既存のバッチ用アプリが登録済み。
  バッチ用の既存資格情報・接続元許可の整合確認が残る。API復旧だけで商品仕様等を合格扱いしない。
- 上記楽天の接続問題は同日後続作業で復旧。Airの対象プロジェクト指定ファイルで既存バッチ用設定を発見し、
  本人の明示承認後、現在の接続元1IPのみ許可追加・macproの同プロジェクト設定へ反映。
  macproの実際のCatalog通信経路で商品検索成功・結果1件取得。キーの新規発行・表示・Git保存はなし。
  同じ初回候補ID・週枠で素材検証を再実行し、API復旧と記事品質合格を分けて判定する。
- Slackが `&` をHTMLエスケープする差異を修正。送信直後のmessage_tsをprivate受領情報へ保存し、
  読み戻し失敗時に盲目的な再送をしない。14:11 JST、先の制作停止案内は既存メッセージと一致し受領情報を修復。
- 同日後続作業で初回候補の5商品を修復。型番・仕様41項目、公式掲載画像、楽天・Amazonの到達商品を実接続で確認。
  GS-600KHの誤った重量・口数、ST-310の重量、SOD-310の他社燃料互換などの旧データを除去。変更前後と出典はprivate repair受領情報へ保存。
- `sourceHints` は商品IDごとの公式URL候補。毎回取得し、メーカー別の主製品仕様欄と正確な型番・仕様値を照合する。
  十分な公式根拠が得られた場合のみ追加検索を省略し、画像バイナリ・購入先・アフィリエイト設定の検査は省略しない。
- SOD-310は生産終了・在庫限りと後継型番を記事へ明示する。公表火力・使用時間は指定燃料と測定条件を保持し、実使用実績と混同しない。
- 実装版 `09f3932`：Air・macproでPython128件成功。仕様照合のDOM範囲と長文応答の待機時間を独立レビュー済み。
  最初の長文生成要求は60秒後に応答取得失敗。利用量は未取得で費用ゼロとは扱わない。共通180秒期限内で待つよう修正し同一候補IDで再開。
- 初回原稿の未確認体験談、収納寸法の逆転、公称火力から冬季性能への外挿、未確認の価格・在庫評価をAstraが修正。
  GS-600KH／SOD-310対SOD-320／ST-310・US-1900の既存3テーマ・同一週枠を維持し、修正sourceから校正・検証・実render・独立審査へ進めた。
  SOD-310の生産終了・在庫限り・後継SOD-311GS、ST-310の25℃～5℃というメーカー説明は必須引用照合で束縛する。
  温度説明を安全な最低使用温度や当サイトの実測結果へ置き換えない。
- native JSON執筆応答、段落単位のGemini校正、FAQの実renderを接続。最終審査のflat採点応答は通過させず、
  nested schemaへ修正し、独立証拠と11項目の未丸め平均による判定を維持した。
- GSのdraft stageでは、`return=minimal` の空201をJSON解析してunknownとなる境界を確認。
  insertだけ空201を受け入れるよう修正し、DBの完全一致readbackは必須のまま維持。
  unknownを未挿入と決めつけず、既存DB状態・revisionを照合して復旧した。GET/CASの空201は成功扱いにしない。
- SOD-320の商品 `added_at` は既存TEXT列の `2026-04-22`。有効な暦日をこのフィールドだけ保持する修正を実施。
  他のcreated/updated/published日時のタイムゾーン要件や、商品の完全一致readbackは緩めていない。
- Slack本文の読戻しでは `&` → `&amp;`、`>` → `&gt;` の差異を確認。
  読戻し側の `plain_text.text` のみ1回デコードし、ボタン値・nonce・URLは完全一致を維持した。
  画像ブロックはURL・alt_textが一致し、サーバー追加のimage_bytes/image_height/fallback/is_animated/image_widthだけが差分だった。
  読戻し側の `type=image` に限りこの5項目を比較から除外し、画像URL・alt_text・type・未知項目の変更は拒否する。
  既送信分はprivate outbound receiptと実読戻しを照合して再利用し、同じ本文・画像の盲目的な再送はしていない。
- runtime `bce2d8c`：初回3記事の本文・FAQ・商品・画像・購入導線・表示の確認と、Slack本文／画像／承認カードのreadbackが完了。
  GSは17:11:33 JST（score 8.090909）、SOTOは17:11:43 JST（8.090909）、CBは17:11:53 JST（8.0）に配信完了。
  これは公開前の履歴。3件ともその後のexact版承認に基づき19:52 JSTまでに公開readback verifiedとなった。
  定期運用は単一macpro・300秒tick・水曜09時JST以降の週3候補上限／未公開3件上限を維持し、承認待ちによる上限を無視して補充しない。
- 旧SEO editorial bridgeはhost-local設定で無効。SEO側の新promptは新記事制作・SNS承認をSlack-first runtimeへ委ね、analytics改善入力は鮮度・欠測を確認して既存記事改善に使う指示へ更新。週次／月次レポートの配備・実送達は別途証拠を確認する。
- runtime `a5490e8`：公開済み3記事を根拠にしたSNS原稿がClaude→Gemini 3.8→Claudeを通過。GS 8.8、CB 8.6、SOTO 8.6で、3件とも既存Slackスレッドへの配信とreadbackがverified。記事は再承認待ちに戻していない。SNSだけ本人の別承認待ちで、X投稿・予約なし。macproでPython196件・collector5件成功。
- analyticsの実データで既存記事改善候補3件を `editorial-insights/latest.json` へ出力。これは新記事の候補追加やSEO改善の成果ではない。この時点では週次／月次report機能は設定falseで、本文の完成・実送達は未確認だった。今週の候補3枠は使用済み、次の通常制作は11月11日（水）09時JST以降。
- runtime `05c4c3e` をmacproへ配備し、Python211件・collector5件成功。host-local `reportsEnabled` をtrueにしてGUI試運転を完了（21:40:50 JST）。週次2026-11-02週と月次2026-10月のSlack送達・readbackはそれぞれverified。旧Air Codex `camp-gear-lab-seo` automationはPAUSEDを確認し、通常の`com.naohide.camp-slack-review`は継続。月次2026-10月分は11月5日枠として送達済みなので、通常の次回月次は12月5日の2026-11月分。次のSEO施策枠は11月5日（木）で、新しい改善施策の実行実績はまだない。X投稿は引き続き本人承認後の手動引継ぎのみ。

## 2026-11-03 22:12 JST — X rollout

- Air/macpro runtime e0c8fa4: Python244件・Node4件成功。独立レビュー指摘を修正済み。
- 3件は本文・画像・元の品質審査を保持してauto_xへ移行。旧承認カードは失効。新カードの配信/readback verified: GS 1793711508.457169、SOTO 1793711516.843559、CB 1793711526.132759。全件social_review・未承認・未投稿。
- @camp_gear_lab / 1343879420470206464の公開情報を確認。OAuth1は両機401（v1 code89）、本人は管理場所不明。22:12の読取専用preflightも未成功。private social-connection.jsonに記録。
- socialPostingEnabled=falseを維持。カードは接続復旧待ちと、承認内容を保存し接続確認後に投稿する旨を明示。認証復旧・対象アカウントpreflight成功・有効化後、別途承認された版の本文と画像、記事URL返信を投稿し、X照合後にSlackへ結果を通知する。
- 実X投稿・実投稿readbackは未実施。契約同意・キー再発行なし。開発者アカウント確認と投稿認証の復旧が残る。旧投稿ジョブは無効のまま。通常runnerは22:12:07 completed、報告の重複送信なし。

## 2026-11-03 22:55 JST — X認証復旧・承認待ち

- 本人がOAuth1アクセストークンとコンシューマーキーの各ペアを再生成し、既存envへ安全入力で保存。22:55:17と22:55:43にusers/meが成功、対象userId1343879420470206464と一致。socialPostingEnabled=trueへ変更。新規契約・権限追加なし。
- 通常runnerは22:55:57 completed、SNS3件はsocial_review・承認nullで投稿ゼロ。実投稿確認はSlackのexact版承認待ち。接続復旧案内を既存Slackスレッドへ送信（1793714169.751269）。カードの復旧待ち文言はこの案内で解消を通知、承認版は変更していない。

## 2026-11-03 22:58 JST — 初回X実投稿確認

- GS-600のSNS新カードへの本人承認を22:58:15に受信。承認版9bb140c3ecd1dd57df987196d33d642e84fd6a1762c3270925cb5c3e151f28a1の本文と画像1枚を投稿し、記事URLを返信。main https://x.com/i/web/status/2117617369673830497 、reply https://x.com/i/web/status/2117617376552493429 。
- 本文、承認画像bytes/SHAとアップロード後添付mediaKey、返信URL/親ID/対象アカウントが一致。journal verified・pendingなし、ledger social_posted。Slack完了通知1793714302.385899もreadback verified、health22:58:23 completed。
- SOTO/CBの2件は未承認・未投稿。socialPostingEnabled=true、今後も本人のexact版承認後だけ投稿する。X認証復旧と初回の実投稿・照合まで確認済み。

## 画像カード統合（2026-11-03 JST、配備受領は以下末尾）

- `socialCardsEnabled` は省略時も設定例もfalse。有効時だけ、本文polish後・品質検査/render/最終審査/Slack承認前に `SocialCards(config, env, catalog).build(bundle)` を実行。確認済み商品画像を再取得し、SHA-256一致を確認して1200×630 PNGへ合成する。画像生成モデルや架空の使用写真は使用しない。
- `article.generationMeta.socialCard` にURL・SHA-256・size・contentType・寸法・templateVersion・元商品画像のSHA-256を保持し、`bundle.images` の `role: social-card` と一致させる。カードを含むbundle全体が審査・承認の版指紋に入る。生成・保存・readbackの失敗で止め、旧画像や空画像へ自動fallbackしない。
- 保存先は専用公開bucket `editorial-social-cards`。既存Supabase設定をメモリ内だけで使用し、SHA-256から決まるpathへupsertなしで保存。bucket作成は明示setupのみで、制作中には作らない。保存後は公開画像bytesを照合する。main報告ではbucket setupとGS画像build/readbackが成功済み。本統合の配備・有効化完了は別途記録する。
- Nextのファイル型画像は明示metadataより優先されるため、旧画像を同URLの通常 `opengraph-image/route.ts` へ移す。新カードのOG/Twitterタグは保存済みURLを指定し、カードのない既存記事は従来デザインへ向ける。未公開記事の画像ルートはDraft Mode以外404。本文Hero/eyecatchは変更しない。
- publisherは承認画像bytesの再照合に加え、OG/Twitterタグが各一つだけでカードURLと完全一致することを確認し、readbackにmanifestを返す。SNS生成はその証跡を要求し、最終SNS審査前に画像をカード一枚へローカルで固定する。記事とSNSの別承認は維持する。
- 公開済みGSのbundle/DB/X投稿、保留中SOTO/CBの承認は変更しない。GS改善画像は別の確認用プレビューとし、公開OG差替えには独立した画像承認と明示apply経路を別途定める。再投稿や既存承認への暗黙反映は行わない。
- 当担当の確認: runtime35件、publish24件、metadata helper2件成功、型検査とNext production build成功。隔離したHEADでも暖房記事の既存medical2失敗とproducts正規化1失敗を再現した。mainがproductsを既存手順で正規化中。新統合の本番配備・実Slack/公開ページ確認はmainの最新受領記録で追記する。

### 配備受領（2026-11-03 23:26 JST）
- 実装 `5fef0e4` をGitHub main/作業branchとmacproへ同期。Vercel production `dpl_9FVD9hKeTX2yKGjXpsRPNkbbDA6g` READY、camp-gear-lab.comへalias済み。GS公開HTMLのOG/Twitter各1件と従来PNGの1200×630・HTTP200を確認。
- macpro Python253件・画像/保存/公開Node37件成功。Airも型検査・build・metadata2件成功。products正規化は内容不変で修正、既存暖房記事のmedical2失敗は未解消。本変更による失敗ではない。
- macproの実GS生成→専用bucket保存→公開GET一致を確認。SHA `6f5282dd3f4e2fda8d653e16efbd403abd2af206eecdc9f294bd1ddeb056791c`、94952bytes。再生成も同一bytes、既存オブジェクトの照合成功。元のledger/公開記事/X投稿は不変。生成環境間のフォント差は許容し、承認後は保存済みbytesを固定する。
- `socialCardsEnabled=true` を既存private configへ設定。health23:25:58 completed、GS social_posted・SOTO/CB social_reviewを維持。新カードを使う将来の記事の本人承認・実公開・X実投稿はまだ実施していない。今回GSは差し替え確認案であり、公開反映は未承認。
- Airの元checkout `claude/camp-gear-lab-review-n1n3e9` は既存 `data/kill-switch.json` 未コミット差分によりpull停止。stash/破棄せず保持。今回の実装checkoutとmacpro、GitHubは同期済み。

### GS公開画像の本人承認・差替え（2026-11-04 JST）
- 本人がCodexで前掲画像を明示承認。専用operator `replace-gs-social-card.mjs` が承認SHAを固定し、共有公開lock内でgeneration_meta.socialCardとupdated_atだけをCAS更新。元の本文・商品・購入先・旧ledger/X投稿は不変。
- 01:02:56更新、01:03:02にprivate repair receipt complete。通常UA/Twitterbot双方でOG/Twitter画像URL一致、公開PNGのSHA6f5282dd3f4e2fda8d653e16efbd403abd2af206eecdc9f294bd1ddeb056791c・94952bytes一致。旧版指紋は履歴として残し、今回の承認は別receiptへ記録。
- 実装d038b6cを両機/mainへ同期、型検査/build・専用7テスト成功。本番dpl_5Xpb6cHfkH4A9H3HzwnyDaAsifgo READY。旧opengraph-image URLも307で保存画像へ転送し、最終bytes一致を確認。X上の既存投稿表示を実見した確認とは区別する。
- 引継ぎ文書は原文/patchを非公開バックアップし、既存追記を全保持して7957bb47で両機/origin同期。対象2文書のSHA一致と未コミット差分なしを確認。

### SOTO/CBのSNS専用画像更新（2026-11-04 20:40 JST）
- 商品写真カードv2で日本語見出しの語途中改行を修正。SOTO SHA `82806852ad1a04ed8d2dea031ffefbae9613afa38a25de5de83f4508689651b6`、CB SHA `3f5d2de1f16638c691cd965b6f87ed0f0e47332d364344a004458422ef8b7a0b`。1200×630 PNGの保存GET・元画像SHA・目視確認済み。
- `hold-social-refresh` → `refresh-social-images` は公開済み記事bundle/publicationを変えず、元記事版・商品画像SHAに結び付けたSNS専用manifestを保存する。本文・返信が完全不変の場合だけ既存Gemini校正を明示的に引継ぎ、Claudeによる新版審査は再実行。今回Sonnet4.6の審査はSOTO8.8/CB8.7で合格。記事OGは今回変更していない。
- SOTO旧版は11/4 13:37の本人Slack承認後、main `2117838625681641686` が投稿済みだった。Xが同一末尾URLを2画像分返す場合の厳密照合を修正。旧approval/journal/main readbackをsocialHistoryへ保持し、旧journalは変更せず、旧返信も作らない。新カードに「旧画像版は投稿済み。今回の承認で新画像版を新規投稿します。」と旧投稿URLを表示する。
- 旧承認ボタンを無効化。新版revisionはSOTO `732c338b9c0cab5b9b5eaa6e591e26555f67b1b1846f6fd3918c5f21ef5fb24c`、CB `4f123a6126e5393634619295ff2750e32109e66e57036e07b4c9191ca061a631`。両件social_review・新承認なし・新画像未投稿。
- Slackの本文/画像/ボタンを各3通readback verified。SOTOカード `1793792407.861649`、CBカード `1793792414.620029`（channel C0C7LG1TQUC）。SSHはKeychain exit36でAPI送信前に失敗したため原記録を保持し、通常GUI launchd経路で配送成功。今後もSlack送信は通常runner経路を使う。socialPostingEnabled=true復帰、health20:40:16 completed。
- 実装 `e63123e` をAir/macpro/origin作業branch同期。Python278件が両機で成功、Node画像9件成功、独立レビュー完了。新画像の実X投稿は今後の本人承認後に別確認する。

### 公開後の自動最終確認（2026-11-04、配備受領は後記）
- 本人依頼により、今後の公開記事で承認本文・画像表示/元画像SHA・PC/スマホ表示・楽天/Amazon購入ボタンと接続先の商品同一性を自動確認する。購入や記事/SNSの承認は行わない。
- 確認結果は記事版ごとに非公開receiptへ保存。問題または確認不能があれば既存Slackへ通知し、同じ結果で繰り返し通知しない。送達不明は盲目的に再送しない。
- 承認済み公開記事とSNSは別管理のまま。SOTO新画像版のX投稿は本人指示によるsocial_heldを維持する。
- 配備: `34e3eb2` をAir/macpro/originへ同期。設定 `postPublicationAuditEnabled=true`、開始点2026-11-04 22:59:58 JST以後の公開記事が対象。今週3件だけ明示的に遡及確認。既存300秒runnerで1回につき最大1記事、失敗/確認不能は30分間隔・最大3回。送達不明は要照合として自動再送しない。Python316件が両機で成功、ブラウザ6件成功、Astraの最終レビューPASS。
- 実行確認: 通常GUI runnerでGS 23:01:05（42項目）、CB 23:02:19（54項目）にsuccess。SOTOも23:03:19までに64項目success、health completed。3件すべて通知不要（not_needed）。Slackの正常通知は送らず、記事/SNS承認権限・SOTO social_heldは変更していない。

## 既存3記事のprivate改訂ワークフロー（コード追加・未配備）

2026-11-08時点ではコード・offline試験の確認段階。3記事の改訂本文完成、job投入、実制作、Slack配信・本人承認・公開完了を示すものではない。
Main/Astraの実配備先読取確認によると、共有receiverアプリは `~/Library/Application Support/codex-slack-receiver/app`。
`notification_review_bridge.mjs:52` のarticle_id検査は `/^[A-Za-z0-9_-]{1,100}$/` で、`revision-<24桁hex>` を受理する。
既存のCAMPスレッド・署名検証・32桁nonce・`camp-<24桁hex>` request ID・64桁manifestの拘束を維持し、transport変更は不要。
これはreceiverの静的な互換確認であり、実改訂の承認試験ではない。テスト承認や追加Slack投稿は送っていない。

対象は `article-024/firepit-beginner-guide` → `article-005/single-burner-ranking` →
`article-002/landlock-vs-landnest-shelter` の固定順。記事・商品DBへの反映はexact版の本人承認後だけ。
新記事の週3枠・未公開3件上限には改訂jobを算入しない。改訂承認待ちで翌週の新記事制作を停止しない。
SOTOの既存job・SNS保留を変更せず、改訂公開後もSNS生成へ自動遷移しない。

private JSON入力（`--evidence-file`）は `{"revisions": [spec, ...]}`、1〜3件。
各specの必須項目：

- `baseArticle`: `Catalog.catalog()` の完全なcamelCase記事snapshot。既存ID/slug/status/日時を保持。
- `changeSummary`: Slackへ表示する短い変更概要。
- `editorialCorrectionInstructions`: 確定した編集仕様。旧本文は事実根拠ではない。未確認の医療・子どもの安全・体験談は削除し、出典確認済みメーカー使用注意だけを扱う。現行medical gateを維持する。
- `verifiedAuthorFacts`: 公開可能な確認済み著者体験の原文文字列。空配列なら旧本文から体験を推定しない。
- `targetProductIds`: 改訂で扱う既存商品IDの正確な順序。1〜20件、元記事のIDの部分集合。
- `productRemovalReasons`: 省いた全IDと各理由。アクセサリーや無関係な電源を黙って省かない。掲載数・タイトル数は現行品質検査で一致させる。
- `baseProducts`: 選択IDの順序で並べた `Catalog.catalog()` の完全な商品snapshot。
- `candidateProducts`: 同じ順序・同じキー構成の完全な訂正候補。変更可能なのは `name, brand, specs, imageUrl, affiliateUrl, amazonUrl, price, description, rating, availability, updatedAt`。変更時は新しいtimezone-aware `updatedAt` を含める。ID/category等は不変。 `yahooUrl` は任意導線の除去として空文字へ変更する場合だけ許容し、追加・非空URLへの変更・null化は拒否する。Yahoo除去はchangeSummaryにも短く追記し、Slackに「Yahooの導線：非表示（商品同一性未確認の検索リンクを外す）」を表示する。候補の楽天/Amazon購入先は通常どおり検証し、品質gateは緩和しない。

基準記事hash、商品ごとの基準hash/候補hashと差分 `productPatches` は内部で計算する。手入力しない。
別名 `productOverrides` やsnapshot外のパッチは受け付けない。`sourceHints` / メーカーadapterによる通常の
型番・全仕様・画像bytes・購入先の照合を各候補商品へ実行し、未確認なら停止する。入力された訂正候補自体を根拠として合格扱いしない。

実行入口（以下は手順の記載のみ。この追記では実行していない）：

```sh
python3 scripts/editorial/runtime.py --config /absolute/private/config.json request-revisions --evidence-file /absolute/private/input.json
python3 scripts/editorial/runtime.py --config /absolute/private/config.json produce-revisions
```

`request-revisions` は現在の基準記事・商品をGETで照合し、private台帳に `revision-…` jobを作る。
`produce-revisions` は固定順の未処理jobを最大1件だけ制作し、通常の新記事 `produce` は呼ばない。
通常GUI LaunchAgentの300秒 `tick` も最大1件の要求済み改訂を処理する。制作に使ったtickだけ新記事制作を次回へ回す。
候補はClaude執筆→Gemini 3.8 Flash校正→構造/事実/画像/購入先/medical/render/上位最終審査を通す。
旧本文35k字等は現行format字数規定を上書きしない。photo-cardは同じ生成・検査を使い、他のgenerationMetaを保持する。
公開DBにdraftを作らず、候補・source・render・reviewをprivate保存する。改訂はさらにAstraが実際の本文・FAQ・画像・購入先の根拠を確認し、対象版のfingerprintと証拠を束縛した品質審査を記録してから、既存Slack本文/画像/承認カードへ配信する。品質審査は本人の公開承認と別で、未実施・旧版の審査では配信しない。候補を変更した場合は品質審査も再実施する。
商品修正があれば変更した項目名と提案後の値を表示する。仕様はカードの先頭3項目だけに省略せず、提案後の全項目を確認できるようにする。旧値や生の購入先URLは列挙せず、購入先は本文のクリック可能な候補リンクで確認する。旧新URLや全仕様の差分はprivate保存し、承認カードに一度だけ「商品カードの修正は、この商品を掲載する他の記事にも反映されます」を表示する。
「更新を公開する」ボタンの本人承認が記事と商品候補全体のexact fingerprintを拘束する。

`publish-revision` は新記事publisherと分岐した `revision-publisher.mjs` を使う。共有publication lock内で
記事と全基準商品を再読し、全件不変を確認してから、承認済み商品差分を、全商品を基準照合したGETで同時に取得した短命の `xmin` row-versionと `id/updated_at/category_id` のCASで順に反映する。
全商品を候補と完全照合してから記事を再GETし、全基準フィールドの一致と新たな `xmin` を確認して `xmin/id/slug/published/updated_at/created_at/published_at` CASで反映する。
記事のidentity/status/初回公開日時/作成日時は不変。影響する公開記事のcacheも再検証し、DB・公開HTML・画像のreadback成功後だけ完了とする。
`xmin` は同じupdated_atを保つ他writerの更新でも変化するため、timestamp更新の協調は前提にしない。提案の長期IDには使わず、公開直前のGET/CAS間だけに使用し、semantic readbackでは除外する。DB schema/RPC追加はない。

商品更新と記事更新は複数リクエストであり、DB transactionではない。途中失敗・結果不明では自動再送/rollbackしない。
private effect journalと共有publication markerを残し、すでに反映された商品・未反映記事・cacheをAstra/人が照合する。
制作中断も自動再発注せず要照合。既存改訂要求を別specで上書きせず、古いボタン・不明effectを無効化した明示的な復旧を要する。
公開後監査は改訂jobと公開記事の別IDを保持し、完全に束縛された改訂だけ商品20件まで許容する（通常記事の上限は維持）。

改訂のモデル入力には、旧記事の本文・抜粋・FAQを含めない。`existingArticle` はtitle/slug/categoryId/productIdsだけ、
関連記事もid/title/slug/categoryIdだけを渡し、旧タイトルを事実根拠にしない。元の完全な記事snapshotはprivate台帳とCASに保持する。
確認済み著者文は執筆指示の冒頭に原文を置き、本文・protectedの両方で完全な文として保持する。言い換えの自動補完はしない。

写真カードは40pxでも収まらない長い句だけ折り返しを許可する。全文・画像SHA・領域の検査を維持し、折り返しても収まらなければ停止する。
No.683040の公式写真は、同一性確認済みarticleの主ギャラリーに限ってsrc/srcsetを照合する。隣接商品・nav・aside・異なる型番は採用しない。

### 改訂候補と既存の「医師から一言」の表示文脈

3対象の既存テンプレートは、まとめ・関連記事・FAQの最初の該当見出し直前、該当なしなら本文末尾に
`MedicalAdvice` を表示する。この安全情報やサイトテンプレートは改訂処理で変更しない。
private previewのdesktop/mobileの実DOMから、`main article #article-reading-content` 内の一意で可視の
advice aside（免責文を含む）を取得する。両viewportの内容一致、可視テキストとDOM内の全テキストの一致を要求する。
`inheritedPresentationContext` としてDOM、canonical DOM SHA-256、表示文字列、固定3ファイル
（article page / MedicalAdvice component / medicalAdviceData）の実bytes SHA-256をcandidateに保存し、
最終review・台帳保存・exact owner approvalのfingerprintへ含める。テンプレートのcopyと実repoがrender中に変われば停止する。

Slackはこの同じ表示文字列を一度だけ「既存の『医師から一言』（変更なし・今回の再検証対象外）」として表示する。
生成・校正する記事本文へ既存clinical文をコピーしてmedical gateを迂回しない。既存のcandidate title/body/FAQの
medical gateは不変で、最終reviewは候補と既存adviceの矛盾も審査する。一方、既存clinical内容の再検証は実施したと扱わず、
`medicalScope=candidate_article_only` / `inheritedClinicalReverified=false` をreview receiptに記録する。

公開時は、最初の公開mutationより前にローカルの固定template bytesと現在の公開HTMLから抽出した同asideのDOMを照合する。
商品CAS後・記事CAS直前にも再照合し、公開readback後も同じDOMを要求する。既存adviceやtemplateが変わった場合は要照合で停止し、
既存の安全情報を削除したり新しいclinical合格を作ったりしない。途中の書込み後に差分を発見した場合は通常のpartial/unknown journalを維持する。

### Slackの商品写真の配信コピー

`stateRoot/delivery-image-aliases.json` は元画像URLをキーに、`url/sha256/size/contentType` の4項目だけを登録する私的台帳。記事・商品・bundleの元URLと画像SHAは変えず、同一バイトの配信用コピーだけをSlack表示に使う。出典や画像同一性の審査を省略しない。

コピーは記事のsocial-card manifestと同じ保存先originの、SHAを含む固定pathに限定。PNGは`editorial-social-cards`または`editorial-delivery-images`の`.png`、JPEGは`editorial-delivery-images`の`.jpg`だけを許可する。元画像のMIME・SHA・サイズが一致し、2MiB以下で、fresh GETの同一バイト照合を全て満たす場合だけ本文の配信を始める。古い対応表や内容不一致は停止する。

アイキャッチ用bucket/uploaderは従来どおりPNG・1200×630を維持。商品写真用の独立bucketは公開・2MiB・PNG/JPEGに限定し、登録前に元データの完全デコードと保存後GETを確認する。変換・上書きはしない。送信途中の再開は既送信receiptと未送信の根拠を照合し、未知結果は盲目的に再送しない。本人の公開承認とSNS別承認は変更しない。
