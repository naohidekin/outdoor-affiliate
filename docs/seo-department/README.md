# SEO 実験部門の運用

この運用は、既存の記事生成パイプラインの採用モデルやフローを変更しない。実験は隔離したリポジトリで実行し、状態・GSC 集計・公開ジャーナルは公開 Git 管理外の private runtime root にだけ保存する（非公開 secretary repo での履歴化は可）。

```bash
export SEO_REPO="/path/to/campgearlab-seo"
export ORIGINAL_REPO="/path/to/outdoor-affiliate"
export SEO_STATE_ROOT="$HOME/.secretary/state/campgearlab-seo"
cd "$SEO_REPO"
node scripts/seo/cli.mjs --root "$SEO_STATE_ROOT" init --policy docs/seo-department/policy.json
node scripts/seo/preflight.mjs --root "$SEO_STATE_ROOT" --policy docs/seo-department/policy.json
```

資格情報は `ORIGINAL_REPO` の `.env.local` だけから明示的に読む。探索や複製はしない。状態 root、環境変数値、GSC の実データ、公開 manifest の中身を public docs や Git に書かない。

```bash
node scripts/seo/metrics.mjs --root "$SEO_STATE_ROOT" --env-file "$ORIGINAL_REPO/.env.local" --write
node scripts/seo/observe.mjs --root "$SEO_STATE_ROOT" --env-file "$ORIGINAL_REPO/.env.local" --write
node scripts/seo/preflight.mjs --root "$SEO_STATE_ROOT"
```

`preflight` は read-only で、モデルや資格情報を使わない。新規介入を許可するには、最新 GSC が PT（`America/Los_Angeles`）基準で確定済み、運用コストが判明、直近 7 日の operations が 200 credits 未満、active experiment が 3 未満である必要がある。operations は 1 run の目標を 50 credits とする。implementation の利用量は週次介入予算に数えない。費用の実 USD は別会計であり、記録がなければ `unknown` のまま扱う。コスト欠損・予算到達・GSC 欠損/陳腐化では新規介入を凍結するが、観測、レポート、公開復旧は実行できる。

日次の上限は新規 1 件、同時 active は 3 件である。canonical page と link source page の重複は認めない。手作業で記事が変わった場合は content hash / publication baseline の不一致として停止する。

候補の選定、根拠の承認、因果評価、公開の判断は `gpt-6-astra` が根拠付きで記録する。Terra は範囲を限定した調査・コード、Luna は抽出だけに使う。GSC 取得、preflight、集計は deterministic で LLM を使わない。OpenRouter 比較パイロットは、実測で継続的な予算超過または同品質で検証済みの総費用削減がある場合だけ検討する。

比較コホートは承認時に query / page / device を固定する。GSC は日本（`jpn`）を対象にし、ソース日付は PT、運用表示は JST とする。verified publication 後にだけ時計を開始し、7 日・14 日は早期観測、28 日・42 日は判断候補である。各観測は完全な PT 期間と `settledThrough` を持つ必要があり、未確定値、欠損値、source failure をゼロで補わない。相関を因果として記録しない。

GSC API の日付は PT の日単位で返るため、publication 当日は完全な比較日として数えない。最初の publication 後 PT 日から checkpoint 日数ぶんの完了日を待ち、API が示す `settledThrough` まで確定してから `observe.mjs --write` を実行する。その後に Astra が固定コホートと根拠を評価する。

Google Search Console の AI Overview 専用レポートは 2026 年 8 月以降 UI で利用できる場合がある。通常 Web の query/page 指標と、AI Overview の impressions・source pages・countries・devices は別の母集団として保存する。クリック、query、API の利用可否を推測して補わない。

公開 manifest の正規仕様・検証者は `scripts/seo/publish.mjs` の `validateManifest` である。manifest には experiment identity、remote baseline の timestamp/hash、許可された patch、非空の evidence、同一 manifest hash に紐づく Astra approval が必要である。公開前に dry-run を行い、適用時は明示的に `--apply` を付ける。

```bash
node scripts/seo/publish.mjs --root "$SEO_STATE_ROOT" --manifest "$MANIFEST_FILE" --env-file "$ORIGINAL_REPO/.env.local"
node scripts/seo/publish.mjs --root "$SEO_STATE_ROOT" --manifest "$MANIFEST_FILE" --env-file "$ORIGINAL_REPO/.env.local" --apply
```

公開の verified event が state に記録されるまで観測を開始しない。rollback は「元に戻す」という別実験を forward に公開・検証してから判断する。自動化スケジュールはここでは作成も前提化もしない。

利用量は各タスクの開始後と終了直前に `node scripts/seo/account-run.mjs --kind operations` で登録・再集計する。次の実行が前回の最終応答分も取り込む。初期構築は `--kind implementation` で別記録とし、同じタスクを運用費へ付け替えない。公開クレジット単価に基づく推定であり、請求額・OpenRouter実費ではない。Fast設定などログで確認できない割増は未反映である。日付をまたいで開始した子タスクがあれば、そのログを `usage.mjs --session` に明示して補完する。

```bash
node scripts/seo/cli.mjs --root "$SEO_STATE_ROOT" propose --file "$PROPOSAL_FILE"
node scripts/seo/cli.mjs --root "$SEO_STATE_ROOT" approve "$EXPERIMENT_ID" --file "$APPROVAL_FILE"
node scripts/seo/cli.mjs --root "$SEO_STATE_ROOT" report --write
```

週次の報告文は機械生成レポートに Astra の「事実→判断の理由→狙い→実施内容」を添える。AI掲載、クリック、順位、事業成果は別々に記載し、成功事例だけを抜き出さない。原稿の追加・競合分析では公式仕様、実体験の裏付け、検索意図、SERP上位の提供価値、季節性、カニバリゼーションを確認する。競合の順位は観測日時・地域・端末を記録し、Web検索ツールの結果順をGoogleの順位と同一視しない。

1ページに複数の新規仮説を重ねない。新規介入の前には現行の Supabase 対象行だけを読み、隔離作業場所の同じ対象行を照合する。旧チェックアウトに他人の未コミット変更がある場合は触らない。全行同期や本番管理 API の一括更新での公開は禁止し、選択的 publish CLI を用いる。復旧が必要なら同じ manifest を再実行して、書き込みの二重適用を防いで検証を完了する。

公開 CLI の照合用記事ミラーは `$SEO_STATE_ROOT/mirror/articles.json` を既定にする。公開リポジトリの `data/articles.json` は照合ミラーに使わない。本番には独立した既存更新があるため、全行を取り込むと無関係な差分まで混ざる。新規候補の baseline を取る時は `node scripts/seo/snapshot.mjs --article "$ARTICLE_ID" --env-file "$ORIGINAL_REPO/.env.local"` を実行する。必要なら `publish.mjs --articles-file FILE` で照合ミラーを明示できる。既存ジョブは共通の publication lock と snapshot により保護対象を全行 upsert から除外する。観測中の別編集は observe が hash で検出し pause する。
