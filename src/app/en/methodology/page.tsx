import type { Metadata } from "next";
import Link from "next/link";
import { enCanonical, getEnPage } from "@/lib/experiments/snow-peak-igt/seo";
import { FORBIDDEN_PHRASES } from "@/lib/experiments/snow-peak-igt/core";

const PAGE = getEnPage("/en/methodology");

export const revalidate = 86400;

export const metadata: Metadata = {
  title: PAGE.title,
  description: PAGE.description,
  alternates: { canonical: enCanonical("/en/methodology") },
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

export default function MethodologyPage() {
  return (
    <div className="max-w-4xl mx-auto px-4 py-10 sm:py-12">
      <nav className="text-sm text-slate-500 mb-6" aria-label="Breadcrumb">
        <Link href="/en" className={`hover:text-lake-600 transition rounded ${FOCUS}`}>
          English
        </Link>
        <span className="mx-2 text-slate-400">/</span>
        <span>Methodology</span>
      </nav>

      <h1 className="text-2xl sm:text-3xl md:text-4xl font-semibold tracking-tight text-ink-strong leading-tight mb-8">
        Methodology
      </h1>

      <div className="prose max-w-none">
        <p>
          This page describes exactly how the records in the{" "}
          <Link href="/en/tools/snow-peak-igt-model-finder">Model Finder</Link>{" "}
          are produced. If you are going to rely on a compatibility answer, you
          should be able to check how we got it.
        </p>

        <h2>Sources we use</h2>
        <p>We record information from Snow Peak&apos;s own material only:</p>
        <ul>
          <li>Official product pages (Snow Peak Japan and Snow Peak USA)</li>
          <li>Official manuals and instruction documents</li>
          <li>Archived official pages, for discontinued products</li>
          <li>Official support and customer service information</li>
        </ul>
        <p>
          Retailer listings, marketplace pages, forum threads and shop blog posts
          are <strong>not</strong> used as the basis for a compatibility claim.
          They are often right, but there is no way for a reader to tell when
          they are wrong, and a confident wrong answer is the failure mode we are
          trying to avoid.
        </p>

        <h2>How records are verified</h2>
        <p>
          Every stored field traces back to a source record, and every source
          record has a publisher, a title, a URL and a date. A record cannot
          enter the dataset without at least one source — this is enforced in
          code, not by convention, so an unsourced record fails the build rather
          than quietly appearing on the site.
        </p>
        <p>
          Compatibility has a stricter rule: an entry may only be marked{" "}
          <em>confirmed</em> if it carries its own source. Marking something
          confirmed because it &quot;obviously&quot; fits is exactly the mistake
          this structure exists to prevent.
        </p>

        <h2>How verification dates are handled</h2>
        <p>
          Each record shows the date it was last checked. That date is the honest
          scope of the claim: it means we saw this in official material on that
          day, and nothing more. Snow Peak can revise a product at any time
          without telling us.
        </p>
        <p>
          We do not refresh dates automatically. A date only moves when someone
          actually re-checks the source, because a date that updates on its own
          is worse than no date — it implies a check that never happened.
        </p>

        <h2>We do not guess</h2>
        <p>
          Where we do not have information, the record says{" "}
          <strong>Unknown</strong> or <strong>Insufficient evidence</strong>. We
          do not fill gaps by inference, by pattern-matching model numbers, or by
          generating plausible text. A blank we admit to is useful; a blank we
          paper over is a trap.
        </p>
        <p>The only judgements the finder will state are these four:</p>
        <ul>
          <li>Confirmed by official documentation</li>
          <li>Current equivalent identified</li>
          <li>Discontinued — no confirmed successor</li>
          <li>Insufficient evidence</li>
        </ul>
        <p>
          What you will never see here are hedged claims such as{" "}
          {FORBIDDEN_PHRASES.slice(0, 3).map((phrase, i, list) => (
            <span key={phrase}>
              <em>&quot;{phrase}&quot;</em>
              {i < list.length - 1 ? ", " : ""}
            </span>
          ))}
          . Those phrases move risk onto the reader while sounding like
          reassurance, so they are blocked in code rather than left to
          discipline.
        </p>

        <h2>How we judge compatibility</h2>
        <p>
          Compatibility is recorded as a relationship between two specific
          products, with its own status and its own sources. It is kept separate
          from product status and from succession, because those are different
          facts:
        </p>
        <ul>
          <li>
            A discontinued product may still be compatible with current
            accessories.
          </li>
          <li>
            A confirmed successor may <strong>not</strong> be compatible with the
            accessories of the product it replaced.
          </li>
        </ul>
        <p>
          We never derive compatibility from succession. Two fields, two sets of
          evidence.
        </p>
        <p>
          Out of scope entirely: gas canisters, fuel adapters and any
          modification to burners. Those carry real safety consequences and
          belong with Snow Peak, not with us. We also do not certify fit for
          third-party products that Snow Peak does not document.
        </p>

        <h2>The manufacturer comes first</h2>
        <p>
          If this page and Snow Peak disagree, Snow Peak is right. Treat anything
          here as a starting point for your own check, especially for an
          expensive or hard-to-return purchase.
        </p>

        <h2>Reporting an error or an outdated record</h2>
        <p>
          Corrections are welcome and we would rather hear about a mistake than
          preserve a clean-looking page. Use the{" "}
          <strong>Request a model check</strong> form under the Model Finder
          results, and say which record is wrong and what the official source
          shows. If a record turns out to be unsupportable, we remove it rather
          than soften it.
        </p>
      </div>
    </div>
  );
}
