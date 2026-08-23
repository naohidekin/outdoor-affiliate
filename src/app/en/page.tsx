import type { Metadata } from "next";
import Link from "next/link";
import { EnTrackView } from "@/components/en/EnClientBits";
import { enCanonical, getEnPage } from "@/lib/experiments/snow-peak-igt/seo";

const PAGE = getEnPage("/en");

export const revalidate = 86400;

export const metadata: Metadata = {
  title: PAGE.title,
  description: PAGE.description,
  // 対応する日本語版が無いので hreflang（alternates.languages）は付けない
  alternates: { canonical: enCanonical("/en") },
  openGraph: {
    type: "website",
    locale: "en_US",
    title: PAGE.title,
    description: PAGE.description,
    url: `https://camp-gear-lab.com${PAGE.path}`,
    siteName: "Camp Gear Lab",
  },
};

const FOCUS =
  "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-lake-600";

const LINKS = [
  {
    href: "/en/tools/snow-peak-igt-model-finder",
    title: "Model Finder",
    body: "Search a model number or product name. See the Japanese and US model numbers, whether it is current or discontinued, any confirmed successor, and compatibility that Snow Peak actually documents.",
  },
  {
    href: "/en/guides/snow-peak-igt-model-numbers",
    title: "Guide: Snow Peak IGT model numbers",
    body: "Why the Japanese and US numbers differ, and why a successor product is not the same thing as a compatible product.",
  },
  {
    href: "/en/methodology",
    title: "Methodology",
    body: "Which sources we use, how records are verified, and why we leave unknown things marked as unknown.",
  },
  {
    href: "/en/affiliate-disclosure",
    title: "Affiliate disclosure",
    body: "What the purchase links on this section are, and what they do not mean.",
  },
];

export default function EnglishHubPage() {
  return (
    <>
      <EnTrackView event="english_hub_view" page="hub" />
      <div className="max-w-4xl mx-auto px-4 py-12">
        <h1 className="text-3xl md:text-4xl font-semibold tracking-tight text-ink-strong leading-tight">
          Snow Peak IGT, in English
        </h1>

        <p className="mt-5 text-base text-slate-600 leading-relaxed max-w-2xl">
          Camp Gear Lab is a Japanese outdoor gear site. This English section is
          an experiment with one narrow purpose: to find out whether people
          outside Japan actually need help matching Snow Peak IGT model numbers
          across markets, identifying discontinued products and their
          successors, and checking what is genuinely compatible.
        </p>

        <p className="mt-4 text-base text-slate-600 leading-relaxed max-w-2xl">
          It is deliberately small. We publish a record only when we can check it
          against official Snow Peak documentation. Where we cannot, the page
          says so instead of guessing.
        </p>

        <ul className="mt-10 grid gap-4 sm:grid-cols-2">
          {LINKS.map((l) => (
            <li key={l.href}>
              <Link
                href={l.href}
                className={`block h-full bg-white border border-line rounded-xl p-5 hover:border-lake-600 transition ${FOCUS}`}
              >
                <span className="block font-semibold text-ink-strong">
                  {l.title}
                </span>
                <span className="block mt-2 text-sm text-slate-600 leading-relaxed">
                  {l.body}
                </span>
              </Link>
            </li>
          ))}
        </ul>
      </div>
    </>
  );
}
