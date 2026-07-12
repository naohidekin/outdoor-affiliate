import Link from "next/link";
import { Category } from "@/lib/types";
import { Mountain } from "lucide-react";
import MobileMenu from "./MobileMenu";

export default function Header({ categories }: { categories: Category[] }) {
  return (
    <header className="bg-white/90 backdrop-blur-md border-b border-line sticky top-0 z-50">
      <div className="max-w-6xl mx-auto px-4">
        <div className="flex items-center justify-between h-16">
          <Link href="/" className="flex items-center gap-2 group">
            <Mountain className="w-6 h-6 text-lake-600" strokeWidth={2} />
            <span className="text-lg font-semibold tracking-tight text-ink-strong">
              Camp Gear Lab
            </span>
          </Link>
          <nav className="hidden md:flex items-center gap-1">
            {categories.slice(0, 6).map((c) => (
              <Link
                key={c.id}
                href={`/category/${c.slug}`}
                className="text-sm text-slate-600 hover:text-lake-600 transition px-3 py-2 rounded-lg hover:bg-lake-50 font-medium"
              >
                {c.name}
              </Link>
            ))}
            <Link
              href="/about"
              className="text-sm text-slate-600 hover:text-lake-600 transition px-3 py-2 rounded-lg hover:bg-lake-50 font-medium"
            >
              About
            </Link>
          </nav>
          <MobileMenu categories={categories} />
        </div>
      </div>
    </header>
  );
}
