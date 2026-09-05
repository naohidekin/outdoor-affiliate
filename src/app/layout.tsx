import type { Metadata } from "next";
import { Noto_Sans_JP, Inter } from "next/font/google";
import Script from "next/script";
import "./globals.css";

// weightを個別指定すると日本語の~124 unicode-range分割×ウェイト数の@font-face宣言が
// 全てレンダリングブロッキングCSSに入る（3ウェイトで276KB）。両フォントとも可変フォント
// なのでweight未指定（可変軸）にして宣言を1/3に削減する。描画結果は同一。
const notoSansJP = Noto_Sans_JP({
  variable: "--font-noto-sans-jp",
  subsets: ["latin"],
});

const inter = Inter({
  variable: "--font-inter",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: {
    default: "Camp Gear Lab | アウトドア用品比較・レビュー",
    template: "%s | Camp Gear Lab",
  },
  description:
    "アウトドア用品を徹底比較。テント、シュラフ、バーナー、バックパックなど、キャンプ・登山ギアのリアルなレビューと比較情報をお届けします。",
  openGraph: {
    type: "website",
    locale: "ja_JP",
    siteName: "Camp Gear Lab",
    url: "https://camp-gear-lab.com",
  },
  twitter: {
    card: "summary_large_image",
  },
  verification: {
    google: "zAQk515bMuad6zmJvPSPmwfOVogJ394b9wqDTKlurGI",
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
      className={`${notoSansJP.variable} ${inter.variable} h-full antialiased`}
    >
      <head>
        {/* LCP画像は外部CDN（商品画像・Unsplash）から来るため、接続確立
            （DNS+TCP+TLS）を前倒しする。1オリジンあたり100〜300msの短縮 */}
        <link rel="preconnect" href="https://m.media-amazon.com" crossOrigin="" />
        <link rel="preconnect" href="https://thumbnail.image.rakuten.co.jp" crossOrigin="" />
        <link rel="preconnect" href="https://images.unsplash.com" crossOrigin="" />
        <link rel="dns-prefetch" href="https://shop.r10s.jp" />
        <link rel="dns-prefetch" href="https://www.googletagmanager.com" />
        <link
          rel="alternate"
          type="application/rss+xml"
          title="Camp Gear Lab"
          href="https://camp-gear-lab.com/feed"
        />
      </head>
      <body className="min-h-full flex flex-col bg-snow text-ink">
        {children}
        <Script
          src="https://www.googletagmanager.com/gtag/js?id=G-0F2R4RX636"
          strategy="afterInteractive"
        />
        <Script id="ga-init" strategy="afterInteractive">
          {`window.dataLayer=window.dataLayer||[];function gtag(){dataLayer.push(arguments);}gtag('js',new Date());gtag('config','G-0F2R4RX636');window.dispatchEvent(new Event('camp-analytics-ready'));`}
        </Script>
        {/* バリューコマース LinkSwitch: shopping.yahoo.co.jp への直リンクを
            クリック時にアフィリエイトリンクへ自動変換する */}
        <Script id="vc-pid" strategy="afterInteractive">
          {`var vc_pid = "892651120";`}
        </Script>
        <Script
          src="https://aml.valuecommerce.com/vcdal.js"
          strategy="afterInteractive"
        />
      </body>
    </html>
  );
}
