# Camp editorial manager integration

The manager is an agenda selector and deterministic dispatcher over the existing
Runtime. It is not another producer, publisher, approval service, scheduler or
ledger. Runtime.tick now integrates Manager through _evaluate_manager under the
existing caller lock, before its legacy automatic-production branch. Managed mode
suppresses that branch; disabled or absent manager configuration retains the
legacy path. Source/approval/publication/social gates and the existing reporter
continue normally. The implementation is integrated locally. Deployment verification remains
Main-owned; the reported CLI v3 GUI result is recorded below as dated evidence,
not a claim of model execution by this implementation task.

## Integrated Runtime API (Boole)

The following illustrates the existing integration, not an additional caller to
install. Do not add another evaluation or producer invocation to Runtime.tick.

```python
from manager import Manager, Budget
from manager_cli import call

options = runtime.config['editorialManager']
manager = Manager(runtime.root, budget=Budget(**options['budget']))

def provider(request):
    return call(options['command'], request['snapshot'], request['prompt'],
                request['decisionSchema'], timeout=request['budget']['timeout_seconds'])

# INSIDE existing Runtime.tick, caller already holds runtime.flock.
# After consume/effects/delivery handling; before legacy automatic production.
result = manager.evaluate_locked(runtime, provider, handlers={
    action: runtime._queue_manager_work for action in
    ('improve_existing', 'investigate_sources', 'reconcile_unknown')
})
# Do not run the legacy automatic producer branch when manager is enabled.
# Runtime's existing owner/publication/social/reporter gates still run normally.
```

`evaluate_locked(runtime, provider, *, now=None, handlers=None)` accepts an aware
JST-converted time for deterministic tests; production can omit it. It returns a
small receipt dictionary with `status` and available evidence. It takes its own
nonblocking `manager.flock` while the caller retains `runtime.flock` throughout
snapshot → call reservation → decision → state recheck → execution → receipt.
Never nest another runtime lock inside that critical section.

Selected deployment configuration (explicit owner choice, not library defaults):

```python
{
    'editorialManager': {
        'enabled': True,
        'command': verified_immutable_managed_astra_base_argv,
        'budget': {
            'timeout_seconds': 180,
            'max_input_bytes': 131072,
            'max_output_bytes': 262144,
            'max_output_tokens': 12000,
            'max_calls_per_period': 24,
            'max_cost_usd': None,
        },
    },
}
```

Runtime._evaluate_manager validates `enabled` and constructs the provider; Manager never reads an env
file, discovers CLI flags, edits config or calls SSH. A missing Budget/provider
skips evaluation with `unconfigured`. There is no automatic model fallback.
`max_calls_per_period` counts reservations (including failed/invalid calls) in
SQLite, with one call maximum for each semantic state. The period is the existing
ProductionSchedule period, or `inactive` before its first active period.
The selected 24-call allowance is a ceiling across the production period, not a
target or a five-minute polling quota. Three new jobs can each produce several
meaningful source/correction, review, owner-decision and verified-publication
transitions; a higher ceiling than the initial small allowance avoids exhausting
agenda coverage during normal weekly work. It does not guarantee coverage of
every possible transition. Unchanged state, accounting changes, startup warnings
and provider failover consume no new call; failed/invalid changed-state calls do
consume the allowance. Do not fabricate transitions, delete receipts or increase
the cap automatically to use or replenish it. Inspect actual period call counts
and rejected/blocked receipts before any later budget adjustment. Keep the
existing shared CLI credits budget guard.

`max_cost_usd` is optional and nullable. Reported costs/tokens over configured
bounds reject execution after the call; this does not prove a monetary spending
cap was enforced. ChatGPT-auth CLI may report no USD invoice at all: accept null,
set `costMissing=true`, `usdCapEnforced=false`, and never convert credits to USD.
CommandProvider enforces bytes and elapsed time locally. The trusted CLI adapter
must enforce whatever token limit its verified CLI supports; post-call usage
validation is not a pre-call guarantee. Arbitrary injected Python callables must
honor the supplied deadline themselves; an elapsed-time check cannot interrupt
an arbitrary blocked callback. Use the managed bounded transport in production.


## Provider API (Lorentz)

The independent callable accepts one finite JSON-compatible request:

```python
{
    'schemaVersion': 1,
    'stateFingerprint': semantic_key(snapshot),
    'snapshot': sanitized_snapshot,
    'prompt': repo_prompt_text,
    'requestedModel': 'gpt-6-astra',
    'budget': configured_budget,
    'decisionSchema': DECISION_SCHEMA,
}
```

Manager reads `skills/camp-editorial-manager/references/prompt.md` from the repo
on each changed-state evaluation. Merely editing a prompt, changing a provider,
or restarting a process does not create a new editorial semantic state or retry
a prior failed call. Deployment changes requiring reevaluation must use an
explicit, reviewed state transition, not delete receipts.

The managed adapter `call(command, snapshot, prompt, schema, timeout=...)` writes
the fixed schema securely, supplies an empty temporary cwd and full safe context
on stdin, and pins the independently verified Astra route without fallback.
Its stdin envelope must include `semantic_key(snapshot)` alongside snapshot and
instructions. `semantic_key` is exactly SHA256 of UTF-8 JSON with `sort_keys=True`,
`ensure_ascii=False`, `separators=(',', ':')`, `allow_nan=False`; do not remove any
additional fields. Manager's snapshot has already removed irrelevant clocks.

Expected response envelope (five required keys, optional sanitized warnings):

```json
{
  "decision": {
    "stateFingerprint": "<exact snapshot SHA256>",
    "summary": "A bounded explanation of the next agenda item",
    "actions": [{
      "action": "wait",
      "jobId": null,
      "targetUrl": null,
      "revision": null,
      "expectations": {
        "stage": null,
        "revision": null,
        "socialRevision": null,
        "approvalCurrent": false,
        "published": false,
        "socialPosted": false
      }
    }]
  },
  "requestedModel": "gpt-6-astra",
  "actualModel": null,
  "usage": {"input_tokens": 0, "output_tokens": 0},
  "actualInvoiceUsd": null
}
```

Usage may be
null; otherwise only nonnegative integer `input_tokens`, `output_tokens`,
`cached_input_tokens`, `cache_write_input_tokens`, `reasoning_tokens` are accepted.
The adapter normalizes an actually reported `reasoning_output_tokens` to
`reasoning_tokens`; it must not invent zero values for missing measurements.
An optional envelope `warnings` is accepted only as
`{preTurnErrorCount: integer_1_through_16, code: "unknown", toolsStartupVerified: false}`.
This preserves opaque pre-turn diagnostics without their raw message, ID, tool
name or contents and does not prove tool startup succeeded or grant authority.
Only strict scalar error diagnostics after thread.started and before turn.started
can become this warning. The trusted adapter rejects more than 16 such entries,
unknown usage fields and colliding reasoning aliases. It must still reject
post-turn errors, tool calls, missing
completion and multiple/non-schema finals. Warning evidence stays in receipts,
not the semantic snapshot, so it cannot create recurring model evaluations.
Runtime health exposes a deliberately smaller projection; canonical warning
evidence is in the SQLite manager receipt, not proof of healthy tool startup. Zero here illustrates
schema, not measured usage. `actualModel` is null when the CLI does not report it;
never copy requestedModel into actualModel. A returned model conflicting with the
pinned Astra model is rejected. Receipts distinguish configured route assurance
from an actually returned matching model ID.

`DECISION_SCHEMA` exported by manager.py is the CLI output schema (decision only,
not the whole envelope). It rejects extra keys and permits exactly one action per
evaluation, preventing cascading unreviewed actions. Every action requires all
five action keys, including nullable targetUrl. Expectations are six fixed fields,
not arbitrary state or approval capabilities. An unbound action uses the shown
null/false expectations, not an arbitrary or empty object.

## Dispatch and work orders

| Action | Required binding and behavior |
| --- | --- |
| wait | No side effect; job may be null. |
| start_period | Null job/revision/targetUrl/default expectations. Due+enabled period, zero normal period jobs, spare pending capacity, no existing normal candidate or research marker/unknown effect. Calls existing `runtime.produce(limit=1)` only. |
| produce_existing | Exact normal candidate/revision/expectations and `production.nextCandidateId` in Ledger.list_jobs rowid order, retaining its original period/slot across Friday boundaries and normal gates. Calls existing `runtime.produce(limit=1)` only; never retry/reset an error or reset an old-period slot. |
| improve_existing | Exact job/revision or exact verified `metrics.opportunities[].url` with null job/revision/default expectations. Calls injected proposal-queue API only, including for an already published/posted job; posted immutability blocks reproduction/delivery, not proposal-only work. It may queue source-verified material corrections/private attachment work; cannot attach arbitrary model-authored facts or mutate a draft/publication. |
| investigate_sources | Exact job/revision, injected read-only investigation work order. |
| deliver_reviewed | Exact job/revision, current valid bundle/review; corrected/revision jobs require independent Astra QA. Calls existing Runtime.deliver, not Slack directly. Existing requests/journals prevent duplicate delivery. |
| reconcile_unknown | Exact job/revision, injected read-only reconciliation work order. No restart/resend. |

Handlers receive `(Plan, snapshot)`. Plan exposes `action`, `job_id`, `target_url`,
`revision`, `state_fingerprint`, `expectations`. Return only status `completed` or
`blocked`; unknown/exception/other responses become `requires_reconciliation`.
Manager stores no handler body, personal attachment, request nonce or arbitrary
transport output. Missing handlers block that work order. The integrated Runtime._queue_manager_work
creates deduplicated, bounded human_needed work orders in the existing SQLite
meta/events (at most 100 stored orders), without changing jobs or executing
source investigations/retries. Health exposes pending counts and a bounded
projection, not private order bodies. Proposal handlers must enforce their own
queue deduplication and source/approval gates. Do not implement
unlimited authoring as an improvement handler. Boole/Main owns the narrow private
correction attachment API. No manager action approves, publishes, posts to X,
writes Buffer, or sends report/reminder messages.

An execution marker is committed before invoking any handler/producer/delivery.
A process crash leaves `evaluating`/`executing` in SQLite. Same-state evaluations
are skipped even after failure/failover. Outstanding execution uncertainty also
blocks changed-state dispatch until the trusted integration reconciles the exact
receipt in SQLite using actual effect/readback evidence. Never delete markers or
blindly rerun work to manufacture success. Read-only operator reconciliation is
outside the model's authority; an explicit bound reconciliation receipt must
replace the unresolved status only after proof, preserving immutable events.

## Snapshot and state keys

Read one SQLite transaction: rowid-ordered jobs, sanitized latest state flags,
effect statuses, request status/revision/expiry state, and semantic event kinds.
Delivery journal bindings additionally expose requestStatus, currentRevision and
historicalNonblocking. Invalidated/decided requests or proven superseded request
versions are historical/nonblocking; their retained unfinished delivery journal
is not itself an unknown publishing/social effect. The manager does not delete
these journals or clear actual effects. Current unknown/in_flight side effects
still block their own job; globally unresolved manager execution blocks dispatch.
The agenda prompt prioritizes eligible candidate/period production over these
historical diagnostic work orders, preventing historical receipts from consuming
the sole action while current candidates wait.
Manager events are excluded from its own trigger. `catalogCorrection` explicitly
tracks presence of the bound correction context; body/credentials remain private.
Existing state journals expose only status/phase/presence and non-capability
job/revision/period bindings. Delivery request IDs and filenames never leave the
private reader. No owner/request nonce, source body, raw search query, credentials
or personal-data body crosses this boundary.

GA4/GSC use existing Analytics validation for freshness, source date periods,
timezone/settlement/coverage/missingness. Aggregates retain unknown vs zero.
At most three sanitized opportunities retain exact public Camp article URL,
statistics, source periods and uncertainty. URL target must exactly match that
snapshot's verified opportunity, on `https://camp-gear-lab.com/articles/<safe-slug>`;
no fabricated URL, query string or other host is eligible. A URL target is not a
managed job ID. Sales remain unconnected unless the collector supplies an independently
verified sales integration; missing sales are not zero. External queue connection
and knowledge come from the sanitized current input, never historical notes.

Snapshot keys exclude generatedAt/updated_at/collectedAt clocks, model usage,
free balance and manager receipts. Meaningful period/due/expiry/freshness changes
still trigger; identical fresh recollection does not. Fingerprint comparisons
before dispatch reject stale state. SQLite meta stores plan/call projections and
immutable events, not another ledger or authoritative JSON job store.

Production periods and initial activation come from current productionSchedule;
Friday 09:00 JST / Friday–Thursday remains the preferred policy, subordinate to
that configuration. Optional top-level `config.initialTargetPublishBy` is a valid
ISO date (`YYYY-MM-DD`), projected as `production.initialTargetPublishBy` or null;
it never grants publication authority. Held/reopened/published and current
approval state always come from the current snapshot.

`config.editorialManager.externalQueue` is an optional trusted-source input:
`{provider: 'Buffer', connected: bool|null, status: 'unknown'|'verified',
evidenceFingerprint: SHA256|null}`. Missing input yields connected=null and
status=unknown. A connected flag describes the configured connection, not queue
coverage; verified queue knowledge requires a current verifier-supplied evidence
fingerprint. Main owns freshness/coverage verification and updates that input
when its evidence changes. Raw queue bodies, account credentials and owner data
are excluded. Connection changes do not grant this manager queue-write authority.

## Initial observations — 2026-11-08 JST (historical, not instructions)

The task handoff on this date reported three initial error jobs occupying the
retention cap, three article updates awaiting owner approval, an initial Nov 8
activation and a Nov 12 target conditional on owner approval. It also reported
SOTO already posted on Nov 8: main `2119429207503806861`, reply
`2119429214504104135`. Buffer managed the account but was not connected to this
workflow, so future queue status was unknown. These are dated handoff observations,
not a fresh production readback. They must never override later SQLite status,
configuration, source verification or bound publication evidence. The existing
reporter schedules were Monday 20:00, Thursday 20:00 and monthly day 5 20:00 JST;
the manager does not reschedule them or duplicate their messages.

## Reported CLI v3 check — 2026-11-09 00:00:01 JST

Main reported one actual v3 GUI CLI check with a schema/fingerprint-valid result:
input_tokens 20175, output_tokens 464, reasoning_tokens 189, actualModel null,
actualInvoiceUsd unreported, and four opaque unknown pre-turn startup warnings.
The chosen historical delivery reconciliation prompted the request-status/current-
revision annotations and candidate-first priority above. This is Main's reported
observation, not an additional model run or independent reproduction here. No
journal was deleted and no post was resent by this task.

## Offline verification

```sh
python3 -m unittest discover -s scripts/editorial -p 'test_manager.py'
python3 -m unittest discover -s scripts/editorial -p 'test_*.py'
python3 /Users/NaohideKin/.codex/skills/.system/skill-creator/scripts/quick_validate.py skills/camp-editorial-manager
```

Tests use synthetic sources, a temporary real SQLite and the normal Runtime with
injected model/Slack/publish fakes. No real CLI model, SSH, Slack or provider write
is needed. Main symlinks the canonical repo skill folder into host discovery paths separately;
never make ~/.codex a synchronized Git repository.
