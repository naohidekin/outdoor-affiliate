# Camp Gear Lab 編集パイプライン（実装と配備状況）

## 0. 現在状態（2026-11-03 JST）

**新パイプラインは実装済み。macproへの配備、GUIでのSlack認証・Gemini校正接続、Slack接続確認メッセージの送信とreadback、常駐tickを確認した。制作・公開の有効化状態は末尾の配備記録を参照する。**
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
| `models.py` | Claudeによる候補選定・執筆・上位審査・SNS原稿、Gemini 3.8 Flash校正、完全brief、厳格JSON・保護データ境界・usage記録 |
| `catalog.py` | Supabase既存商品・記事・カテゴリ・クリックの読取、公式仕様の型番照合、画像取得とSHA-256、購入先のlive照合。public DNS固定・リダイレクト再検証 |
| `quality.py` | 本文H1、商品ID/shortcode/「◯選」、内部リンク、FAQ、metaDescription、画像metadata・購入先URL・NA証跡、校正保護要素の順序/内容を機械検証 |
| `render-preview.mjs` | 隔離Nextアプリで実コンポーネントをdesktop/mobile表示、privateスクリーンショット、画像・H1・overflow・shortcode・購入CTA計測と遷移先検査 |
| `publish.mjs` | draft stage、exact版・既存商品照合、共通SEO公開ロック、CAS公開、DB/cache/public HTML readback、承認画像bytes再照合 |
| `slack.py` / `slack-api.mjs` | 既存Bot/認証受信経路を利用した本文分割・FAQ・画像・記事/SNS承認カード配信、Bot identityと配信内容readback、送信間隔制御、認証受信側からの署名検証済spool受渡し |
| `install.py` | LaunchAgent生成と任意load。`com.naohide.camp-slack-review`、300秒間隔、RunAtLoad、JST、privateログ。資格情報はコピーしない |

`runtime.py --config <host-local-config> status|preflight|tick|produce|deliver|retry|approve-from-codex` が入口。
`preflight` はSlack auth.testとGemini接続検査であり、全経路の稼働保証ではない。
`produce` は明示的な手動制作入口。水曜09時以降の開始条件は定期実行の `tick` が適用する。
`install.py --config <host-local-config>` はplist準備、`--load` 付きはGUI domainへのbootstrapを伴う。
本書更新では配備・load・外部送信・公開を実行しない。

## 2. 実行主体・週枠・再開

- 新経路は**単一macpro**に統合する。Airへ公開を中継する旧計画は採用しない。
  他Macで同じrunnerを稼働させない。端末内flockを端末間排他とは扱わない。
- LaunchAgentは**300秒ごと**にtickし、ログイン後のRunAtLoadでも再開する。
  **JST水曜09時以降、その週の日曜まで**制作が可能。毎水曜09時ちょうどの実行保証ではない。
  tickの制作は1記事ずつ。週3枠は候補作成数の上限であり、週3記事の公開保証ではない。
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
3. **執筆仕様→既存Claude執筆**。正本は `CLAUDE.md`、ルート `SKILL.md`、
   `docs/writing-style.md`、`docs/author-gear.md`。briefは目的/読者/結論/見出し/確定事実/数値/リンク/
   必須表現/禁止変更事項/文体/文字量/CTA/形式と、公開可能な入力である `externalSafe: true` を持つ。
   未確認の所有・体験・購入者レビューを捏造しない。体験が未確認なら調査記事と本文で明示する。
4. **Gemini 3.8 Flash**は本文校正候補だけを生成。元sourceを変更せず、見出し/URL/数値/
   shortcode/商品ID/表/code/広告表記/相対リンク先の内容・順序を `inspect_polish` で比較する。
   Geminiは新事実・医学的助言・商品条件・結論を作らず、合否を決めない。privateなresearch/artifacts配下へsource.json/candidate.jsonを分離保存し、上位審査へ元本文と編集ルールも渡す。
5. `inspect_bundle` の構造検査後、実renderと**上位最終審査7.5/10以上**を通す。
   facts/images/affiliate/medical/renderの独立証跡を必要とし、モデルの「確認済み」だけで合格にしない。
   qualityが返す `mandatory_evidence` はpending。意味同一・事実完全性・実体験・医療・live/renderを自己認定しない。
   現runtimeは医療/子どもの安全に関する助言を自動選定から避け、検出時は保留する。
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

## 7. SNSはmanual post handoff

- 記事公開のDB/cache/public readbackがverifiedになった後だけSNS原稿を作る。
  公開本文・画像を根拠にClaude生成→Gemini 3.8校正→上位7.5審査→**記事と別のSNS承認**。
- 現proposalはtext / replyText / url / images / platform=x。本文にURLを置かず、正確な公開URLを返信へ置く。
  告知案全体の独立fingerprintを使い、変更時はSNS再審査・再承認。
  SNS予定日時/予約を現schemaが実装しているとは書かない。
- SNS承認後は `social-outbox/<revision>.json` に **`approved_manual_post_pending`** を記録しSlackへ通知する。
  **自動投稿・自動予約は行わない**。本人が原稿を利用するか、Codexアプリへ投稿を別途依頼する。
  手動投稿後の外部投稿ID/readback収集までをこのrunnerが実装済みとは扱わない。
- X旧自動投稿は復活させず、新しいSNS認証・課金・旧レールを追加しない。
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
| Python試験（bf0a5ec） | Air・macproとも116件成功 |
| macproのpublish/render試験（bcba319） | 実renderを含む31件成功、skipなし |
| 新runtime GUI preflight | Slack認証・Gemini 3.8 Flash実呼出し成功 |
| Slack実送信 | 接続案内と制作停止案内をAPI読み戻しで確認。本人の既読は未確認 |

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
- 承認済み実記事の公開はまだ実行していない。公開試験は隔離データの契約試験であり、実際の公開実績に数えない。
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
