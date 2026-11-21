# 記事審査の評価と計算の分離

## 現行 v2：品質判定とadvisory評価

2026-11-21の本人選択により、新しい記事審査は`article-review-scoring-v2`を使う。
`admissionMode=hard_checks_and_owner_floors`を保存し、事実・画像・商用導線の適用契約・医療・render・構造のhard検査、
原義のWISE六軸floor（2,2,2,2,3,2）、criticalな`issues`が空であることを合格条件とする。
Supervisor平均7.5はadvisoryであり、低い平均だけを理由に不合格やcritical issueにしない。
高い評価や平均でhard検査・六軸floorを代替することもない。記事とSNSの本人承認は別のままで、SNSのschemaと既存gateは変更しない。

0–10の各評価も実本文への独立した評価として保持する。1–4点を2.5倍する尺度ではない。
目安は0–2=欠如・矛盾、3–4=薄い一般論、5–6=部分的、7–8=継続して具体的で有用、9–10=全体を通じて際立つ強み。
Witは適切で記憶に残る表現、Insightは理解を変える根拠付きの区別、Sincereは根拠に根ざした具体的問題意識、
Empthは簡潔に腹落ちし人へ説明できる内容、AI-freeは定型反復のない自然な文章、Senseは有用な半歩先の角度を見る。
原本の六軸定義と1–4アンカーは変更しない。調査記事・真正な著者体験なしを理由にSincereを自動的に2点へ制限せず、
実際の文章の不足や強みを示す。高評価を保証したり体験・数字を創作したりしない。

`word_count`はAI wireから除外する。既存formatの本文字数範囲内ならprogramが10点を与え、範囲外はhard failとする。
soft目標からの距離で加減点しない。本文の不足や反復は該当する文章評価で扱う。
購入導線／比較表のtyped N/Aは従来どおりstrict nonproduct検証時だけ計算上7.5を寄与させる。
11平均・activeMean・thresholdMetは説明用に厳密計算して保存し、平均の異なる適用範囲間比較や合否の代用にしない。

審査の同じ応答で、最大6件の`improvementFeedback`を返す。wireは
`{criterion, quote, anchor, nextAction}`のみで、AIへparagraph indexを数えさせない。
quoteは1–240字、anchorは1–160字、nextActionは1–400字。programが本文の空行区切り段落／FAQ回答から唯一の完全一致を探し、
保存時に`location={kind:paragraph|faq_answer,index:0始まり}`を付ける。不存在・複数一致・不明schema・AIがlocationを追加した場合は契約エラー。
低いadvisory評価には、実際に低評価となった項目の少なくとも1つに対応する引用付き改善を要求する。commercialでは適用中のaffiliate_links/comparison_tableも対象にできるが、N/Aやprogram由来word_countは対象外とする。criticalな問題をfeedbackだけへ隠さない。
原文全体の再送、追加AI工程、schema feedback loop、自動再試行は作らず、raw応答artifactも変更しない。

v1の算術・7.5合格条件・保存記録検証はversion別の経路で保持する。v2導入で旧reviewを合格換算・上書きしない。
通常Runtimeはbundle直下のversion markerとfinal入力version 3（wire schema／実装hashを含む）で旧cacheを分離する。
本人指定の`evaluation_only`で旧本文をv2評価する場合も、別receiptへ評価結果を保存し、旧履歴・承認・admissionには使わない。

## 通常polishの限定採否

実Gemini応答のschema・型・重複／範囲外indexはfatalのまま。
個々のeditがlocked段落、新しい保護literal／数値、段落境界変更などへ違反した場合は、そのedit全体を棄却して元段落を残す。
他の実応答editだけで作った全候補を`inspect_polish`と既存format字数範囲で検査し、失敗なら採用候補editも全棄却して元sourceを保持する。
通信異常・認証異常を元sourceで成功扱いにするfallbackではない。
`acceptedIndices`・`rejected[{index,reason}]`・`outcome`・`actualResponseId`・`rawResponseAccepted`を候補へ付け、
最終審査のpreservation証拠と保存reviewの`polish.selection`にも残す。`partial`や`no_changes_after_rejection`をraw応答全体の合格と呼ばない。
新Gemini呼出し・架空usage・二重課金記録・counter resetはなく、既存の実呼出し／raw artifact／費用を保持する。

以下は旧v1の経緯・保存互換仕様であり、v2の記事admissionへ旧7.5 gateを再適用しない。

## 実際に起きた不整合

2026-11-20の保存済みClaude審査応答5件を読み取り照合した。以下は旧応答の観測値であり、新しい記事評価ではない。元artifact・台帳・利用量・承認は変更しない。

| 対象 | AIの合格回答 | AIの総合点 | 内訳11項目の実平均 | 比較表の点 |
|---|---|---:|---:|---:|
| ポール初回 | true | 7.5 | 6.909091 | 10 |
| ポール修正後 | true | 7.0 | 7.136364 | 10 |
| Coleman寝袋 | true | 7.5 | 6.545455 | 5 |
| Thermos初回 | false | 6.5 | 6.727273 | 10 |
| Thermos修正後 | true | 7.6 | 6.181818 | 0 |

原因は、AIに項目別の意味評価と総合点の算術・合否を同時に要求していたこと、および非商品記事でも対象外項目に数値回答を必須にし、その値を定義していなかったことである。旧プログラムは内訳平均でこれらを不合格にしていたため、誤った合格回答による公開は行われていない。

これとは別に、実本文には説明の反復、定型表現、独自の切り口の弱さがあった。採点契約の修正で、この本文品質の問題まで解消したとは扱わない。主観的な項目評価のばらつきも、算術修正だけでゼロにはならない。

## 保存互換の旧契約 `article-review-scoring-v1`

AIは、適用される項目の0〜10評価、オーナー原義の六軸1〜4評価、事実等の必須検査、必須修正事項・所見だけを返す。記事用wire schemaには総合`score`と`passed`を持たせない。対象外項目も送受信の数値欄から外す。余分な総合点や対象外の0・5・7.5・10を返した場合は契約違反で停止する。自動再試行は追加しない。

プログラムが適用範囲・合計・合否を決める。空の商品IDだけを根拠に対象外にはしない。検証済みの非商品記事契約（出典、画像、商用導線なし等）の完全検証に通った場合だけ、購入導線と商品比較表をtyped N/Aとする。商用記事はguideを名乗ってもこの2項目を除外できない。N/Aは`measured:false`であり、楽天・Amazon接続や商品比較を測定して合格したという意味ではない。

11項目の枠と7.5以上の基準を維持する。N/Aは計算上だけ7.5を寄与させ、10点の加点や0点の減点にしない。

```
normalized11Mean = (適用項目の合計 + N/A数 × 7.5) / 11
normalized11Mean >= 7.5 ⇔ 適用項目の平均 >= 7.5
```

この中立性は合否境界についてのもの。表示点は7.5へ寄るため、N/A数の異なる記事同士の単純な点数比較には使わない。`calculation.activeMean`と`normalized11Mean`を分けて保存する。浮動小数の丸めではなく厳密な有理数で閾値を判定する。

合格にはさらに、六軸の下限w≥2/i≥2/s≥2/e≥2/ai≥3/sense≥2、必須の独立証跡、事実・画像・購入導線適用・医療・表示の検査、必須修正事項が空であることが必要。六軸1〜4とSupervisorの0〜10は既存の独立した評価であり、相互換算率を新設しない。

## 保存と再利用

新しい通常制作では、プログラムがbundle直下の`articleReviewScoring`（公開記事本文のmetadataとは別）へ契約versionを付与する。これは記事版fingerprintに含まれ、台帳検証ではversionを省略して旧形式へ戻すことを拒否する。総合点・合否・適用範囲・計算内訳を同じ関数で再計算し、改変を拒否する。

final-reviewの入力versionは2とし、scoring version・applicability・wire schemaを入力keyへ含める。計算と執筆promptの実装hashも依存関係へ含める。旧成功結果を新契約の結果として再利用しない。

旧bundle、旧審査、失敗履歴、利用量、本人承認はそのまま保持する。旧稿を合格へ換算したり、試行カウンタを初期化したりしない。WISE原本とSHA pin、モデル、予算、記事・SNSの本人別承認、SNS用schemaと判定は変更しない。公開やSNS予約の権限は、この計算契約から生じない。

## 本文への追加指示

具体性の執筆promptは[出典に結びついた具体性](editorial-writing-specificity.md)に記載する。同じ上位執筆呼出しの中で節ごとの問いと出典を整理し、Geminiは確定した意味の校正に限定する。新しいAI工程や呼出しは追加しない。

この修正だけで一次資料が十分になるわけではない。資料不足を文字数や資料数の恣意的な閾値で判断する新しい自動holdは作らず、出典・内容の既存検査と意味審査を残す。追加promptの接続と算術のoffline検証は、実モデルによる新本文の品質合格を保証しない。

固定本文のprice/rating表示抑止は、`build_v2_fixed_candidate(job,candidate)`で明示的な新候補を作る。unmarked/v1からv2 markerとcurrent policyへの遷移だけを許可し、本文・brief・元CAS expectedRevisionは不変、新candidateRevisionを固定する。review関数内でmetadataを後付けしない。既存guardで実ledger保存後にfresh v2 review・独立QA・本人の新候補承認を必要とし、旧reviewを昇格させない。

`editorialLearnings`は公開反応の実測と未検証仮説を含む編集参考であり、商品・著者の事実根拠や因果関係の証明ではない。research/draftへ短い同一注記を加えるだけで、入力の再掲・新AI工程を追加しない。

SNS本文校正とhealth probeは明示的な非記事modeを使い、従来のstrict edit検証を維持する。記事字数boundsや部分採用をSNSへ転用しない。
