"use client";

import { useState } from "react";
import Link from "next/link";
import { Menu, X } from "lucide-react";

interface MobileMenuProps {
  categories: { id: string; slug: string; name: string }[];
}

export default function MobileMenu({ categories }: MobileMenuProps) {
  const [open, setOpen] = useState(false);

  return (
    <div className="md:hidden">
      <button
        onClick={() => setOpen(!open)}
        className="p-2 text-slate-600 hover:text-lake-600 transition"
        aria-label="メニュー"
      >
        {open ? <X className="w-5 h-5" /> : <Menu className="w-5 h-5" />}
      </button>
      {open && (
        <nav className="absolute top-16 left-0 right-0 bg-white border-b border-line shadow-lg z-50">
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
