// JSON-LDを<script>タグへ埋め込むためのシリアライザ。
// 記事タイトルや口コミに "</script>" 等が混入してもHTMLとして解釈されないよう
// "<" を Unicodeエスケープ（バックスラッシュ+u003c）に置換する
// （JSONとしては等価なのでスキーマには影響しない）
export function toJsonLd(data: unknown): string {
  return JSON.stringify(data).replace(/</g, "\\u003c");
}
