import Link from "next/link";
import { Mountain } from "lucide-react";

/**
 * 英語セクションのヘッダ・フッタ。
 *
 * 日本語版の Header/Footer を流用しない。カテゴリナビは日本語記事へ
 * 誘導してしまい、英語で来た読者を行き止まりに送るため。
 * 見た目のトークン（lake / ink / line）は共通のものを使う。
 */

const NAV = [
  { href: "/en/tools/snow-peak-igt-model-finder", label: "Model Finder" },
  { href: "/en/guides/snow-peak-igt-model-numbers", label: "Guide" },
  { href: "/en/methodology", label: "Methodology" },
];

export function EnHeader() {
  return (
    <header className="bg-white/90 backdrop-blur-md border-b border-line sticky top-0 z-50">
      <div className="max-w-4xl mx-auto px-4">
        <div className="flex items-center justify-between h-16 gap-4">
          <Link
            href="/en"
            className="flex items-center gap-2 rounded-lg focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-lake-600"
          >
            <Mountain className="w-6 h-6 text-lake-600 shrink-0" strokeWidth={2} />
            <span className="text-base sm:text-lg font-semibold tracking-tight text-ink-strong">
              Camp Gear Lab
            </span>
          </Link>
          <nav aria-label="English section" className="flex items-center gap-1">
            {NAV.map((item) => (
              <Link
                key={item.href}
                href={item.href}
                className="text-sm text-slate-600 hover:text-lake-600 hover:bg-lake-50 transition px-2 sm:px-3 py-2 rounded-lg font-medium focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-lake-600"
              >
                {item.label}
              </Link>
            ))}
          </nav>
        </div>
      </div>
    </header>
  );
}

export function EnFooter() {
  return (
    <footer className="bg-white border-t border-line mt-auto">
      <div className="max-w-4xl mx-auto px-4 py-10 text-sm text-slate-600 space-y-4">
        <p className="leading-relaxed">
          This is a small English experiment on{" "}
          <span className="text-ink-strong font-medium">Camp Gear Lab</span>, a
          Japanese outdoor gear comparison site. It covers Snow Peak IGT model
          numbers only. Everything here is sourced from official Snow Peak
          documentation, and anything we cannot confirm is marked as unknown.
        </p>
        <ul className="flex flex-wrap gap-x-5 gap-y-2">
          <li>
            <Link
              href="/en/methodology"
              className="text-lake-600 hover:text-lake-700 underline underline-offset-2 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-lake-600 rounded"
            >
              Methodology
            </Link>
          </li>
          <li>
            <Link
              href="/en/affiliate-disclosure"
              className="text-lake-600 hover:text-lake-700 underline underline-offset-2 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-lake-600 rounded"
            >
              Affiliate disclosure
            </Link>
          </li>
          <li>
            <Link
              href="/"
              className="text-slate-500 hover:text-lake-600 underline underline-offset-2 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-lake-600 rounded"
            >
              日本語サイト（Japanese site）
            </Link>
          </li>
        </ul>
        <p className="text-xs text-slate-400 pt-2 border-t border-line-soft">
          Snow Peak is a trademark of its respective owner. Camp Gear Lab is not
          affiliated with, endorsed by, or sponsored by Snow Peak.
        </p>
      </div>
    </footer>
  );
}

/**
 * 最初の販売リンクより前に出す短い開示。
 * 広告に接する前に認識できる位置に置くのが安全側（日本語版と同じ考え方）。
 */
export function EnInlineDisclosure() {
  return (
    <p className="text-xs text-slate-500 flex items-start gap-2">
      <span className="font-medium text-slate-600 border border-line-soft rounded px-1.5 py-0.5 shrink-0">
        Ad
      </span>
      <span className="pt-0.5">
        Some purchase links on this page are affiliate links.{" "}
        <Link
          href="/en/affiliate-disclosure"
          className="text-lake-600 hover:text-lake-700 underline underline-offset-2 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-lake-600 rounded"
        >
          Read the disclosure
        </Link>
        .
      </span>
    </p>
  );
}
