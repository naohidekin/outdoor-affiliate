// 記事本文（Markdown）のH2から目次を生成する。
// 見出しアンカーIDはArticleContent側のH2レンダラーと同じ関数で生成し、
// 目次リンクと見出しidが必ず一致するようにする

export interface TocItem {
  id: string;
  text: string;
}

// 見出しテキスト→アンカーID。日本語はそのままidに使える（hrefはブラウザが
// 自動でURLエンコードする）。Markdown装飾と記号だけ落とす
export function headingId(raw: string): string {
  return raw
    .replace(/\[([^\]]*)\]\([^)]*\)/g, "$1") // リンク→テキスト
    .replace(/[*_`~]/g, "") // 強調・コード装飾
    .replace(/\{\{[^}]*\}\}/g, "")
    .trim()
    .replace(/[\s　]+/g, "-")
    .replace(/[#?&%/:"'<>()（）｜|、。！？!]/g, "")
    .slice(0, 64);
}

// H2のみ抽出（H3まで載せると長文記事では目次自体が長大になる）。
// コンポーネントタグ（{{comparison等}}）だけの行は対象外
export function extractToc(content: string): TocItem[] {
  const items: TocItem[] = [];
  for (const m of content.matchAll(/^## +(.+)$/gm)) {
    const text = m[1]
      .replace(/\[([^\]]*)\]\([^)]*\)/g, "$1")
      .replace(/[*_`~]/g, "")
      .trim();
    if (!text) continue;
    items.push({ id: headingId(m[1]), text });
  }
  return items;
}
