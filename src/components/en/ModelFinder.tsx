"use client";

import { useMemo, useRef, useState } from "react";
import {
  EVIDENCE_STATEMENTS,
  PRODUCT_STATUS_LABEL,
  UNKNOWN_LABEL,
  compatibilityStatement,
  displayOrUnknown,
  searchProducts,
  shouldShowSuccessor,
  successorStatement,
  type ProductRecord,
  type SearchResult,
  type SourceRecord,
} from "@/lib/experiments/snow-peak-igt/core";
import { trackEnEvent } from "@/lib/experiments/snow-peak-igt/analytics";
import { EnInlineDisclosure } from "./EnChrome";
import { EnPurchaseLink } from "./EnClientBits";
import ModelRequest from "./ModelRequest";

const FOCUS =
  "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-lake-600";

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid sm:grid-cols-[13rem_1fr] gap-1 sm:gap-4 py-2.5 border-b border-line-soft last:border-b-0">
      <dt className="text-xs sm:text-sm text-slate-500">{label}</dt>
      <dd className="text-sm text-ink">{children}</dd>
    </div>
  );
}

function Unknown() {
  return <span className="text-slate-400">{UNKNOWN_LABEL}</span>;
}

/** 値があればそのまま、無ければ Unknown。空文字や 0 を出さない */
function Value({ value }: { value: string | null | undefined }) {
  const shown = displayOrUnknown(value);
  return shown === UNKNOWN_LABEL ? <Unknown /> : <>{shown}</>;
}

function SourceList({
  sourceIds,
  sources,
}: {
  sourceIds: string[];
  sources: SourceRecord[];
}) {
  const resolved = sourceIds
    .map((id) => sources.find((s) => s.id === id))
    .filter((s): s is SourceRecord => Boolean(s));

  if (resolved.length === 0) return <Unknown />;

  return (
    <ul className="space-y-1">
      {resolved.map((s) => (
        <li key={s.id}>
          <a
            href={s.url}
            target="_blank"
            rel="noopener noreferrer"
            className={`text-lake-600 hover:text-lake-700 underline underline-offset-2 rounded ${FOCUS}`}
          >
            {s.publisher} — {s.title}
          </a>
          <span className="text-slate-400 text-xs ml-2">
            checked {s.lastVerifiedAt}
          </span>
        </li>
      ))}
    </ul>
  );
}

/** 出典付きの事実。原文をそのまま出し、どの資料に書いてあるかを添える */
function Fact({
  fact,
  sources,
}: {
  fact: { text: string; sourceIds: string[]; lang?: "ja" | "en" };
  sources: SourceRecord[];
}) {
  const cited = fact.sourceIds
    .map((id) => sources.find((s) => s.id === id))
    .filter((s): s is SourceRecord => Boolean(s));
  const isJa = fact.lang === "ja";
  return (
    <>
      <span className="text-ink" lang={fact.lang ?? "en"}>
        {fact.text}
      </span>
      {isJa ? (
        <span className="block text-xs text-slate-500 mt-0.5">
          Quoted in Japanese from the Japanese official page. We do not translate
          it here, because a translation would be our wording rather than Snow
          Peak&apos;s.
        </span>
      ) : null}
      {cited.length > 0 ? (
        <span className="block text-xs text-slate-500 mt-0.5">
          {cited.map((s, i) => (
            <span key={s.id}>
              {i > 0 ? ", " : ""}
              <a
                href={s.url}
                target="_blank"
                rel="noopener noreferrer"
                className={`underline underline-offset-2 hover:text-lake-600 rounded ${FOCUS}`}
              >
                {s.title}
              </a>
            </span>
          ))}
        </span>
      ) : null}
    </>
  );
}

function ProductResult({
  product,
  products,
  sources,
}: {
  product: ProductRecord;
  products: ProductRecord[];
  sources: SourceRecord[];
}) {
  const successor = product.confirmedSuccessorId
    ? products.find((p) => p.id === product.confirmedSuccessorId)
    : null;

  const documented = product.compatibility.filter(
    (c) => compatibilityStatement(c) === EVIDENCE_STATEMENTS.confirmed
  );

  return (
    <article className="bg-white border border-line rounded-xl p-4 sm:p-6">
      <h3 className="text-lg font-semibold text-ink-strong mb-4">
        {product.productName}
      </h3>

      <dl className="mb-5">
        <Row label="Japanese model number">
          <Value value={product.japaneseModelNumber} />
        </Row>
        <Row label="US model number">
          <Value value={product.usModelNumber} />
        </Row>
        <Row label="Product status">
          {PRODUCT_STATUS_LABEL[product.status]}
        </Row>
        <Row label="IGT unit capacity">
          {product.igtUnitCapacity ? (
            <Fact fact={product.igtUnitCapacity} sources={sources} />
          ) : (
            <Unknown />
          )}
        </Row>
        {shouldShowSuccessor(product) ? (
          <Row label="Confirmed successor">
            {successor ? (
              <>
                {successor.productName}
                <span className="block text-xs text-slate-500 mt-0.5">
                  {successorStatement(product)}
                </span>
              </>
            ) : (
              <span className="text-slate-500">{successorStatement(product)}</span>
            )}
          </Row>
        ) : null}
        <Row label="Officially documented compatibility">
          {documented.length === 0 ? (
            <span className="text-slate-500">
              {EVIDENCE_STATEMENTS.insufficient}
            </span>
          ) : (
            <ul className="space-y-2">
              {documented.map((c) => {
                const target = products.find((p) => p.id === c.targetId);
                return (
                  <li key={c.targetId}>
                    <span className="text-ink">
                      {target?.productName ?? c.targetId}
                    </span>
                    <span className="block text-xs text-slate-500 mt-0.5">
                      {compatibilityStatement(c)}
                    </span>
                    {c.notes ? (
                      <span className="block text-xs text-slate-500">{c.notes}</span>
                    ) : null}
                  </li>
                );
              })}
            </ul>
          )}
        </Row>
        <Row label="Evidence source">
          <SourceList sourceIds={product.sourceIds} sources={sources} />
        </Row>
        <Row label="Last verified">
          <Value value={product.lastVerifiedAt} />
        </Row>
      </dl>

      {product.purchaseOptions.length > 0 ? (
        <div className="pt-4 border-t border-line-soft space-y-3">
          <EnInlineDisclosure />
          <div>
            <p className="text-xs text-slate-500 mb-2">Current purchase option</p>
            <ul className="flex flex-wrap gap-2">
              {product.purchaseOptions.map((o) => (
                <li key={`${o.market}-${o.merchant}-${o.url}`}>
                  <EnPurchaseLink
                    href={o.url}
                    merchant={o.merchant}
                    market={o.market}
                    modelId={product.id}
                    placement="finder_result"
                    affiliate={o.affiliate}
                    className={`inline-flex items-center gap-1.5 px-4 py-2 rounded-lg border border-lake-600 text-lake-600 hover:bg-lake-50 text-sm font-medium transition ${FOCUS}`}
                  >
                    {o.merchant}
                    <span className="text-xs text-slate-500 uppercase">
                      {o.market}
                    </span>
                  </EnPurchaseLink>
                </li>
              ))}
            </ul>
          </div>
        </div>
      ) : (
        <p className="pt-4 border-t border-line-soft text-sm text-slate-500">
          Current purchase option: <Unknown />
        </p>
      )}

      <div className="mt-4 pt-4 border-t border-line-soft">
        <p className="text-xs text-slate-500 mb-2">Important limitations</p>
        {product.importantLimitations.length > 0 ? (
          <ul className="list-disc pl-5 space-y-1.5 text-sm text-ink mb-3">
            {product.importantLimitations.map((f) => (
              <li key={f.text}>
                <Fact fact={f} sources={sources} />
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-sm text-slate-500 mb-3">
            {EVIDENCE_STATEMENTS.insufficient}. We have not recorded
            product-specific limitations from official documentation for this
            item yet.
          </p>
        )}
        <p className="text-xs text-slate-500 leading-relaxed">
          This record reflects official documentation as of the verification date
          above. Snow Peak may change specifications at any time, and the
          manufacturer&apos;s current information always takes precedence over
          this page.
        </p>
      </div>
    </article>
  );
}

export default function ModelFinder({
  products,
  sources,
  requestFormEnabled,
}: {
  products: ProductRecord[];
  sources: SourceRecord[];
  requestFormEnabled: boolean;
}) {
  const [query, setQuery] = useState("");
  const [result, setResult] = useState<SearchResult>({ status: "empty" });
  const started = useRef(false);

  const datasetEmpty = products.length === 0;

  function handleChange(value: string) {
    setQuery(value);
    // finder_start は「表示」ではなく「実際に検索操作を始めた時点」。
    // ページ表示で発火させると finder_view と同じ意味になり、
    // 「使われたかどうか」が測れなくなる
    if (!started.current && value.trim() !== "") {
      started.current = true;
      trackEnEvent("finder_start", { page: "finder" });
    }
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const outcome = searchProducts(query, products);
    setResult(outcome);

    if (outcome.status === "empty") return;

    trackEnEvent("finder_complete", { page: "finder" });

    if (outcome.status === "found") {
      trackEnEvent("result_found", {
        page: "finder",
        result_status: "found",
        // 見つかった商品のIDは自由入力ではないので送ってよい
        model_id: outcome.matches[0]?.product.id,
      });
    } else {
      // 検索語そのものは送らない（自由入力にあたる）
      trackEnEvent("result_unknown", { page: "finder", result_status: "not_found" });
    }
  }

  const matches = useMemo(
    () => (result.status === "found" ? result.matches : []),
    [result]
  );

  return (
    <div className="space-y-6">
      <form onSubmit={handleSubmit} className="space-y-3" role="search">
        <label
          htmlFor="igt-model-query"
          className="block text-sm font-medium text-ink-strong"
        >
          Search by model number or product name
        </label>
        <div className="flex flex-col sm:flex-row gap-2">
          <input
            id="igt-model-query"
            name="q"
            type="search"
            inputMode="search"
            autoComplete="off"
            value={query}
            onChange={(e) => handleChange(e.target.value)}
            placeholder="CK-080, ck080, Entry IGT"
            aria-describedby="igt-model-hint"
            className={`flex-1 border border-line rounded-lg px-4 py-3 text-base text-ink bg-white placeholder:text-slate-400 ${FOCUS}`}
          />
          <button
            type="submit"
            className={`bg-lake-600 hover:bg-lake-700 text-white px-6 py-3 rounded-lg text-sm font-medium transition ${FOCUS}`}
          >
            Search
          </button>
        </div>
        <p id="igt-model-hint" className="text-xs text-slate-500">
          Capitalisation, hyphens and spaces do not matter. CK-080, ck080 and
          &quot;CK 080&quot; all find the same record.
        </p>
      </form>

      <div aria-live="polite" aria-atomic="false">
        {datasetEmpty ? (
          <div className="bg-mist border border-line rounded-xl p-5 text-sm text-slate-600 leading-relaxed">
            <p className="font-medium text-ink-strong mb-1">
              No records are published yet.
            </p>
            <p>
              This section only publishes records that have been checked against
              official Snow Peak documentation, and none have been verified so
              far. Rather than fill the gap with guesses, we leave it empty. You
              can still request a model check below, and we will add records as
              they are verified.
            </p>
          </div>
        ) : null}

        {result.status === "found" ? (
          <div className="space-y-4">
            <p className="text-sm text-slate-500">
              {matches.length} {matches.length === 1 ? "record" : "records"} found
            </p>
            {matches.map((m) => (
              <ProductResult
                key={m.product.id}
                product={m.product}
                products={products}
                sources={sources}
              />
            ))}
          </div>
        ) : null}

        {result.status === "not_found" && !datasetEmpty ? (
          <div className="bg-mist border border-line rounded-xl p-5">
            <p className="font-medium text-ink-strong mb-1">
              No record for that model
            </p>
            <p className="text-sm text-slate-600">
              {EVIDENCE_STATEMENTS.insufficient}. We have not verified this model
              against official documentation yet.
            </p>
          </div>
        ) : null}
      </div>

      {/*
        リクエスト導線を出す条件。
        データが空のうちは検索しても何も出ないので、最初から出す。
        データがあるなら、**1回検索して見つからなかったときだけ**出す。

        検索せずに送信できると、一次指標
        （model_request_submit ÷ result_unknown）の分母を経ずに
        分子だけが増えて、需要の強さを測れなくなる。
        導線を増やすより、測れることを優先する（2026-08-25）。
      */}
      {datasetEmpty || result.status === "not_found" ? (
        <section className="border-t border-line pt-6">
          <h2 className="text-lg font-semibold text-ink-strong">
            Can&apos;t find your model?
          </h2>
          <p className="text-sm text-slate-600 mt-1 mb-4">
            Request a model check.
          </p>
          <ModelRequest enabled={requestFormEnabled} />
        </section>
      ) : null}
    </div>
  );
}
