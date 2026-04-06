# 画像運用ガイドライン

Outdoor Gear Lab で使用する画像のソース・選定基準・管理方式を定める。
Lake & Sky リブランディングにおいては「焚き火の煙が匂ってきそうなリアリティ」と
「白×青×清涼感のデザイン」の両立を最優先する。

---

## ソース優先順位

### 1. 自前撮影（最優先 / 将来）
- 現状ストックなし。今後撮影したものは `public/images/own/` 配下に格納
- 自前画像が増えたら順次差し替え

### 2. Unsplash（CC0、現状の主力）
- ライセンス: Unsplash License（商用利用可、クレジット不要だが**当サイトでは記載**）
- 推奨タグ: `camping`, `tent`, `mountain`, `lake`, `campfire`, `hiking`, `forest`
- 青空 / 湖 / 雪山 / 朝霧 など Lake & Sky の世界観に合うものを優先
- 過度に加工された / インスタ映え過剰な画像は避ける
- next/image の `remotePatterns` に `images.unsplash.com` を追加して直リンク使用
- クレジット表記: 画像直下に小さく `Photo by [name] / Unsplash`

### 3. Pexels（CC0、補助）
- ライセンス: Pexels License（商用 OK・クレジット不要）
- Unsplash で見つからない時の補助
- next/image の `remotePatterns` に `images.pexels.com` を追加

### 4. メーカー公式 / Amazon / 楽天（商品画像）
- products.json の `imageUrl` には**常にこの優先順位で**画像 URL を格納
  1. メーカー公式（スノーピーク・SOTO・ユニフレーム等）
  2. 楽天市場（`thumbnail.image.rakuten.co.jp`）
  3. Amazon
- 商品画像は記事内では情景画像と区別して扱う

---

## 用途別の使い分け

| 用途 | 推奨ソース | サイズ目安 |
|---|---|---|
| 記事カバー | Unsplash 横位置（青系） | 1600×900 |
| H2 セクション冒頭 | Unsplash 縦/横、Pexels | 1200×675 |
| 本文中の情景 | Unsplash | 1200×675 |
| 商品画像 | メーカー公式 / 楽天 / Amazon | 製品ごと |
| 自分の使用感 | 自前撮影（将来） | 1200×900 |

---

## next/image 設定

`next.config.ts` に以下を追加：

```ts
images: {
  remotePatterns: [
    { protocol: 'https', hostname: 'images.unsplash.com' },
    { protocol: 'https', hostname: 'images.pexels.com' },
    { protocol: 'https', hostname: 'thumbnail.image.rakuten.co.jp' },
    { protocol: 'https', hostname: 'image.rakuten.co.jp' },
    { protocol: 'https', hostname: 'm.media-amazon.com' },
    { protocol: 'https', hostname: 'images-na.ssl-images-amazon.com' },
    // メーカー公式（必要に応じて追加）
    { protocol: 'https', hostname: 'www.snowpeak.co.jp' },
    { protocol: 'https', hostname: 'www.shoei.co.jp' }, // 例
  ],
},
```

実装時は既存設定を破壊しないよう merge する。

---

## 一元管理: data/images.json

将来の差し替えを容易にするため、本文内の情景画像は `data/images.json` で
一元管理する設計にする。

```json
{
  "lake-morning-1": {
    "url": "https://images.unsplash.com/photo-xxxxxxx",
    "alt": "朝もやの湖と山並み",
    "credit": "Photo by John Doe / Unsplash",
    "creditUrl": "https://unsplash.com/@johndoe",
    "tags": ["lake", "morning", "mountain"],
    "width": 1600,
    "height": 900
  },
  "campfire-night-1": {
    "url": "https://images.unsplash.com/photo-yyyyyyy",
    "alt": "夜の焚き火",
    "credit": "Photo by Jane Doe / Unsplash",
    "creditUrl": "https://unsplash.com/@janedoe",
    "tags": ["campfire", "night"],
    "width": 1200,
    "height": 675
  }
}
```

### 記法（Markdown 拡張）

```markdown
::img{id="lake-morning-1"}
```

または既存の `![](url)` も併存可。`::img{id="..."}` を使うと将来一括差し替え可能。

### 実装フェーズ

1. `data/images.json` を新規作成（最初は 5〜10 枚）
2. `src/components/Img.tsx` 作成（id ベースで images.json から解決）
3. `ArticleContent.tsx` に `::img{...}` パーサー追加
4. サンプル記事刷新時に投入

---

## デザイン上のルール（Lake & Sky）

- 角丸: `rounded-lg`（控えめ）
- 影: 使わない or 極薄（`shadow-none` / `shadow-sm` まで）
- カバー画像は記事タイトル直上、フル幅 or max-w で揃える
- キャプション: `text-xs text-slate-500` で出典を併記
- 青系の世界観を崩す画像（強い夕焼け / オレンジ調モロ出し）は避ける

## クレジット表記フォーマット

```
Photo by [Author Name] / Unsplash
Photo by [Author Name] / Pexels
画像提供: スノーピーク公式
```

リンクを付ける場合：

```html
<a href="https://unsplash.com/@johndoe" rel="nofollow noopener">
  Photo by John Doe / Unsplash
</a>
```

## NG

- 出典不明画像
- 他の個人ブログ / SNS からのスクレイピング
- 透かしなし商用ストック画像（getty 等）の無断使用
- 過度なフィルター・色加工で世界観を変える
- 子ども顔出し画像（プライバシー）
