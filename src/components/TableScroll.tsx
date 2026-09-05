import type { ReactNode } from "react";
import { MoveHorizontal } from "lucide-react";

export default function TableScroll({ children, label = "比較表" }: { children: ReactNode; label?: string }) {
  return (
    <div className="table-shell my-7 min-w-0 overflow-hidden rounded-xl border border-line bg-white">
      <div className="flex items-center gap-2 border-b border-line-soft px-4 py-3 text-xs text-slate-600">
        <MoveHorizontal size={16} aria-hidden="true" />
        横にスクロールして比較できます
      </div>
      <div className="table-scroll" role="region" aria-label={`${label}（横スクロール）`} tabIndex={0}>
        {children}
      </div>
    </div>
  );
}
