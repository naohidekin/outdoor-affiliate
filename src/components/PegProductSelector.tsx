"use client";

import { useId, useRef, useState } from "react";
import AffiliateLink from "./AffiliateLink";
import { filterPegVariants, pegFilterOptions, PEG_FILTER_FIELDS, type PegFilters, type PegVariant } from "../lib/pegs/selector.ts";

const EMPTY_FILTERS: PegFilters = { sizeLabel: "", color: "", type: "" };
const LABELS = { sizeLabel: "サイズ", color: "色", type: "タイプ" };
const BUTTON = "inline-flex min-h-11 items-center justify-center rounded-lg border px-4 py-2 text-sm font-medium transition focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-lake-600";

export default function PegProductSelector({ variants }: { variants: readonly PegVariant[] }) {
  const [filters, setFilters] = useState<PegFilters>(EMPTY_FILTERS);
  const prefix = useId();
  const firstSelect = useRef<HTMLSelectElement>(null);
  const visible = filterPegVariants(variants, filters);
  return (
    <section id="product-selector" aria-labelledby={`${prefix}-title`} className="my-10 min-w-0 rounded-2xl border border-lake-100 bg-lake-50/40 p-4 sm:p-6">
      <h3 id={`${prefix}-title`} className="text-xl font-semibold text-ink-strong">条件に合うペグを探す</h3>
      <p className="mt-3 text-sm leading-7 text-slate-600">掲載したサイズ・色・タイプから絞り込めます。価格・在庫・送料は販売先でご確認ください。</p>
      <div className="mt-5 grid gap-4 sm:grid-cols-3">
        {PEG_FILTER_FIELDS.map((field, index) => (
          <label key={field} htmlFor={`${prefix}-${field}`} className="min-w-0 text-sm font-medium text-ink">
            {LABELS[field]}
            <select id={`${prefix}-${field}`} ref={index === 0 ? firstSelect : undefined} value={filters[field]}
              onChange={(event) => setFilters((current) => ({ ...current, [field]: event.target.value }))}
              className="mt-2 block min-h-11 w-full min-w-0 rounded-lg border border-lake-200 bg-white px-3 py-2 text-sm">
              <option value="">すべて</option>
              {pegFilterOptions(variants, field).map((value) => <option key={value} value={value}>{value}</option>)}
            </select>
          </label>
        ))}
      </div>
      <div className="my-4 flex flex-wrap items-center justify-between gap-2 text-sm">
        <p role="status" aria-live="polite" aria-atomic="true">{visible.length}件の組み合わせ / 全{variants.length}件</p>
        <button type="button" className="min-h-11 px-2 text-lake-700 underline underline-offset-4"
          onClick={() => { setFilters(EMPTY_FILTERS); firstSelect.current?.focus(); }}>条件をリセット</button>
      </div>
      <noscript><p className="mb-4 text-sm">絞り込みを使わずに確認できるよう、すべての組み合わせを下に掲載しています。</p></noscript>
      {visible.length === 0 ? (
        <p className="rounded-lg border border-dashed border-lake-200 bg-white p-5 text-sm leading-7">この条件の組み合わせは掲載していません。サイズ・色・タイプのいずれかを「すべて」に戻してください。</p>
      ) : (
        <div className="grid min-w-0 gap-4 md:grid-cols-2">
          {visible.map((variant) => (
            <article key={variant.id} data-peg-variant={variant.id} className="flex min-w-0 flex-col rounded-xl border border-line bg-white p-4 sm:p-5">
              <p className="text-xs text-slate-500">{variant.series}</p>
              <h4 className="mt-2 text-lg font-semibold leading-7 text-ink-strong">{variant.name}</h4>
              <p className="mt-2 text-sm font-medium text-lake-700">{variant.sizeLabel} / {variant.color}</p>
              <p className="mt-1 text-xs leading-6 text-slate-600">{variant.type}</p>
              <dl className="mt-4 grid grid-cols-[5em_minmax(0,1fr)] gap-x-3 gap-y-2 text-sm leading-6">
                <dt className="text-slate-500">素材</dt><dd>{variant.material}</dd>
                <dt className="text-slate-500">長さ</dt><dd>{variant.lengthMm === null ? "180mm / 184mm（公式内で表記差あり）" : `${variant.lengthMm}mm`}</dd>
                <dt className="text-slate-500">1本重量</dt><dd>{variant.id.startsWith("ellisse-") ? "約" : ""}{variant.weightG}g（公称）</dd>
                <dt className="text-slate-500">販売本数</dt><dd>{variant.purchaseLinks.length ? variant.purchaseLinks.map((link) => `${link.packCount}本`).join(" / ") : "検索先で確認"}</dd>
              </dl>
              {variant.note ? <p className="mt-4 text-xs leading-6 text-slate-600">{variant.note}</p> : null}
              <div className="mt-auto pt-5">
                {variant.purchaseLinks.map((link) => (
                  <div key={link.url} className="mb-4 rounded-lg bg-lake-50 p-3">
                    <p className="text-xs font-medium text-lake-700">{link.kind === "select_at_destination" ? "販売先でサイズ・色を選択" : "この仕様の専用ページ"} · {link.manufacturerModel}</p>
                    <p className="mt-2 text-sm leading-6 text-ink">{link.note}</p>
                    <p className="mt-1 text-xs leading-6 text-slate-500">{link.merchant}</p>
                    <AffiliateLink href={link.url} productId={variant.id} productName={variant.name} store="rakuten" placement="product_card"
                      className={`${BUTTON} mt-3 w-full border-lake-700 bg-lake-700 text-white hover:bg-lake-800`}>{link.label}</AffiliateLink>
                  </div>
                ))}
                <div className="flex flex-wrap gap-2">
                  <a href={variant.manufacturerUrl} target="_blank" rel="noopener noreferrer" className={`${BUTTON} border-line text-ink`}>公式仕様</a>
                  <AffiliateLink href={variant.amazonSearchUrl} productId={variant.id} productName={variant.name} store="amazon" placement="product_card"
                    className={`${BUTTON} border-line text-ink`}>Amazonで検索（広告）</AffiliateLink>
                </div>
                <p className="mt-3 text-xs leading-6 text-slate-500">Amazonは検索結果です。希望する仕様・本数の商品や在庫を保証しません。</p>
              </div>
            </article>
          ))}
        </div>
      )}
    </section>
  );
}
