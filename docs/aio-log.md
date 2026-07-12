# AIO（AI検索最適化）施策ログ・効果測定

camp-gear-lab.com のAIO/LLMO対策の実施記録と月次ベースライン。
月1回、GA4「AI Assistant」チャネル・Search Console・アフィリ発生額を追記する。

## ベースライン（施策直後・2026-07-12記録）

GA4 トラフィック獲得（直近28日 = 6/14〜7/11、施策**前**の自然状態）:

| チャネル | セッション | 構成比 | エンゲージメント率 | 平均滞在 |
|---|---|---|---|---|
| Organic Search | 742 | 72.9% | 63.1% | 1分14秒 |
| **AI Assistant** | **106** | **10.4%** | 50.0% | 25秒 |
| Direct | 102 | 10.0% | 31.4% | 17秒 |
| Organic Social | 29 | 2.9% | 72.4% | 48秒 |

- **AI Assistantはすでに全流入の1割・第2チャネル**（施策前から）
- AI経由は滞在が短い＝「AIの回答で概要を得て確認しに来る」行動。結論ボックスと商品ボタンの初速が重要

## 実施済み施策（2026-07-12 第1弾・第2弾）

1. **エンティティ統一**: サイト名 Camp Gear Lab / 著者「ギア男（現役小児科開業医）」に全面統一。
   Person schema に sameAs（X・楽天ROOM）/ worksFor / knowsAbout、ホームに Organization JSON-LD 追加
2. **/llms.txt** 新設（カテゴリ別主要記事の動的Markdown索引）
3. **回答チャンク**: 旗艦5記事に `> **結論**:` 即答ボックス＋質問形H2。
   article-writer と CLAUDE.md にAIOルールを恒久化（以後の新記事は自動適用）
4. **FAQ構造化データ**: FAQゼロ3記事を解消、主要記事を5問体制に。本文FAQ/配列FAQの二重表示も解消
5. **一次情報注入**: docs/author-gear.md 正典準拠の実体験を9記事に注入。
   正典外の捏造体験（未所有ギア使用談・具体地名）を3記事で無害化
6. **計測**: GA4標準「AI Assistant」チャネルで測定（Google自動メンテ。自作セグメント不要と判明）。
   Vercel Firewall は AI Bots = Allow を確認済み
7. **Bing Webmaster Tools 登録**（2026-07-12）: GSCインポートで所有権・sitemap引き継ぎ。
   sitemap.xml 成功・検出URL 128件・エラー0。ChatGPT/Copilot検索はBingインデックス依存のため必須の導線。
   「AI Performance（ベータ）」でAI回答内の引用数を月次確認する（DNSはVercel直結でCloudflare不使用＝AI Crawl Control対象外）
8. **IndexNow 組み込み**（2026-07-12）: article-daily の公開処理に即時通知を追加
   （Google Indexing API と並走）。キーファイルは public/ でホスト。
   初回シード・大量リライト後は `npm run indexnow:all` で全URL一括送信

## 月次記録

| 記録日 | 期間 | AI Assistantセッション | Organicセッション | SC表示回数 | メモ |
|---|---|---|---|---|---|
| 2026-07-12 | 6/14〜7/11 | 106 (10.4%) | 742 | — | ベースライン（施策前） |

## 実測に基づく改修（2026-07-12 第3弾・第4弾）

GA4「AI Assistant × ランディングページ」で、AIが実際に入口にしている記事が判明。
「AIに選ばれているのに体温ゼロ・エンゲージ低」の記事を優先改修する方針に切替。

- **AIに選ばれるのは全部ランキング型記事**（TOP20が「〜おすすめ・ランキング」で占有）→ 新記事もランキング型が本線
- **第3弾（6本）**: solo-tent / rainwear / duo-tent / budget-sleeping-bag / insect-repellent-spray / trekking-shoes
  に結論ボックス・質問形H2・FAQ点検・正典準拠の体温注入
- **第4弾（2本）**: エンゲージ率0%だった cooler-box（医師の食中毒視点＋グロウラー）、
  camping-beginner-gear-checklist（アメドL/偽ヘリ/キャプスタの入門ストーリー）を豪華化。FAQも各5〜6問に
- landlock-vs-landnest-shelter（17位・0%）は32,000字・FAQ10・一人称20の既完成記事のため**温存**（0%はサンプル1の統計ノイズと判断）

## 次の一手（判断待ち）

- [ ] 第3弾: 質問形H2＋結論ボックスの全記事展開（効果確認後）
- [x] IndexNow組み込み（2026-07-12完了）
- [ ] 用語集・「〜とは」ハブページ（AIの定義引用の受け皿）
- [ ] 一次情報の続き: 一人称ゼロ記事 約55本のうち、正典で書ける実話がある収益上位から
- [ ] 廃番4商品の記事リライト（ロゴス枕・スノーピーク ドライネット・BUNDOK・サーマレスト枠）
