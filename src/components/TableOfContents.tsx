import { TocItem } from "@/lib/toc";
import { List, ChevronDown } from "lucide-react";

// 記事の目次。<details>ベースでJS不要（Server Componentのまま動く）。
// モバイルの長文で邪魔にならないよう折りたたみを既定にし、
// 見出し4本未満の短い記事ではページ側で表示自体を省く
export default function TableOfContents({ items }: { items: TocItem[] }) {
  if (items.length === 0) return null;
  return (
    <details id="article-toc" className="my-6 scroll-mt-20 rounded-xl border border-line bg-mist/60 open:bg-white transition-colors group">
      <summary className="cursor-pointer min-h-14 px-4 py-3.5 text-sm font-semibold text-ink-strong flex items-center gap-3 list-none">
        <List size={18} className="text-lake-600" aria-hidden="true" />
        <span>目次</span>
        <ChevronDown size={18} className="ml-auto text-lake-600 group-open:rotate-180 transition-transform" aria-hidden="true" />
      </summary>
      <ol className="px-4 pb-4 pt-1 divide-y divide-line-soft">
        {items.map((item, i) => (
          <li key={item.id + i} className="text-sm leading-snug">
            <a
              href={`#${item.id}`}
              className="text-slate-600 hover:text-lake-700 transition flex items-start gap-3 min-h-11 py-3 leading-relaxed"
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
