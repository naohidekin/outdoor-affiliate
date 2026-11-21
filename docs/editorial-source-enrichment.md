# Verified nonproduct source enrichment

This source-only handoff preserves an existing job and its accounting. It does
not run production, a model, image generation, approval, publication or social
delivery. Quality policy, scoring thresholds, weekly limits and model budgets
remain unchanged. The current apply policy allows only
`article-98d3334c7e9afbfb222c19b1`, slug
`thermos-bottle-compatible-parts-search-guide`, category `tumbler`, productIds `[]`.
The receipt/transition machinery can be reused; expanding the pilot policy is a
separate explicit change, not automatic rollout to the other articles.

## Registry and verified scope

`topic_selection.py` collects eight fixed exact HTML URLs. The previous six URL,
ID and scope definitions remain unchanged. Coverage is verified only when all
eight succeed; partial coverage is still partial.

| Exact URL | Public source ID | Exact supported example |
|---|---|---|
| https://www.thermos.jp/goods/ptpdl?g=900067140990 | `public:thermos-jnls-gasket-fit` | JNL-Sパッキンセット（フタパッキン・せんパッキン各1個）, part JAN 4562344398367; product row JNL-S500 / BK-J （ブラックジェイド） / product JAN 4562344397339 |
| https://www.thermos.jp/goods/ptpdl?g=900068940990 | `public:thermos-jnls1000-gasket-fit` | JNL-S1000パッキンセット（フタパッキン・せんパッキン各1個）, part JAN 4562344404532; product row JNL-S1000 / MLGY （ミネラルグレー） / product JAN 4562344400664 |

Both have scope `thermos-parts-fit-example`, in the existing parts family. A
Thermos-primary proposal gets that scope only when its public source IDs include
a registered fit example. The existing lookup scope alone gains no fit claims.
The repair/cleaning/general-compatibility exclusions remain in force. A missing
row does not prove incompatibility; these examples do not establish JNL versus
JNL-S interchangeability or apply to unlisted colors/models.

`fit_example_excerpt(url, html)` requires one visible H1 in main with the exact
part name and its `_code` JAN. It ignores the `_price` span. It then requires the
visible 適合製品一覧 section, one table inside `list_area`, the exact three column
headers, and the model/color/product-JAN in the same row. Duplicate matching
rows, conflicting JANs, swapped or merged cells, hidden/script-only evidence,
missing fields, intervening sections and malformed relevant markup are omitted.
Alt text and other rows do not become facts. The normalized capsule is at most
500 characters. Reverification recomputes the capsule from current HTML; a price
change alone is irrelevant, while an identity/row/canonical/content-type change
holds. PDF is not parsed or claimed as HTML proof.

The old `_Blocks` parser is unchanged. The lookup pages retain their original
four-block extraction. For `pdpts` only, a fifth bounded bottom-label note may be
included. The actual public page places that note in a div under `list_area`,
not a p/li: a separate visible-field adapter extracts its exact first sentence
without OCR or image-alt text. Original four blocks stay in order. Old receipts
reverify their original parts rather than being forced to adopt the fifth block.

## API

```python
from source_enrichment import prepare, validate

# job/proposed_theme are full JSON copies supplied by the operator.
# request is the existing hardened public HTTP reader; tests inject HTML fixtures.
receipt = prepare(job, proposed_theme, request, now=aware_jst_time)
validate(job, receipt)  # offline consistency and CAS checks
result = ledger.extend_nonproduct_sources(job['id'], receipt)
```

The public Ledger wrapper delegates to `source_enrichment.apply(ledger, id,
receipt)`. No other Ledger update method is used by the helper.

Only `sourceIds`, `nonProductContract`, `outline`, and `selectionReason` may
change in the theme. ID, slug/title/category/productIds, period and the remaining
theme fields are fixed. Nonpublic analytics source IDs are fixed. Existing
reference IDs cannot be dropped. Their URL/ID/scope/title identities are fixed;
an expanded excerpt must contain each original paragraph unchanged and in order.
New references must have complete registry-consistent receipts, not a plain
`verified: true` flag. Proposed contract keys, all receipt hashes, the full source
set, allowed scopes and outline family coverage are validated before gather can
return facts=true. Contract images remain empty at this source-only step.

`prepare` does not write the ledger. It validates the transition and fetches all
proposed references, then binds the observation hashes to the complete old job,
old theme, week, proposed theme and aware preparation time. The receipt contains
both old/new themes, complete source observations and its own canonical SHA.
`validate` checks those bindings and observations without HTTP. These hashes
protect consistency; they are not signatures granting authority to an untrusted
caller. Preparation/application are local operator operations, not a remote
approval endpoint. Prepare freshly before applying; apply does not silently
refetch, reserve calls or assert a new observation time.

`apply` uses `ledger._tx/_get/_put`. It revalidates CAS inside the transaction,
requires no bundle/revision/review/Astra review/approval/publication/social, and
rejects any request or effect row for this job. Unrelated jobs' effects do not
block it. The old theme and receipt are retained additively in
`sourceEnrichments` and the immutable ledger event history. Repeated application
fails CAS. Failure after a write rolls the transaction back.

The resulting job remains `held`, with `holdReason=source_enrichment_ready`.
Nothing is reset: no new job, stage-journal deletion, usage change, model-budget
reset or approval is created. The slug-derived article budget identity remains
the same. This is not a transition to candidate/autoproduction.

## Manual next step and image/brief binding

The caller must keep the job held until manual execution is explicitly ready.
Regather the complete new contract, refresh its independently verified owned
illustration and rebuild the source/renderer/stage dependency binding. Fit
bundles require the renderer evidence source IDs, source receipt SHA, PNG SHA
and composition hash to agree with the new reference set. Relabeling only an
old image's referenceIds or setting verified=true is rejected. The public image
policy remains owned illustration; this does not authorize manufacturer product
photos or merchant commerce.

The upper writing brief must use the verified product and part JANs distinctly,
with source qualifiers. It must not infer incompatibility from an absent row,
installation instructions, prices, stock, shipping or performance. New immutable
source inputs require new stage keys/manifest bindings and actual remaining
budget; historical successful/failed artifacts are retained. Approval and all
existing independent checks still apply.

## Verification

Offline tests use real-shaped H1/table HTML, forged row/cell variants, old
receipts, same-job SQLite transactions, public wrapper CAS, rollback, additive
history, unrelated effects and preservation of a nonzero real ModelBudget
snapshot. Fixture HTML and fixture usage records are synthetic, not paid model
executions. Separate read-only checks against saved actual public HTML confirmed
both fit capsules and the five-block pdpts excerpt; no native production state
was changed by those checks.
