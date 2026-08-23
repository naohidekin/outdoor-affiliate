import type { Metadata } from "next";
import Link from "next/link";
import { enCanonical, getEnPage } from "@/lib/experiments/snow-peak-igt/seo";

const PAGE = getEnPage("/en/guides/snow-peak-igt-model-numbers");

export const revalidate = 86400;

export const metadata: Metadata = {
  title: PAGE.title,
  description: PAGE.description,
  alternates: { canonical: enCanonical("/en/guides/snow-peak-igt-model-numbers") },
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

export default function IgtModelNumbersGuide() {
  return (
    <div className="max-w-4xl mx-auto px-4 py-10 sm:py-12">
      <nav className="text-sm text-slate-500 mb-6" aria-label="Breadcrumb">
        <Link href="/en" className={`hover:text-lake-600 transition rounded ${FOCUS}`}>
          English
        </Link>
        <span className="mx-2 text-slate-400">/</span>
        <span>Guide</span>
      </nav>

      <h1 className="text-2xl sm:text-3xl md:text-4xl font-semibold tracking-tight text-ink-strong leading-tight mb-8">
        Understanding Snow Peak IGT model numbers
      </h1>

      <div className="prose max-w-none">
        <p>
          If you are shopping for Snow Peak IGT parts from outside Japan, the
          model numbers are the first thing that trips people up. This page
          explains the traps, and how to use the Model Finder to work around
          them.
        </p>

        <h2>Japanese and US model numbers may differ</h2>
        <p>
          Snow Peak sells in both Japan and the United States, and the two
          catalogues do not always use the same number for the same item. A
          number you found on a Japanese listing may not appear anywhere on the
          US site, and the reverse also happens. Two numbers that look almost
          identical can also be different products — a trailing letter is often
          a revision, not a typo.
        </p>
        <p>
          This is why the Model Finder stores the Japanese number and the US
          number as separate fields, and shows both. Where we only know one of
          them, the other is shown as Unknown. We do not derive one from the
          other.
        </p>

        <h2>Current, discontinued and successor are three different things</h2>
        <p>
          These get collapsed into one idea constantly, and it causes bad
          purchases. They are separate:
        </p>
        <ul>
          <li>
            <strong>Current</strong> — Snow Peak still lists the product.
          </li>
          <li>
            <strong>Discontinued</strong> — Snow Peak no longer lists it. That
            says nothing about whether a replacement exists.
          </li>
          <li>
            <strong>Successor</strong> — a newer product that takes the older
            one&apos;s place in the range.
          </li>
        </ul>
        <p>
          The important one: <strong>a successor is not a promise of
          compatibility.</strong> A newer model can replace an older one in the
          catalogue while having different dimensions, a different mounting
          arrangement, or a different frame width. So the Model Finder records a
          confirmed successor and documented compatibility in separate fields,
          and never infers the second from the first.
        </p>

        <h2>Compatibility must be confirmed from official documentation</h2>
        <p>
          Forum threads and shop listings are full of confident claims about what
          fits what. Some of them are right. The problem is that you cannot tell
          which, and a wrong answer here means a part that does not sit in the
          frame.
        </p>
        <p>
          So this section only records compatibility that appears in Snow Peak&apos;s
          own material — product pages, manuals, archived official pages and
          official support information. Anything else is left as{" "}
          <em>Insufficient evidence</em>. That is not us being cautious for the
          sake of it: an unverified claim presented as fact is worse than no
          claim at all.
        </p>

        <h2>How to use the Model Finder</h2>
        <p>
          Type a model number or a product name into the{" "}
          <Link href="/en/tools/snow-peak-igt-model-finder">Model Finder</Link>.
          Capitalisation, hyphens and spaces are ignored, so <code>CK-080</code>,{" "}
          <code>ck080</code> and <code>CK 080</code> all reach the same record.
        </p>
        <p>Each record shows, where we have it:</p>
        <ul>
          <li>Product name</li>
          <li>Japanese model number and US model number</li>
          <li>Product status — Current, Discontinued or Unknown</li>
          <li>Confirmed successor</li>
          <li>Officially documented compatibility</li>
          <li>The evidence source, and the date we last checked it</li>
          <li>A current purchase option, when one exists</li>
        </ul>

        <h2>How to request an unknown model check</h2>
        <p>
          If your model is not there, use the{" "}
          <strong>Request a model check</strong> form under the search results.
          Tell us the model number, and what you are trying to connect, replace
          or identify — that context matters, because &quot;does this fit?&quot;
          has a different answer depending on what is on the other side.
        </p>
        <p>
          We will only publish a record once we can check it against official
          documentation. If we cannot confirm it, we will not publish a guess.
        </p>

        <h2>Limitations of the data</h2>
        <ul>
          <li>
            Coverage is narrow and deliberately small. This is an experiment, not
            a complete catalogue.
          </li>
          <li>
            Every record carries the date it was last verified. Snow Peak can
            change specifications at any time, and{" "}
            <strong>the manufacturer&apos;s current information always takes
            precedence over this page.</strong>
          </li>
          <li>
            We do not cover gas canisters, fuel adapters or any modification to
            burners.
          </li>
          <li>
            We do not confirm fit for third-party products that Snow Peak does
            not document.
          </li>
          <li>We do not track prices or stock.</li>
        </ul>
        <p>
          If you find something out of date or wrong,{" "}
          <Link href="/en/methodology">tell us</Link> — corrections are the whole
          point of publishing the verification date.
        </p>
      </div>
    </div>
  );
}
