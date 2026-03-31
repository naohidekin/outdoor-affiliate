import Link from "next/link";
import { Category } from "@/lib/types";

export default function Header({ categories }: { categories: Category[] }) {
  return (
    <header className="bg-amber-50 border-b border-amber-200 sticky top-0 z-50 shadow-sm">
      <div className="max-w-6xl mx-auto px-4">
        <div className="flex items-center justify-between h-16">
          <Link href="/" className="flex items-center gap-2 text-xl font-bold text-amber-900">
            <span className="text-2xl">⛺</span>
            <span>Outdoor Gear Lab</span>
          </Link>
          <nav className="hidden md:flex items-center gap-6">
            {categories.slice(0, 6).map((c) => (
              <Link
                key={c.id}
                href={`/category/${c.slug}`}
                className="text-sm text-amber-800 hover:text-green-700 transition font-medium"
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
