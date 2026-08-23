# Snow Peak IGT 需要検証MVP — 本番データ

**現在このデータは空です。意図的に空です。**

実装時（2026-08-23）、作業環境のネットワークegressポリシーが
Snow Peak 公式ドメインへの接続を拒否していたため、公式資料で
裏を取ることができませんでした。

```
www.snowpeak.co.jp:443  → gateway 403 (connect_rejected)
www.snowpeak.com:443    → gateway 403 (connect_rejected)
```

Web検索自体は通りましたが、返るのは Amazon・eBay・CampSaver などの
**販売店ページ**です。これらは互換性の確定根拠として使ってはいけない
情報源であり、公式ページで確認できない以上、投入すれば捏造になります。

そのため、スキーマ・検証・空状態だけを実装し、データは入れていません。

## 追加するときの絶対条件

`src/lib/experiments/snow-peak-igt/core.ts` の `validateDataset()` が
起動時に検証します。次を満たさないレコードはビルド時に落ちます。

- `sourceIds` が1件以上あり、すべて `sources.json` に実在すること
- `lastVerifiedAt` があること（YYYY-MM-DD）
- 互換性を `confirmed` と書くなら、その項目にも `sourceIds` があること
- `confirmedSuccessorId` は実在する商品IDを指すこと
- `purchaseOptions[].url` は絶対https URLであること

## 人が判断すべきこと（自動化しない）

- **日本型番と米国型番を混同しない。** 同じ製品でも別番号がある
- **後継品があること＝互換性がある、ではない。** 別概念として別項目に入れる
- 情報が無い項目は埋めない。`null` のままにする。表示側が
  `Unknown` / `Insufficient evidence` に変換する
- 出典は公式商品ページ・公式マニュアル・公式アーカイブ・公式サポートのみ
  （`sourceType` の型がそれ以外を受け付けない）

## テスト用データはここに置かない

fixture は `tests/experiments/snow-peak-igt/fixtures.ts` にあります。
`tests/experiments/snow-peak-igt/production-data.test.ts` が
「fixtureのIDが本番データに混入していないこと」を検証します。
