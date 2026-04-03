import type { Metadata } from "next";
import { Noto_Sans_JP, DM_Sans } from "next/font/google";
import "./globals.css";

const notoSansJP = Noto_Sans_JP({
  variable: "--font-noto-sans-jp",
  subsets: ["latin"],
  weight: ["400", "500", "700"],
});

const dmSans = DM_Sans({
  variable: "--font-dm-sans",
  subsets: ["latin"],
  weight: ["400", "500", "700"],
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
      className={`${notoSansJP.variable} ${dmSans.variable} h-full antialiased`}
    >
      <head>
        <link
          rel="alternate"
          type="application/rss+xml"
          title="Outdoor Gear Lab"
          href="https://camp-gear-lab.com/feed"
        />
        <script
          async
          src="https://www.googletagmanager.com/gtag/js?id=G-0F2R4RX636"
        />
        <script
          dangerouslySetInnerHTML={{
            __html: `window.dataLayer=window.dataLayer||[];function gtag(){dataLayer.push(arguments);}gtag('js',new Date());gtag('config','G-0F2R4RX636');`,
          }}
        />
      </head>
      <body className="min-h-full flex flex-col bg-[#FAFAF7]">{children}</body>
    </html>
  );
}
