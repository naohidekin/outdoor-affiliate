#!/usr/bin/env node
/**
 * ランドネストシェルター初張りの実体験を記事に差し込む
 *
 * landnest-shelter-vs-2room-comparison はタイトルが
 * 「実際に買った僕が本音比較」なのに、これまで購入しただけで張っていな
 * かったため、設営まわりに一次情報が無かった。2026-08の週末に初張りした
 * ので、その内容を入れる。
 *
 * 出典は docs/author-gear.md の「初張りの実体験」。そこに書いていない
 * 具体（キャンプ場名・地名・同行者など）は足さない。「二人で30分」は
 * 誰と張ったかを聞いていないので「大人2人で」に留めてある。
 *
 * 使い方:
 *   node scripts/insert-landnest-firstpitch.mjs           # 内容を表示するだけ
 *   node scripts/insert-landnest-firstpitch.mjs --apply   # 記事に差し込む
 *
 * 2回実行しても重複しない（差し込み済みなら何もしない）。
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.join(path.dirname(fileURLToPath(import.meta.url)), "..");
// フラグを位置引数と取り違えないこと。
// --apply だけ渡したとき process.argv[2] をそのままファイル名にして
// 「--apply が開けません」で落ちた（2026-08-16）
const positional = process.argv.slice(2).filter((x) => !x.startsWith("--"));
const FILE = positional[0] || path.join(ROOT, "data", "articles.json");
const APPLY = process.argv.includes("--apply");

const SECTION = `## ランドネストシェルターの設営は、実際どうだった？

> **結論**: 大人2人で30分。つまずいたのは地面のピンにフレームを差す1か所だけでした。

先に書いておくと、この記事を最初に書いた時点では、僕はまだこの幕を張っていませんでした。買ったのは7月、初張りは8月の週末です。ここからは実際に建ててみて分かったことを足します。

大人2人で、かかった時間は30分でした。ポールが少ないので、どれをどこに使うか迷う時間がありません。**設営が楽ということは、そのまま撤収が楽ということです**。子連れキャンプだと、これが効きます。

引っかかったのは1か所だけでした。地面のピンにフレームを差すとき、フレームが外れやすい。ここは少し慣れが要ります。逆に言えば、僕が詰まったのはそこだけです。テントを建てたことがある人なら簡単ですし、初めてでも説明書を読めば組めます。

### 建ててみて一番ありがたかったのは「左右がない」ことでした

インナーテントは左右どちらにも付けられます。アウターにも向きがありません。「あれ、こっち側だったっけ」が起きない。

これはカタログのスペック表には出てこない部分です。数字で比べているうちは絶対に分かりません。でも設営のストレスって、実際にはこういうところから来ます。僕は10年使ったアメニティドームLを、もう目を瞑ってでも建てられるくらい体が覚えていました。新しい幕に替えると、その蓄積がゼロに戻る。それが正直こわかったんですが、ランドネストシェルターは迷う要素がそもそも少ないので杞憂でした。

もうひとつ、アップライトポールで屋根を大きくせり出せるのが、僕の想像以上でした。その下にキッチンを広げられます。天気が良い日は、そこがリビングになる。**幕体の実寸よりも、ずっと広く使えます**。カタログの床面積だけ見て「思ったより狭いかな」と迷っている方は、ここを計算に入れてください。

### 気になったところも正直に3つ

| 気になった点 | どういう人に効くか |
|---|---|
| ペグダウンの本数が意外と多い | 設営の楽さを最優先している人は、ここだけ想像とギャップがあるかも |
| スカートが地面のコンディション次第で汚れる | 雨予報の日が多い人。撤収時に泥を落とす手間が増えます |
| インナーの奥行きが狭め | 身長が高い人。幅は4人寝られますが、奥行きで窮屈に感じるかもしれません |

スカートは、あること自体は間違いなく良いことです。冬の底冷えが変わります。ただ悪天候だったり地面のコンディションが悪いと、そのぶん汚れる。トレードオフとして受け入れる部分だと思います。

インナーテントの狭さは、我が家では問題になりませんでした。**寝るだけの空間と割り切っているから**です。むしろリビングが広く取れるぶん、僕が寝室に求めるものは減りました。ただ、テント内でゆっくり過ごしたい方や背の高い方は、店頭で一度入ってみることをおすすめします。

`;

const file = path.isAbsolute(FILE) ? FILE : path.resolve(process.cwd(), FILE);
const articles = JSON.parse(fs.readFileSync(file, "utf8"));
const a = articles.find((x) => x.slug === "landnest-shelter-vs-2room-comparison");
if (!a) {
  console.error("記事が見つかりません: landnest-shelter-vs-2room-comparison");
  process.exit(1);
}
if (a.content.includes("ランドネストシェルターの設営は、実際どうだった？")) {
  console.log("すでに差し込み済みです。何もしません");
  process.exit(0);
}

// 「設営が一番簡単なのはどれ？」の直後（次のH2の手前）に入れる。
// 設営の話が続くので流れが切れない
const ANCHOR = "\n## 夏の涼しさ";
const at = a.content.indexOf(ANCHOR);
if (at === -1) {
  console.error("差し込み位置（## 夏の涼しさ）が見つかりません");
  process.exit(1);
}

const before = a.content.length;
const next = a.content.slice(0, at + 1) + SECTION + a.content.slice(at + 1);

console.log(`${a.slug}`);
console.log(`  ${before}字 → ${next.length}字（+${next.length - before}）`);
console.log(`  差し込み位置: 「設営が一番簡単なのはどれ？」の直後`);
console.log(`\n──── 差し込む内容 ────\n${SECTION}────────────────\n`);

if (!APPLY) {
  console.log("書き込むには --apply");
  process.exit(0);
}

a.content = next;
a.updatedAt = new Date().toISOString(); // 進めないと同期のauto-pullで巻き戻る
fs.writeFileSync(file, JSON.stringify(articles, null, 2));
console.log("data/articles.json を更新しました");
console.log("反映: npm run db:sync -- --no-pull");
