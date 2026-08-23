import { EnHeader, EnFooter } from "@/components/en/EnChrome";
import { EnHtmlLang } from "@/components/en/EnClientBits";
import { EN_LANG } from "@/lib/experiments/snow-peak-igt/seo";

/**
 * 英語セクションの外枠。
 *
 * `lang` をここのラッパー要素に付けている。ルートレイアウトは1つしかなく
 * `<html lang="ja">` 固定で、出し分けにはルートレイアウトの分割が要る
 * （詳細は EnHtmlLang のコメント）。SSR出力にはこのラッパーの lang が乗る。
 */
export default function EnLayout({ children }: { children: React.ReactNode }) {
  return (
    <div lang={EN_LANG} className="flex flex-col min-h-full flex-1">
      <EnHtmlLang />
      <EnHeader />
      <main className="flex-1">{children}</main>
      <EnFooter />
    </div>
  );
}
