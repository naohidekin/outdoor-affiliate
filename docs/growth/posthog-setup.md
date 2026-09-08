# PostHog導入

## 状態

サイト側の実装・型確認・購入クリックの回帰テスト・本番ビルドを確認。専用プロジェクト598025（US Cloud）の公開トークンをサイト所有者から受領し、クライアント用設定へ反映。本番でのイベント受信確認は未完了。GA4と独自クリックビーコンは継続。

## 接続設定

Camp Gear Lab専用プロジェクトを作成し、以下を本番環境に設定して再デプロイする。Persona Apartのトークンを流用しない。

- NEXT_PUBLIC_POSTHOG_KEY: プロジェクトの公開トークン（個人APIキーではない）
- NEXT_PUBLIC_POSTHOG_HOST: プロジェクト地域に合わせ https://us.i.posthog.com または https://eu.i.posthog.com
- NEXT_PUBLIC_POSTHOG_REPLAY: true で記事ページのみ録画を開始。初期値は無効。PostHog側でも録画を有効にする。

環境変数が未設定の場合は専用プロジェクトの公開トークンとUSホストを利用する。NEXT_PUBLIC_POSTHOG_KEYを空文字に設定するとSDKを読み込まず、送信しない。プレビュー・localhostも対象外。本番ドメインのトップ、記事、カテゴリ、選び方ガイドだけを対象にする。

## イベントと確認手順

1. 実際のスマホで記事を開き `$pageview`、`article_view` を確認。
2. 比較表のヘッダーまでスクロールし `comparison_view` を確認。記事を離れるまで一度のみ。
3. 購入リンクの表示で `affiliate_offer_view`、クリックで `affiliate_click` を確認。
4. article_slug / page_path、product_id、merchant、placement で集計する。比較表到達を経由しないクリックもあるため、記事閲覧→クリックのファネルも別途作成する。
5. 管理・問い合わせページとプレビューで新しいイベントが送られないことを確認。
6. リプレイを有効にする場合は文字・入力欄のマスクを確認し、記録量の上限と保持期間を管理画面で設定する。

リンク先URL・任意テキスト・フォーム入力値はカスタムイベントに転送しない。URL検索パラメーター・参照元の自動プロパティも送信前に除く。CookieではなくsessionStorageを使い、個人プロフィールは作らない。GA4初期化待ちイベントの再送でPostHogに二重送信しない。

購入クリックは注文・報酬ではない。売上は各アフィリエイトのレポートで評価する。

## 根拠

- https://posthog.com/docs/libraries/js/config
- https://posthog.com/docs/libraries/js/usage
- https://posthog.com/docs/session-replay/privacy

## 2026-09-07 追加確認

ユーザーからイベント受信を確認したとの報告あり。こちらのブラウザーではPostHogに未ログインのため、ダッシュボード作成と集計結果の確認は未実施。
比較表の到達イベントはモバイルの商品カード導入部にも対応。非表示のデスクトップ表はIntersectionObserverの到達対象にならない。

次に作るレポート：
- ファネルA：article_view → affiliate_click。同一セッションで集計。
- ファネルB：article_view → comparison_view → affiliate_click。同一セッションで集計。
- 記事URLとデバイス種別で分け、merchant / placementでクリックの内訳を確認。
- 同じ期間のAmazon・楽天レポートと合わせて評価する。クリックを注文と扱わず、単一トラッキングIDから記事別報酬を推定しない。
- 少数アクセスの短期間比較から勝ち負けを断定しない。まず同じ曜日を含む期間で基準値を集める。


## 2026-09-08 更新：集計画面と管理アクセスの除外

- プロジェクト598025へのイベント受信と、購入導線ダッシュボード（ID2076127）の保存を確認済み。
- 主要3記事の同一記事・同一セッションの閲覧→クリックファネル、記事別イベント回数、商品・購入先・設置位置別クリックの5レポート。
- 認証成功時と認証済み管理画面アクセス時に `camp_analytics_excluded=1` を設定（最長1年間）。ログアウト後も残す。認証Cookieとは別で権限を持たない。
- 既にログイン済みのブラウザはデプロイ後に管理画面を再読み込みする。別の確認用スマホは `/analytics-settings` で「このブラウザを計測から除外する」。開いている記事も再読み込みする。
- PostHogは初期化前・非同期初期化後・送信直前に除外を確認。GA4はタグ初期化前に公式のga-disable設定を適用。独自クリックAPIも除外Cookieまたは有効な管理セッションがあれば保存しない。
- 除外は当該ブラウザだけに有効。通常読者、別ブラウザ、Cookie削除後の確認操作まで自動判別しない。過去の記録は変更せず、導入前の管理アクセス混在を注記する。
- LinkSwitchとアフィリエイトURLは変更しない。クリック集計停止は購入リンクやASP側の成果計測停止ではない。
- GA4根拠：https://developers.google.com/tag-platform/security/guides/privacy
