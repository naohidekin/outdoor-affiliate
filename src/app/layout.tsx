import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: {
    default: "Outdoor Gear Lab | アウトドア用品比較・レビュー",
    template: "%s | Outdoor Gear Lab",
  },
  description:
    "アウトドア用品を徹底比較。テント、シュラフ、バーナー、バックパックなど、キャンプ・登山ギアのリアルなレビューと比較情報をお届けします。",
  openGraph: {
    type: "website",
    locale: "ja_JP",
    siteName: "Outdoor Gear Lab",
    url: "https://camp-gear-lab.com",
  },
  twitter: {
    card: "summary_large_image",
  },
  metadataBase: new URL("https://camp-gear-lab.com"),
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="ja"
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
    >
      <body className="min-h-full flex flex-col bg-gray-50">{children}</body>
    </html>
  );
}
