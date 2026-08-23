import type { Metadata } from "next";
import Link from "next/link";
import ModelFinder from "@/components/en/ModelFinder";
import { EnTrackView } from "@/components/en/EnClientBits";
import { loadIgtDataset } from "@/lib/experiments/snow-peak-igt/data.server";
import {
  enCanonical,
  finderRobots,
  getEnPage,
  hasSearchQuery,
} from "@/lib/experiments/snow-peak-igt/seo";

const PAGE = getEnPage("/en/tools/snow-peak-igt-model-finder");

type SearchParams = Promise<{ [key: string]: string | string[] | undefined }>;

/**
 * 検索結果は同一ページ内で描き、型番ごとのURLは作らない。
 * それでも `?q=` 付きのURLは共有されうるので、その場合だけ noindex にする。
 * ここを開けると検索語の数だけ薄いページがindexされる。
 */
export async function generateMetadata({
  searchParams,
}: {
  searchParams: SearchParams;
}): Promise<Metadata> {
  const params = await searchParams;
  const robots = finderRobots(hasSearchQuery(params));

  return {
    title: PAGE.title,
    description: PAGE.description,
    alternates: { canonical: enCanonical("/en/tools/snow-peak-igt-model-finder") },
    robots,
    openGraph: {
      type: "website",
      locale: "en_US",
      title: PAGE.title,
      description: PAGE.description,
      url: `https://camp-gear-lab.com${PAGE.path}`,
      siteName: "Camp Gear Lab",
    },
  };
}

const FOCUS =
  "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-lake-600";

export default function ModelFinderPage() {
  const { products, sources, lastVerifiedAt } = loadIgtDataset();
  // 送信先URLはブラウザへ渡さない。設定されているかどうかだけを渡す
  const requestFormEnabled = Boolean(process.env.MODEL_REQUEST_FORM_URL);

  return (
    <>
      <EnTrackView event="finder_view" page="finder" />
      <div className="max-w-4xl mx-auto px-4 py-10 sm:py-12">
        <nav className="text-sm text-slate-500 mb-6" aria-label="Breadcrumb">
          <Link href="/en" className={`hover:text-lake-600 transition rounded ${FOCUS}`}>
            English
          </Link>
          <span className="mx-2 text-slate-400">/</span>
          <span>Model Finder</span>
        </nav>

        <h1 className="text-2xl sm:text-3xl md:text-4xl font-semibold tracking-tight text-ink-strong leading-tight">
          Snow Peak IGT Model Finder
        </h1>

        <p className="mt-4 mb-8 text-base text-slate-600 leading-relaxed max-w-2xl">
          Look up a Snow Peak IGT model number or product name. Every record
          here is checked against official Snow Peak documentation, and anything
          we cannot confirm is shown as unknown rather than guessed.
        </p>

        <ModelFinder
          products={products}
          sources={sources}
          requestFormEnabled={requestFormEnabled}
        />

        <section className="mt-12 pt-6 border-t border-line text-sm text-slate-600 leading-relaxed space-y-3">
          <h2 className="text-base font-semibold text-ink-strong">
            What this tool does not tell you
          </h2>
          <ul className="list-disc pl-5 space-y-1.5">
            <li>
              It does not judge compatibility for gas canisters, fuel adapters or
              any modification to burners. Get that from Snow Peak directly.
            </li>
            <li>
              It does not confirm fit for third-party products that Snow Peak
              does not document.
            </li>
            <li>
              It does not track prices or stock. Check the retailer for those.
            </li>
            <li>
              Snow Peak&apos;s own current information always takes precedence
              over this page.
            </li>
          </ul>
          {lastVerifiedAt ? (
            <p className="text-xs text-slate-500">
              Most recent verification in this dataset: {lastVerifiedAt}
            </p>
          ) : null}
          <p>
            <Link
              href="/en/methodology"
              className={`text-lake-600 hover:text-lake-700 underline underline-offset-2 rounded ${FOCUS}`}
            >
              How these records are verified
            </Link>
          </p>
        </section>
      </div>
    </>
  );
}
