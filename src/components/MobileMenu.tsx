"use client";

import { useRef, useState } from "react";
import Link from "next/link";
import { Menu, X } from "lucide-react";

interface MobileMenuProps {
  categories: { id: string; slug: string; name: string }[];
}

export default function MobileMenu({ categories }: MobileMenuProps) {
  const [open, setOpen] = useState(false);
  const toggleRef = useRef<HTMLButtonElement>(null);

  return (
    <div className="lg:hidden" onKeyDown={(event) => {
      if (event.key === "Escape") {
        setOpen(false);
        toggleRef.current?.focus();
      }
    }}>
      <button
        ref={toggleRef}
        onClick={() => setOpen(!open)}
        className="p-2 text-slate-600 hover:text-lake-600 transition"
        aria-label={open ? "メニューを閉じる" : "メニューを開く"}
        aria-expanded={open}
        aria-controls="mobile-navigation"
      >
        {open ? <X className="w-5 h-5" /> : <Menu className="w-5 h-5" />}
      </button>
      {open && (
        <nav id="mobile-navigation" aria-label="メインナビゲーション" className="absolute top-16 left-0 right-0 bg-white border-b border-line shadow-lg z-50 max-h-[calc(100dvh-4rem)] overflow-y-auto">
          <div className="max-w-6xl mx-auto px-4 py-3 grid grid-cols-2 gap-1 border-b border-line-soft">
            {[
              { href: "/#gear-guides", label: "ギアを選ぶ" },
              { href: "/#field-notes", label: "使った道具の記録" },
              { href: "/articles", label: "記事を探す" },
              { href: "/about", label: "書き手について" },
            ].map((item) => <Link key={item.href} href={item.href} onClick={() => setOpen(false)} className="text-sm font-medium text-lake-700 px-3 py-3 rounded-lg hover:bg-lake-50">{item.label}</Link>)}
          </div>
          <div className="max-w-6xl mx-auto px-4 py-3 grid grid-cols-2 gap-1">
            {categories.map((c) => (
              <Link
                key={c.id}
                href={`/category/${c.slug}`}
                onClick={() => setOpen(false)}
                className="text-sm text-slate-600 hover:text-lake-600 transition px-3 py-2.5 rounded-lg hover:bg-lake-50 font-medium"
              >
                {c.name}
              </Link>
            ))}
          </div>
        </nav>
      )}
    </div>
  );
}
