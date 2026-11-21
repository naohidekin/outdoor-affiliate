# Camp topic demand selection implementation plan

> For agentic workers: implement the bounded tasks below, then independent review.

Goal: rank new weekly articles by relevant observed search needs, owner-requested seasonal/apparel/brand comparison value, and distinct reader decisions; route narrow/overlapping ideas to existing updates.
Architecture: existing GSC snapshots already contain private query aggregates. Locally project those into controlled topic facets and measured metrics with no raw query text. Existing AI proposes up to nine candidates once; deterministic code verifies source/topic relevance, ranks needs, checks full local article sections/FAQ, and selects three within the existing weekly slots. Existing passed period selections are not reranked.
Tech stack: existing Python analytics/selector/runtime, SQLite ledger, existing metrics collector. No added AI calls, external trend provider, scheduler, credential scope, cap increase, or publication authority.
Spec: current owner request in this chat, 2026-11-22 JST; prior weekly-three and separate owner article/SNS approval rules remain authoritative.

Global constraints: article32 calls/period128 and existing token budgets; standard3/period and shared pending3; real Gemini polish/Claude review and mandatory facts/images/links/visible render/WISE floors; article and SNS exact-version owner approval separately; no raw query strings to models; missing evidence is not zero; own-site GSC is not market search volume; no forced 3 weak topics when qualified pool insufficient.

Review focus: unrelated high-traffic signals must not justify a candidate; absent prior query cluster is unknown; body/FAQ duplicate outside first8 headings must be caught locally without expanding model input; narrow topic with no exact suitable existing target must hold; historical selected receipts/jobs/owner approvals remain unchanged.

- [x] Task1 search demand projection: new search_demand.py and tests, analytics.py integration. classify_topic(text) returns only controlled facets. project raw query aggregates into <=40 bounded groups, retaining date/coverage/observed counts/weighted averagePosition and optional comparable previous metrics; never raw query, never extra API/AI.
- [x] Task2 deterministic selection: topic_selection.py + tests. Export new sanitized demand signals. Match demand facets to title/reader question/query, distinguish direct demand vs related own-site proxy, prioritize seasonal/apparel/comparison among measured relevant candidates, retain source gates. Check rich existing section/FAQ index, route narrow/overlap to exact existing update target or hold. Rank programmatically ahead of model priority, maintain3/pending and history behavior.
- [x] Task3 runtime integration: preserve compact model summaries, use richer local article index for duplicate checking, pass bounded selection rules/signals, save versioned selection/needs/update candidate receipts. Route update candidates to existing proposal queue without editing/publishing articles. No new tick/AI manager loops.
- [ ] Task4 independent tests/review and native read-only verification. Test direct and irrelevant evidence, duplicate FAQ/sections, narrow routing/no target, date/zero/privacy, priorities, unchanged caps/approval/history. Fetch/preserve edits, commit/push focused changes, fast-forward native, compare config/state boundaries. No extra production jobs or current-period regeneration.

Local verification: 1,470 Python tests PASS; independent review approved after demand missing-metric and cross-garment update routing fixes. Native read-only projection verification pending deployment.
