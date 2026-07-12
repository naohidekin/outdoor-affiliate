import type { Metadata } from "next";
import { Noto_Sans_JP, Inter } from "next/font/google";
import Script from "next/script";
import "./globals.css";

const notoSansJP = Noto_Sans_JP({
  variable: "--font-noto-sans-jp",
  subsets: ["latin"],
  weight: ["400", "500", "600"],
});

const inter = Inter({
  variable: "--font-inter",
  subsets: ["latin"],
  weight: ["400", "500", "600"],
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
          {`window.dataLayer=window.dataLayer||[];function gtag(){dataLayer.push(arguments);}gtag('js',new Date());gtag('config','G-0F2R4RX636');`}
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
