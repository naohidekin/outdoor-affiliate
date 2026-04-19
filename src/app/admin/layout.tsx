"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useState } from "react";

const navItems = [
  { href: "/admin", label: "ダッシュボード", icon: "📊" },
  { href: "/admin/articles", label: "記事管理", icon: "📝" },
  { href: "/admin/products", label: "商品管理", icon: "📦" },
  { href: "/admin/categories", label: "カテゴリ管理", icon: "🏷️" },
  { href: "/admin/x-posts", label: "X 投稿管理", icon: "𝕏" },
  { href: "/admin/x-analytics", label: "X Analytics", icon: "📈" },
  { href: "/admin/4koma", label: "4コマ漫画", icon: "🎨" },
];

export default function AdminLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const [open, setOpen] = useState(false);

  if (pathname === "/admin/login") {
    return <>{children}</>;
  }

  async function handleLogout() {
    await fetch("/api/auth", { method: "DELETE" });
    router.push("/admin/login");
  }

  return (
    <div className="min-h-screen flex bg-gray-50">
      {/* Mobile overlay */}
      {open && (
        <div
          className="fixed inset-0 bg-black/50 z-20 lg:hidden"
          onClick={() => setOpen(false)}
        />
      )}

      {/* Sidebar */}
      <aside
        className={`fixed inset-y-0 left-0 z-30 w-64 bg-gray-900 text-white flex flex-col transition-transform duration-200 lg:relative lg:translate-x-0 lg:z-auto ${
          open ? "translate-x-0" : "-translate-x-full"
        }`}
      >
        <div className="p-6 border-b border-gray-700 flex items-center justify-between">
          <div>
            <Link href="/" className="text-lg font-bold text-green-400">
              🏕️ Outdoor Affiliate
            </Link>
            <p className="text-xs text-gray-400 mt-1">管理画面</p>
          </div>
          <button
            className="lg:hidden text-gray-400 hover:text-white p-1 text-lg leading-none"
            onClick={() => setOpen(false)}
            aria-label="閉じる"
          >
            ✕
          </button>
        </div>
        <nav className="flex-1 p-4 space-y-1 overflow-y-auto">
          {navItems.map((item) => (
            <Link
              key={item.href}
              href={item.href}
              onClick={() => setOpen(false)}
              className={`flex items-center gap-3 px-4 py-3 rounded-lg transition text-sm ${
                pathname === item.href
                  ? "bg-green-600 text-white"
                  : "text-gray-300 hover:bg-gray-800"
              }`}
            >
              <span>{item.icon}</span>
              {item.label}
            </Link>
          ))}
        </nav>
        <div className="p-4 border-t border-gray-700">
          <button
            onClick={handleLogout}
            className="w-full text-left px-4 py-2 text-sm text-gray-400 hover:text-white transition"
          >
            ログアウト
          </button>
          <Link
            href="/"
            className="block px-4 py-2 text-sm text-gray-400 hover:text-white transition"
          >
            サイトを表示 →
          </Link>
        </div>
      </aside>

      {/* Main */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* Mobile top bar */}
        <header className="lg:hidden bg-gray-900 text-white px-4 py-3 flex items-center gap-3 sticky top-0 z-10">
          <button
            onClick={() => setOpen(true)}
            className="p-2 rounded-lg hover:bg-gray-800 transition text-xl leading-none"
            aria-label="メニューを開く"
          >
            ☰
          </button>
          <Link href="/" className="text-base font-bold text-green-400">
            🏕️ Outdoor Affiliate
          </Link>
        </header>
        <main className="flex-1 p-4 lg:p-8 overflow-auto">{children}</main>
      </div>
    </div>
  );
}
