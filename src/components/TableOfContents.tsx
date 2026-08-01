import { TocItem } from "@/lib/toc";

// 記事の目次。<details>ベースでJS不要（Server Componentのまま動く）。
// モバイルの長文で邪魔にならないよう折りたたみを既定にし、
// 見出し4本未満の短い記事ではページ側で表示自体を省く
export default function TableOfContents({ items }: { items: TocItem[] }) {
  if (items.length === 0) return null;
  return (
    <details className="my-6 rounded-xl border border-line bg-mist/60 open:bg-white transition-colors group">
      <summary className="cursor-pointer px-5 py-3.5 text-sm font-semibold text-ink-strong flex items-center gap-2 list-none">
        <span className="text-lake-600">📑</span>
        <span>目次</span>
        <span className="ml-auto text-lake-600 text-xs group-open:rotate-180 transition-transform">
          ▼
        </span>
      </summary>
      <ol className="px-5 pb-4 pt-1 space-y-1.5">
        {items.map((item, i) => (
          <li key={item.id + i} className="text-sm leading-snug">
            <a
              href={`#${item.id}`}
              className="text-slate-600 hover:text-lake-700 hover:underline underline-offset-2 transition flex gap-2"
            >
              <span className="text-lake-400 tabular-nums shrink-0">
                {String(i + 1).padStart(2, "0")}
              </span>
              <span>{item.text}</span>
            </a>
          </li>
        ))}
      </ol>
    </details>
  );
}
