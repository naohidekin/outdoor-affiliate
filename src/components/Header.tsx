import Link from "next/link";
import { Category } from "@/lib/types";
import { Mountain } from "lucide-react";

export default function Header({ categories }: { categories: Category[] }) {
  return (
    <header className="bg-white/90 backdrop-blur-md border-b border-gray-200/60 sticky top-0 z-50">
      <div className="max-w-6xl mx-auto px-4">
        <div className="flex items-center justify-between h-16">
          <Link href="/" className="flex items-center gap-2 group">
            <Mountain className="w-6 h-6 text-[#4a6741]" strokeWidth={2.5} />
            <span className="text-lg font-bold tracking-tight text-[#3d2b1f]" style={{ fontFamily: 'var(--font-heading)' }}>
              Outdoor Gear Lab
            </span>
          </Link>
          <nav className="hidden md:flex items-center gap-1">
            {categories.slice(0, 6).map((c) => (
              <Link
                key={c.id}
                href={`/category/${c.slug}`}
                className="text-sm text-gray-600 hover:text-[#4a6741] transition px-3 py-2 rounded-lg hover:bg-[#4a6741]/5 font-medium"
              >
                {c.name}
              </Link>
            ))}
          </nav>
        </div>
      </div>
    </header>
  );
}
