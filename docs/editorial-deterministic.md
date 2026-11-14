# Camp編集の通常進行と工程復旧

この変更は隔離ブランチで検証する。既存の本番設定・launchd・承認台帳を切り替える手順ではない。
停止中のCodex確認用automationを、この変更の導入やテストを理由に再開しない。

## 分担

通常の開始日・件数・次工程・待機・送達・承認照合はプログラムで扱う。
企画、執筆、Gemini校正、Claude内容審査は従来のモデルと品質基準を維持する。
独立Astra審査が必要な訂正・改訂について、その審査を工程キャッシュで代用しない。
判断が必要な例外は人がCodexへ依頼する。定期的なAI診断ループは新設しない。

`executionPolicy` は明示導入する構成とし、導入準備時には停止状態を指定する。

```json
{
  "executionPolicy": {
    "mode": "deterministic",
    "suspended": true,
    "exceptions": {"autoAI": false}
  }
}
```

この断片を本番へ自動反映しない。設定がない旧構成との互換動作と、停止設定を別に扱う。
特に旧managerを無効化するだけでは従来の自動生成分岐へ戻るため、移行手順として使わない。

## 繰り返す確認の入口

[運用スキル](../skills/camp-editorial-operations/SKILL.md) を使う。
運用CLIのstatus/planは読取専用で、モデル、Slack、公開、商品サイトへ接続しない。
コマンドの詳細は `python3 scripts/editorial/operations.py --help` で確認する。
次のコマンドは状態を読むだけで、Runtimeを生成せず認証ファイルも読まない。

```bash
python3 scripts/editorial/operations.py --state-root /absolute/path/to/state status
python3 scripts/editorial/operations.py --state-root /absolute/path/to/state --config /absolute/path/to/config.json plan
```

停止した工程の再試行案は、statusの対象記事・工程・入力キーを指定して確認する。
`--execute` を付けなければ実行しない。停止設定の場合は `--execute` を付けても実行しない。

```bash
python3 scripts/editorial/operations.py --state-root /absolute/path/to/state --config /absolute/path/to/config.json --job-id ARTICLE_ID --stage polish --input-key EXACT_STAGE_KEY retry-stage
```

実行は対象と失敗根拠を確認し、停止していないことと復旧権限を確認した運用時に限る。
工程記録だけを確認するときは、既存SQLiteを指定する。

```bash
python3 scripts/editorial/stage_journal.py /absolute/path/to/ledger.sqlite3
python3 scripts/editorial/stage_journal.py /absolute/path/to/ledger.sqlite3 --job-id ARTICLE_ID
```

原稿・APIキー・認証設定・Slackのnonceは表示しない。欠測を成功やゼロに置き換えない。
診断のためにRuntime.tick、produce、外部モデルや投稿コマンドを実行しない。

## 工程記録と再利用

SQLiteの既存meta/eventsへ、記事・工程・入力と依存資料のハッシュ・状態を記録する。
成功出力は同じprivate台帳へ保存し、読取用statusでは本文を出さない。
AI呼出し前に予約を保存し、正常完了後に出力ハッシュを保存する。

- 同じ入力・依存資料・モデル経路・スキーマの成功結果だけを再利用する。
- 公式情報・画像・購入先の現在確認と、PC/スマホの表示検査は再利用で省略しない。
- 本文、商品条件、画像、リンク、品質基準などが変われば、影響する工程を再実施する。
- 表示内容が変わった版に旧本人承認を移さない。記事とSNSの承認は引き続き別々。
- 過去の原稿から工程成功を推定して埋めない。既存の失敗・承認・予算・送達記録を保持する。

## 失敗と再試行

同じ入力で失敗した工程を通常のtickで繰り返さない。既知の失敗のみ、対象を限定した
明示的な再試行を初回に加えて1回まで許す。上限到達後は停止理由を報告する。
途中停止・結果不明・壊れた記録は照合待ちとし、入力変更でも迂回しない。

この上限は工程の実行回数であり、providerへのHTTP要求数ではない。
既存の執筆内の文字数補修、通信エラー処理がある場合、その実測応答を別に数える。
応答が得られず利用量が取得できなかった呼出しを「AI呼出しなし」と報告しない。

公開・X投稿・Slack送達には従来のeffect/delivery記録を使う。
工程記録のretryやキャッシュを使って、それらを再投稿・再送しない。
記録の削除や直接SQL更新で復旧せず、結果不明の実行は根拠を確認して照合する。

## オフライン検証

```bash
python3 -m unittest discover -s scripts/editorial -p 'test_stage_journal.py'
python3 -m unittest discover -s scripts/editorial -p 'test_dispatcher.py'
python3 -m unittest discover -s scripts/editorial -p 'test_*.py'
```

実モデル・実Slack送信・実公開は使わず、合成台帳と偽の接続先で確認する。
変化なし/承認待ち/停止時の外部呼出しゼロ、表示失敗からの再開、入力変更による無効化、
旧版承認の拒否、結果不明の公開・投稿の重複防止を確認する。
公開後の検査とインデックス追跡は、既存テストと版別受領情報の契約を維持する。

## 再開前の作業

1. 未コミットの安全訂正・表示制御・承認処理との統合を確認し、組合せテストを通す。
2. 対象Macの隔離コピーで同じ検証を行い、本番未反映とコード同期を区別する。
3. 本番の停止/有効フラグ、既存の結果不明effect、単一runner、モデル設定を限定確認する。
4. 本人が再開を指示した範囲だけ設定を切り替える。確認用heartbeatの復活は前提にしない。
5. 最初の実制作は従来の全品質ゲートを通し、記事公開・SNS投稿はそれぞれ本人承認を待つ。

オフラインテスト成功は、実認証・実モデル・実送達・実公開の成功証明ではない。

## 2026-11-14 停止配備

実行ブランチは `codex/camp-editorial-slack-20261103`。両Macの既存変更を保存コミットし、
その両方と deterministic 実装を統合する。Webサイト main の配備とは別。

停止時は executionPolicy.suspended=true、exceptions.autoAI=false、editorialManager.enabled=false。
generation/publication/socialPosting/reports/postPublicationAudit/indexTracking/
catalogCorrectionsPublication の各Enabledはfalse。launchdとCodex確認automationも再開しない。

再開時は本人が指定した範囲の認証と未解決記録を確認する。公開を許可する前に
postPublicationAuditEnabled と indexTrackingEnabled を必ず復元し、制作・公開・SNS・報告の
各フラグは許可範囲だけ戻す。旧AI managerは無効を保ち、単一runnerの停止を最後に解除する。
公開後検査の停止中を「品質確認の成功」とは扱わない。通常進行のAI削減量は実稼働前には未測定。

記録棚卸しは `operations.py --state-root <absolute-root> records`。SQLiteは読取専用、
既知の構造化受領情報だけを使い、モデル・環境ファイル・外部APIを呼ばない。
出力で成功判定できないものは照合待ちとし、履歴や予算を初期化しない。

停止後も、停止前に発動済みのモデル応答と利用量の受領証跡は保存する。
結果保全は新規実行の許可ではなく、次のモデル呼出し・公開・送信は停止判定で拒否する。

## 2026-11-14 監査と商品同一性の限定修正

本人指定により今回の実装はCodexと独立レビューで行う。既存の制作・校正・審査モデルは変更しない。
公開GETは同一監査内で最大4並列、取得応答の保持は合計64MiBまで。150秒の内部期限と
180秒の親プロセス上限を維持する。期限到達時には確認済みの失敗・成功を保持し、
残りをunverifiedとして記録する。結果はstdoutへ即時flushし、子の終了待ちで失わない。

制作前と公開後はmerchant_identityの共通判定を使用する。誤型番・付属品だけの購入先は
failed、情報不足・型式やサイズの競合はunverifiedとして停止する。ブランドの明示aliasと
区切りだけを正規化し、店舗名内の英字部分一致やアクセサリーセットを本体根拠にしない。
既存固定商品のprimary-node検証を公開後にも適用するが、誤型番・付属品の拒否は上書きしない。
公式情報・画像SHA・紹介先・遷移先・PC/スマホ表示の検査は省略しない。

新しい読取専用の実測結果はprivate deployments受領情報へ保存する。過去の監査失敗・
自動再確認3回の履歴や予算は消去しない。未確定なリンクを別候補へ自動交換せず、
内容や購入先が変わる場合は新しい対象版として審査し本人の記事承認を受ける。
SNS変更には別の本人承認を必要とする。実行設定の停止は維持する。
楽天の中継は観測済みtransition.afl.rakuten.co.jpだけをexact-hostで追加する。
紹介先ID、HTTPS、DNS固定、最終itemのhost/path/pc一致は維持し、サブドメインへ広げない。
