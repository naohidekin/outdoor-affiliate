import type { Metadata } from "next";
import Link from "next/link";
import { enCanonical, getEnPage } from "@/lib/experiments/snow-peak-igt/seo";

const PAGE = getEnPage("/en/affiliate-disclosure");

export const revalidate = 86400;

export const metadata: Metadata = {
  title: PAGE.title,
  description: PAGE.description,
  alternates: { canonical: enCanonical("/en/affiliate-disclosure") },
  openGraph: {
    type: "article",
    locale: "en_US",
    title: PAGE.title,
    description: PAGE.description,
    url: `https://camp-gear-lab.com${PAGE.path}`,
    siteName: "Camp Gear Lab",
  },
};

const FOCUS =
  "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-lake-600";

export default function AffiliateDisclosurePage() {
  return (
    <div className="max-w-4xl mx-auto px-4 py-10 sm:py-12">
      <nav className="text-sm text-slate-500 mb-6" aria-label="Breadcrumb">
        <Link href="/en" className={`hover:text-lake-600 transition rounded ${FOCUS}`}>
          English
        </Link>
        <span className="mx-2 text-slate-400">/</span>
        <span>Affiliate disclosure</span>
      </nav>

      <h1 className="text-2xl sm:text-3xl md:text-4xl font-semibold tracking-tight text-ink-strong leading-tight mb-8">
        Affiliate disclosure
      </h1>

      <div className="prose max-w-none">
        <p>
          <strong>
            Some links on this English section are affiliate links. If you buy
            through one of them, Camp Gear Lab may earn a commission at no extra
            cost to you.
          </strong>
        </p>

        <h2>Where the links appear</h2>
        <p>
          Purchase links appear inside Model Finder results, under{" "}
          <em>Current purchase option</em>. A short disclosure is shown directly
          above them, before you reach the first link, so you know what a link is
          before you click it. Affiliate links are marked up as{" "}
          <code>rel=&quot;sponsored nofollow noopener&quot;</code>.
        </p>

        <h2>What a purchase link does not mean</h2>
        <ul>
          <li>
            It is not a recommendation produced by the commission. Records are
            built from official documentation first; a purchase link is attached
            afterwards, only where a legitimate one exists.
          </li>
          <li>
            It is not a price or stock claim. We do not track prices, stock
            levels, lowest prices or review scores, and we do not display them.
            Check the retailer.
          </li>
          <li>
            It is not a compatibility claim. Compatibility comes from Snow
            Peak&apos;s documentation, and is shown separately with its source.
          </li>
        </ul>

        <h2>Where no affiliate programme exists</h2>
        <p>
          Where we do not have an affiliate relationship with a retailer, we link
          to the manufacturer or retailer as an ordinary link. We do not invent
          tracking IDs, and we do not route you through a programme we are not
          actually part of.
        </p>

        <h2>Independence</h2>
        <p>
          Camp Gear Lab is not affiliated with, endorsed by, or sponsored by Snow
          Peak. Snow Peak trademarks and product names are used only to identify
          the products being described. No manufacturer pays for placement or
          reviews this content before publication.
        </p>

        <h2>How to reach us</h2>
        <p>
          For corrections or questions about this section, see the{" "}
          <Link href="/en/methodology">Methodology</Link> page, or the contact
          details on the{" "}
          <Link href="/">
            Japanese site
          </Link>
          .
        </p>
      </div>
    </div>
  );
}
