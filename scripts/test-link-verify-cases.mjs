#!/usr/bin/env node
/**
 * verify-links.mjs の判定を、実際に出た16件で回帰テストする
 *
 * 2026-08-14 の初回実行で「別商品の疑い」16件が出たが、目視すると
 * 9件はカタカナ／英語の表記ゆれによる誤検出だった。判定を直したあと
 * 「誤検出9件が消え、本物の誤リンク4件は残る」ことをAPIを叩かずに確かめる。
 * 期待値は当時のストア側タイトル（実データ）で固定してある。
 *
 *   FP  … 誤検出。ブランドは合っており、疑いから外れてほしい
 *   BAD … 本物の誤リンク。疑いとして残ってほしい
 *   ??  … 目視でも判断が割れるもの。判定は問わない（変化の記録だけ）
 *
 *   node scripts/test-link-verify-cases.mjs
 */
import { tokenOverlap, normalizeBrands, brandMatches } from "../src/lib/product-match.mjs";

// verify-links.mjs の matchScore と同じ（あちらは対象の絞り込みと
// API呼び出しが本体なので、判定部分だけをここに写して検証する）
function matchScore(productName, storeTitle) {
  const norm = (x) => normalizeBrands((x || "").normalize("NFKC").toLowerCase());
  const rawSrc = (productName || "").normalize("NFKC");
  const raw = rawSrc.match(/[A-Za-z]{1,6}-?[0-9]{2,5}[A-Za-z0-9+/]*/g) || [];
  const titleSrc = (storeTitle || "").normalize("NFKC");
  const modelHit = raw.some((m) => {
    const esc = m.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    return new RegExp(`(?<![A-Za-z0-9-])${esc}(?![A-Za-z0-9])`, "i").test(titleSrc);
  });
  if (modelHit) return 1;
  return tokenOverlap(norm(productName), norm(storeTitle));
}

const isSuspect = (name, brand, title) => matchScore(name, title) < 0.4 && !brandMatches(brand, title);

// [期待, id, 商品名, brandフィールド, ストア側タイトル]
const CASES = [
  ["FP", "burner-m-002", "スノーピーク ホームアンドキャンプバーナー GS-600", "スノーピーク",
    "スノーピーク(snow peak) HOME&CAMPバーナー"],
  ["FP", "pillow-nemo-fillo-elite", "NEMO フィロ エリート", "NEMO",
    "Nemo Equipment Fillo Elite 超軽量 バックパッキングピロー - ブラック"],
  ["FP", "shoes-002", "メレル モアブ3ミッド ゴアテックス", "MERRELL",
    "MERRELL(メレル) メンズ MOAB 3 SYNTHETIC MID GORE-TEX"],
  ["FP", "rakuten-poncotan-10000531", "ポンコタン 軽量折りたたみアウトドアチェア", "アウトドアチェア【ポンコタン】",
    "【 PONCOTAN 歴代最高のアウトドアチェア 】ウルトラライトフィットチェア2.0 ワイド"],
  ["FP", "trash-box-coleman", "コールマン ポップアップボックス コヨーテ 2000038938", "コールマン",
    "Coleman(コールマン) ポップアップボックス アウトドア キャンプ ゴミ箱 トラッシュ"],
  ["FP", "hammock-eno-doublenest", "ENO DoubleNest Hammock（ダブルネストハンモック）", "Eagles Nest Outfitters",
    "eno(イノー) ダブルネスト ハンモック レッド/チャコール DH004"],
  ["FP", "light-003", "ルーメナー2 LUMENA2", "LUMENA",
    "(ルーメナー2) LUMENAⅡ 防水・防塵・耐衝撃 バッテリー機能付き LEDランタン"],
  ["FP", "peg-hammer-captainstag", "キャプテンスタッグ 鍛造ペグ抜きハンマー UA-4516", "キャプテンスタッグ",
    "CAPTAIN STAG(キャプテンスタッグ) 鍛造 ペグ抜きハンマー"],
  // 当初は誤検出（FP）に分類したが、調べたら登録ブランドは ESTOAH.home で
  // リンク先はアイモニカ。表記ゆれではなく本当に別の出品者の商品なので、
  // 疑いに残るのが正しい。無銘のブルーシートなので実害は小さいが、
  // 疑いから外すために判定を緩めるのは筋が違う
  ["??", "tent-009", "厚手ブルーシート 3.6m×5.4m（#3000）", "ESTOAH.home エストアホーム",
    "アイモニカ ブルーシート #3000 厚手 1.8×1.8～10×10 (3.6×5.4)"],

  ["BAD", "fire-blower-fireside80", "ファイヤーサイド ファイヤーブラスター80 FB2", "ファイヤーサイド",
    "Redecker(レデッカー) ファイヤーブロアー (火吹き筒 火吹き棒 ひふきぼう) 60"],
  ["BAD", "tarp-008", "DARCHE ECLIPSE AWNING 車用オーニングタープ", "DARCHE",
    "XiaZ 日除けシェード 2層撥水防水加工 雨よけ 防水サンシェード 400Dポリエステル"],
  ["BAD", "tarp-007", "ロゴス USBシェードランタン（4連タイプ）", "ロゴス",
    "LACITA LEDランタン ポータブル 13,400mAh 充電式 キャンプ アウトドア"],
  ["BAD", "fp-006", "スノーピーク 焚火台 L", "スノーピーク",
    "キャプテンスタッグ アルミ ロールテーブル (コンパクト) M-3713"],

  ["??", "fan-socool", "Socool fan キャンプ扇風機", "Socool fan",
    "キャンプ 扇風機 20000mAh大容量 最大60時間連続使用 Type-C充電式 吊り下げ"],
  ["??", "knife-002", "モーラナイフ Garberg Full Tang", "Morakniv",
    "モーラナイフ ガーバーグ スタンダード ステンレス Morakniv | ナイフ キャンプナ"],
  ["??", "rakuten-mystic-r-10000076", "Mystic Ridge 折りたたみ焚き火台（ソロ用・ステンレス）", "Mystic Ridge 楽天市場店",
    "【選ばれて23冠／レビュー1000件超！楽天1位】 焚火台 焚き火台 コンパクト ソロ キャ"],
];

let fail = 0;
for (const [expect, id, name, brand, title] of CASES) {
  const score = matchScore(name, title);
  const bhit = brandMatches(brand, title);
  const suspect = isSuspect(name, brand, title);
  const want = expect === "FP" ? false : expect === "BAD" ? true : suspect;
  const ok = suspect === want;
  if (!ok) fail++;
  const mark = expect === "??" ? "－" : ok ? "✅" : "❌";
  console.log(
    `${mark} ${expect.padEnd(4)} ${id.padEnd(26)} 一致${String(Math.round(score * 100)).padStart(3)}%` +
      `  ブランド${bhit ? "一致" : "不一致"}  → ${suspect ? "疑いに残す" : "疑いから外す"}`
  );
}

console.log(`\n${CASES.length}件中 ${fail}件が期待と違います`);
process.exit(fail === 0 ? 0 : 1);
