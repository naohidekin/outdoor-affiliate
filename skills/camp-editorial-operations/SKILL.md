---
name: camp-editorial-operations
description: Camp Gear Lab編集台帳の状態確認、次工程の確認、停止した工程の限定復旧と検証を既存プログラムで行う。記事・SNSの承認や自動化の再開には使わない。
---

# Camp editorial operations

このファイルの実体からリポジトリのルートを解決し、対象の `AGENTS.md` と
[通常進行・工程復旧](../../docs/editorial-deterministic.md) の必要な節だけを読む。
台帳は既存SQLite、実行主体は既存runner一つ。スキル自体は定期実行を作らない。

分析から通常制作・既存記事改善への接続は[SEO循環](../../docs/seo-feedback-loop.md)を参照する。
版別の循環状況は`seo-feedback/latest.json`、最新の数値本文は`analytics/seo/latest.json`を読む。
同じ証拠でAIを反復起動せず、再分析の実行と公開後の効果計測を区別する。
共有商品の訂正は`check-corrected`で影響記事の本文・FAQを先に確認し、訂正待ちを未知の公開effectへ変換しない。
独立Astra確認の既存receiptがあれば再利用し、新規確認は対象版・共有予算に束縛した1試行に限る。本人承認にはしない。
`researchResponseRecoveryEnabled`は受信・利用量確定・全案形式違反だけを同じ制作期予算で追加1回扱う。
既存停止分の復旧は`research_response_recovery.prepare/owner_grant/arm`へ現marker・応答・context・configのSHAと
本人の実際の指示参照を束縛する。旧11/20専用回復を別期へ流用しない。
結果不明、部分採用、既存選定済み、予算到達は対象外。旧marker・応答・履歴を削除・初期化しない。
`existingImprovementsEnabled`は制作期ごと最大1件の確認済み既存記事を通常改訂へ渡す。
受領情報は`existing_improvement_attempts/results`、状況はhealthの`existingImprovement`で読む。
同一状態の再起動でAI・source調査を繰り返さず、holdを勝手に解除しない。未接続の検索意図・SERPを診断済みにしない。
本文・商品・画像・購入先・上位QAと本人対象版承認を維持し、記事承認をSNS承認へ転用しない。

11/28本人が不足2案の追加調査・制作を指示した11/27期だけは、`research_pool_completion.prepare/owner_grant/execute`を使う。
既知の適格フリース1案を固定し、検証済み商品ペアと公式504/507に支えられたシェルの役割2案を有限追加する。
旧hold・raw応答・入力・利用量・使い切ったrepair権を保存し、別の本人指示をhashへ結ぶ。
追加Claude企画は1回・同じ制作期128calls内。固有検索需要と関連ページの代理指標を区別する。
私的な購入先訂正は通常の`catalogCorrectionContext`へ束縛し、Astra QA・本人対象版承認前に共有商品を更新しない。
未公開3上限により後続枠が待つ場合も、選定pool内で訂正contextを保持し、枠が空いた時だけ既存producerが作る。
旧Stormの結果不明を消したり、別候補として枠を作り直したりしない。この有限権限を別期へ流用しない。

## 状態・次工程を確認する

運用CLIの読取専用 status/plan/records を使う。Runtimeのtickやproduceを確認目的で実行しない。
認証情報、本文全文、Slackのnonce、生ログを表示しない。正常な承認待ち・開始日前・
対象なしを異常扱いせず、同じ状態ではAIを呼ばない。

未解決記録の棚卸しは `python3 scripts/editorial/operations.py --state-root <絶対パス> records` を使う。
現在版と旧版、台帳の送達済みとファイルの未完了、managerの作業依頼と外部実行の結果不明を区別する。
この出力から再送・再実行を自動判断しない。

## 旧記録を照合する

本人が照合を依頼した場合は `record_reconciliation.py` のprepare/check/apply APIを使う。
元記録と公開・監査・インデックス証拠のhashを結び、追加receiptだけを保存する。
元の失敗、manager履歴、承認、モデル利用量、試行上限は書き換えない。
operationsのrecordsで照合済み履歴と現在の未解決を再確認する。証拠が変わった照合は無効とする。
旧X記録の本体IDだけで返信成功を推定せず、対象外の旧版を再投稿しない。

## 工程を復旧する

対象記事、工程、入力の識別値と、現在の停止理由を先に照合する。
明確な失敗だけを既存CLIの限定retryで扱い、初回＋修正1回の上限を守る。
in_flight/unknown、公開・投稿・送達結果が不明の場合は、既存受領情報を照合する。
マーカー削除、カウンタ初期化、別候補作成、直接SQL更新で先に進めない。
入力が変われば影響する検査をやり直し、公開内容が変われば旧承認を使わない。

本人が指定した既存記事改訂のdraft文字数不足は、`retry-corrected-stage`で
旧失敗1/2の残り1回だけを新入力へ引き継げる。改訂context・旧key・blocked受領情報を
照合し、fresh sourceと記事／商品の公開ベースが一致してからモデルを呼ぶ。
旧失敗・共有記事予算・制作週予算を保持し、上限到達や未知の結果を別枠で迂回しない。
進行中manager、関連する照合待ち、範囲不明の記録は停止条件。無関係と確認できる
過去のmanager記録は変更せず、当該記事の復旧を妨げない。

焚き火台改訂`revision-752f932fa6927ba5852ada4e`の既知Amazon NA証拠欠落だけは、
`resume-revision-review-after-purchase-na`へ対象job・型付きNA JSON・今回の指示参照を明示する。
固定sourceと成功済みdraft2/2・polish1/2のSHA、旧lineage、未開始final、fresh source／公開ベースを照合し、
本文等を保持したmetadata-only receiptから通常の最終審査へ一度だけ進む。writer／polish再呼出し、
旧記録や試行・共有予算の初期化、NAから欠品・販売終了の推定は禁止。失敗・unknownは照合待ち。
既定dry-run、実行はruntime.flock内の`--execute`。記事／SNSは別途本人承認を待つ。
今後の必要販路欠落は既存display gate後・writer前に明示NAの対象・理由・確認者・鮮度を検査し、
不足ならモデルを呼ばず保留する。詳細なCLI引数と検証条件は上記の運用文書を参照する。

2026-11-23の肌着保留とMontbell中心の3枠再選定は`supplemental_reselection.prepare/apply`を使う。
本人指示・既存owner-skin-hold.json・新旧manifest SHAを結び、同batch／notBefore／3slot／batch96を維持する。
3テーマ確定後、差替slot2だけsource-readyを必須とし、未制作1／3の証拠待ちは通常producerに残せる。
applyはrunner lease内で再照合し、旧skinのrejected／decided／本文／usageを変えず別IDのslot2を作る。
今回の旧skin IDに束縛したreceipt以外でrejectedを集計除外しない。旧版の制作・承認・送達・公開・SNSはholdで拒否する。
新jobは旧skinのarticle32を共有し、period128・batch96・pending3も維持。reportの新job実API費用と旧分込み共有残量を分ける。
候補未確定の適用・有料制作・旧不可視draftの削除／公開・本人承認代行は禁止。詳細は運用文書を参照する。

明示内部リンクはCatalogで実在published・同category・非自己参照へ照合し、要約上限5件内で最大3件を優先する。
今回の置換down新job`article-42e59288744a55545f896d2d`の既知リンク違反は保存出力を優先し、
`retry-saved-reselection-draft`へ対象job・draft・旧keyを明示する。固定artifact／旧sourceとfresh contextを照合し、
navigation以外の本文・brief・商品・画像・出典を変更せず純validatorで再検証する。残り1試行を継承し、
writer APIなしを`savedOutputLocalRevalidation`へ明記する。旧失敗・paid usageは保持、Gemini／Claude以降は通常経路。
既定dry-run、実行はrunner lease内の`--execute`。未知・source drift・枠消費済みは停止し、本人承認は別途待つ。

11/16追加3記事のdraft文字数・内部リンク違反を修正版で直す場合だけ、
`operations.py retry-corrected-stage`へ旧失敗のexact input keyを指定する。
まずdry-runで対象を照合し、本人の修正指示がある場合だけ`--execute`を使う。
旧失敗・利用量を保持し、旧キーと現入力キーを原子的に結んで残り1試行を引き継ぐ。
source hold・未知結果・上限到達では止まり、別キーや別記事で試行枠を作り直さない。

今回本人が追加許可したプラズマ1000だけは、`supplemental_review_recovery.py`の
prepare/executeを使う。旧artifact・失敗・許可参照・manifestを固定し、追加工程を各1試行に限定する。
通常のリトライ枠や予算は変更せず、この許可を他記事へ流用しない。

2026-11-20の最新本人指示は、ジオライン／シャミース2記事の原因を採点不整合と本文品質に分け、
本文・購入リンクを直して既存予算内でSlack承認待ちまで進めるcompletion権限を含む。
`supplemental_pair_recovery.py`の`phase='completion'`でfresh source・現失敗artifact/hash・具体的な別修正仕様を束縛する。
既知のfinal_review_failed後は同じ本人指示で別仕様を進められるが、各工程1試行、同一仕様・過去本文の再採点は禁止する。
32calls/記事・128calls/制作期間・96calls/batchの既存総枠、旧claim・履歴・実測利用量を維持し、枠を作り直さない。
unknown/in_flight・provider/schema異常は停止して照合し、本文validation失敗を同入力で再試行しない。
この権限を他記事・本人承認・公開・SNS予約／投稿へ流用せず、承認は対象版ごとに別途扱う。
completionの`correction_path`は現polished本文＋FAQを含むarticle/hashと、限定path・old/new・出現回数を固定する。
削除以外の全文候補は`mode='upper_editor_candidate'`と上位確認記録を必須とし、候補・執筆仕様・fresh research・source proofのhashへ結ぶ。
新しい本文やFAQは上位編集候補であり、旧writerの新規出力とは扱わない。商品・出典・画像・identityと原writer briefは保持し、protected/facts等との衝突は別確認する。
ローカル補正は`literal_correction`として記録し、writer再呼出しや架空のモデル利用量を作らず、実Gemini→独立QA→実Claude finalを既存総枠内で通す。

2026-11-20通常企画の既知`proposal_contract`（6案すべてintent enum違反）だけは、
`research_contract_recovery.py`のprepare/armで旧marker SHA・raw artifact SHA・固定response ID・settled予算を照合する。
旧markerを別archiveへ保存し、first failure＋repair1 receiptを残して主markerを`retry_ready`へ進める。
既存producerが新企画の呼出し前にrepair権を一度だけ消費し、同じ`research:<period>`予算で新schemaから企画する。
旧案のintent分類・source/product IDsの補完・旧案の選考転用は禁止。失敗・unknown・予算停止で権利を戻さない。
元artifactはnative実ファイルの固定SHAも必須とし、caller指定SHAだけで同response IDの改変を受け入れない。
確認済みは6案のintent違反であり、唯一のエラーとは断定しない。元requestがない旧category/product/existing membershipは未確認のまま記録する。
旧context適合証明を作らず、新企画はfresh contextの全validationを必須とする。
通常週3本・共有pending3・既存総予算と、記事／SNSの本人別承認を維持し、設定再開や公開の権限にはしない。

## 品質と承認を確認する

2026-11-23の本人指定で、肌着比較`article-b1059cbd51d84cee93adbdc6`だけは
`skin_insertion_recovery.py`のdiagnose/prepare/executeで限定復旧する。
保存済みClaude出力の挿入差分を上位確認し、既存本文・数値を固定して再利用する。
旧draftの失敗2回・実測利用量を残し、同じ記事・制作週・batch予算で実Gemini校正と
Claude最終審査を各1要求だけ実施する。執筆の再呼出し・枠の初期化・別記事への流用は禁止。
fresh source、本人の復旧指示、選択挿入文、対象版、実装hashをprepareで固定してから
runtime.flock内で一度だけclaimする。送達不明・中断・不合格は照合待ちで止める。
この復旧指示は記事承認でもSNS承認でもなく、公開・予約は本人の別承認を待つ。

工程結果の再利用は執筆・校正・審査の重複呼出しを避ける手段に限る。
現在の公式情報・商品写真・購入先、PC/スマホ表示、既存品質基準を確認する。
本人の記事対象版承認とSNS対象版承認は別。モデル審査や送達を本人承認にしない。
公開後検査・サイトマップ・GSC確認は既存の版別受領情報で照合する。

## 停止と報告

記事系とSNS系は別制御。SNS生成・承認配信／取込・X投稿の各flagを、
記事制作の再開に伴って有効化しない。SNS待ちを理由に次期の記事制作を止めない。

停止中は読取専用確認とオフライン検証まで。再開の明示指示がなければ
production設定、launchd、Codex automationを有効化しない。
ただし本人が対象記事の修正とSlack配信を明示した場合は、上記運用文書の
「本人指定の限定手動修正」に従いmanual_reviewを使う。通常停止を解除せず、
対象外制作・承認・公開・SNS投稿を行わない。未知の送達は照合してから扱う。
報告は対象、観測結果、残る確認、必要な本人操作だけに絞る。
実モデル・実測利用量・欠測・推定費用・実請求を区別し、キャッシュ利用を新規利用量に加算しない。

審査済み記事のSlack送達だけが失敗した場合、本文生成・校正・審査を再実行しない。
対象版と送信窓を固定して実GETと`slack-outbound`を照合し、旧verified receiptは上書きしない。
再入防止はstateRoot配下の永続receiptとruntime.flockを使い、送達済み部分を再投稿せず、
固定した未送信部分だけを配信する。写真の配信用ミラーは元画像とbytes・SHA・MIMEが一致するものだけを
既存`delivery-image-aliases.json`へ登録できる。本文・画像・購入先の版を変えず、
失効した承認要求は本人承認へ戻さず、新しい対象版確認カードとして配信する。

## Buffer経由のSNS

[Buffer連携](../../docs/editorial-deterministic.md#buffer経由のsns) に従い、`buffer_x` の承認版と
`buffer-publications` の工程記録を照合する。記事承認・SNS承認、Buffer予約・Buffer送信・X実投稿確認は別の状態。
旧 `auto_x` の承認・spoolを移行せず、別の既存Buffer投稿を引き取って予約・変更しない。
本文・画像SHA・画像順序・記事URL・Bufferチャンネル・Xアカウント・予約方針を対象版へ固定する。
結果不明のcreate/editは再送せず照合する。時刻前の待機はAPIを呼ばず、確認回数・共有API枠の上限を守る。
Bufferがsentでも、Xの本文・画像・返信の証拠が不足すれば未確認とする。画像の近似一致を合格にしない。
接続キーの入力は専用ローカル画面へ本人が行い、キーをチャットや引継ぎへ記載しない。

## ウェアと本人指定の追加3本
2026-11-22の冬物深掘りは`winter-depth-2026-11-22`の固定3案。R1/クリマエアの未制作案は同じslugを再利用し、旧公開2件と予算・履歴を保持する。`supplemental-winter-depth-20261122.json`の登録だけで制作・配備・商品照合完了とは扱わない。
新ブランドは`apparel_identity.py`と`official_shopify_apparel.py`の公式主商品照合を使う。別モデルSKUが混在する主商品、親ASINだけのURL、未確認の色サイズは保留する。検索結果だけで商品同一性を認めない。
モンベルは本人指定の重点調査ブランド。本人の購入意向は購入・使用経験に変換せず、同じ用途の確認済み候補から推奨を決める。国内ブランドと個々の商品の製造国を区別する。
`apparel_identity.py`の公式仕様・主商品画像・購入先variant証跡を使い、未分類wearをgear検証へ落とさない。型番・性別・色・サイズの違い、親ASINの未選択状態は保留する。
追加制作は`apparel-2026-11-16`の固定3slotのみ。通常週3本とは別計数、共有未公開3件・制作週予算・batch全期間96callsを維持し、既存runnerの開始日時とsource_holdを尊重する。
11/20企画は検証済み候補内で秋冬ウェアを優先し、既存比較の重複、未検証の需要・使用経験を作らない。記事／SNS本人承認は別のまま。
## Bufferキー更新
`buffer_connection_setup.py --rotate`は旧キーが有効な間に準備し、本人の再生成前に予約snapshotを取得する。更新前後を照合し、キー以外を変更しない。
write権限はBuffer UIでの本人確認とAPI読取の実証を分ける。結果不明・CAS不一致・payload差分は保留し、再生成・再予約・送信を自動再試行しない。

### 文章生成前の商品確認だけで止まった今回の改稿

`retry_revision_source_hold` は一般的な再開ボタンではない。今回の本人指示・対象job・改稿仕様の固定照合を通し、モデル呼出し・予約・承認・公開が一度もないことを確認できる対象だけ、一度だけ既存制作処理へ渡す。旧失敗ソースの正確なバイト列と旧実行記録を保持し、別の追記専用受領情報へ結果を残す。全商品の再確認を省略せず、再失敗・結果不明では止める。通常tickへ接続せず、許可対象や予算を広げない。

### 表示確認だけを修復した改稿の続行

`revision_render_resume.prepare()` の読取照合を先に通す。対象・本人指示・既存の本文/校正成功キー・出力SHA・実利用量・旧表示失敗受領情報を固定し、同じ入力の保存済み本文/校正だけを利用する。`execute()` は一度限りの別claimと旧証跡の正確なコピーを残す。本文/校正のcacheが不一致ならモデルや予算予約に入らず停止し、最終審査と独立QAだけを通常予算で続ける。古い記録の削除、枠の初期化、承認/公開の付与、通常tickへの自動再試行追加は禁止。

医師助言欄の対象外は、固定ファイルの静的mapでslugが未登録であること、PC/スマートフォンで実際に欄がないこと、公開前後も同じ適用区分であることを検証した型付き証拠に限定する。既存助言欄がある記事は従来どおり内容とDOMの一致が必須であり、医学的正確性を新たに認証したことにはしない。
