import Link from "next/link";
import { Category } from "@/lib/types";

export default function Header({ categories }: { categories: Category[] }) {
  return (
    <header className="bg-white border-b sticky top-0 z-50">
      <div className="max-w-6xl mx-auto px-4">
        <div className="flex items-center justify-between h-16">
          <Link href="/" className="text-xl font-bold text-green-700">
            Outdoor Gear Lab
          </Link>
          <nav className="hidden md:flex items-center gap-6">
            {categories.slice(0, 6).map((c) => (
              <Link
                key={c.id}
                href={`/category/${c.slug}`}
                className="text-sm text-gray-600 hover:text-green-600 transition"
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
