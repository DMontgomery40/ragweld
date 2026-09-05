# Native indexing accounting

LiteLLM is the per-request spend ledger. Ragweld adds aggregate checkpoints to
the existing index-run summary so an operator can distinguish observed charges
from a quote, delayed ingestion, interrupted work, and missing price evidence.
The execution log in `docs/exec-plans/active/graphrag-continuation-2026-09-04.md`
records whether this implementation has been deployed and accepted.

## Reading the operator view

Indexing displays the selected run's saved quote and native reconciliation.
Dashboard selects the run belonging to the active index manifest. A newer failed
attempt or schema proposal does not replace the active generation's cost display.
Schema proposals have separate attempt IDs, including failed attempts. Reloading
the page can recover their accounting through latest proposal history.

- **Pre-run quote:** the original configuration and prices captured before work.
  It does not change when the current corpus configuration changes.
- **Provider-reported subtotal:** native evidence containing a supported provider
  charge. Other measured calls remain in the separately labeled gateway-calculated
  subtotal. Neither subtotal implies an invoice total.
- **Pending:** actual work or native ingestion has not settled. Browser retries
  are bounded; manual refresh remains available.
- **Incomplete:** interrupted ownership, uncertain requests, missing measurements,
  uncovered routes, unknown prices, or unverified gateway attempt policy prevent
  a complete total. A missing measurement is never converted into a free call.
- **Processed denominators:** files, chunks and tokens handled by the attempt,
  including a failed attempt. They are distinct from promoted index counts.

The generated gateway disables router and provider SDK retries and fallback
families. Native management endpoints do not establish every effective cached SDK
setting; the current run record therefore retains the unverified-policy qualifier
for paid lanes. A successful fixture proves the tested configuration, not every
future deployment override.

## Lifecycle and history

Every outbound attempt is acknowledged in a durable lane census before transport
dispatch. Producer leases remain open until actual asynchronous or threaded work
finishes, even after the request coroutine is cancelled. A process lifetime lock
distinguishes retained work from an abandoned process. An abandoned census remains
explicitly interrupted; ledger rows cannot reconstruct a closed census.

Summaries retain their original corpus, run, models, gateway root and quote.
Deindexing and deleting a corpus preserve these historical records. Current status
for a deleted corpus returns404; explicit history remains readable:

```text
GET  /api/index/{corpus}/runs/{run}
GET  /api/index/{corpus}/runs/latest
GET  /api/index/{corpus}/runs/latest?run_kind=schema_proposal
POST /api/index/{corpus}/runs/{run}/costs/reconcile
```

Reconciliation uses the saved gateway root and the current private gateway key.
It reads bounded, authenticated native spend-log pages and requires exact run,
corpus and lane matches. Concurrent checkpoint changes invalidate an older read.
Credential or gateway errors are saved without erasing a newer result.

## Proxmox activation

Run deployment and runtime commands on LXC100, with the reviewed source deployed
at `/opt/ragweld`. The Mac checkout is source only. Before recreating a gateway or
restarting the API, inspect every corpus status and any retained accounting workers.
An idle browser alone does not establish quiescence.

The provisioner uses existing owner-only files under `/etc/ragweld`. It creates
the dedicated `ragweld_litellm` database and constrained role, preserving unrelated
environment settings and existing credentials. It refuses foreign resources,
role memberships, conflicting destinations and unsafe retry or prompt-storage
settings. It copies the existing Langfuse project identity without rotating it.

```bash
/opt/ragweld/.venv/bin/python /opt/ragweld/deploy/proxmox/provision_litellm_ledger.py provision --apply
/opt/ragweld/.venv/bin/python /opt/ragweld/deploy/proxmox/provision_litellm_ledger.py migrate --apply
```

Neither command restarts the gateway. Migration output stays in the owner-only
`/etc/ragweld/litellm-ledger-migration.log`; inspect it privately on failure.
After successful migrations, recreate the gateway through the existing Proxmox
deployment procedure during an idle interval. Verify the deployed commit marker,
readiness, one controlled run, native reconciliation, browser reload, and the
existing Langfuse and Mimir surfaces. Preserve native data during a code rollback;
do not drop the ledger to repair an application deployment.

## Trace and metric ownership

One run observation supplies the parent context across schema, semantic graph and
figure-description calls. Explicit W3C propagation survives worker threads. The
gateway emits native Langfuse generation events; the app retains request and stage
spans, trace links and aggregate summaries without emitting duplicate generations.
Run, corpus and lane metadata identify traces. Mimir metrics add only the bounded
lane label, never run or corpus identifiers.

Native spend-log prompt storage and native tracing content capture are separate
controls. The generated gateway disables both prompt storage and message logging;
the private environment also disables GenAI message-content capture. Native
fixture tests check exported attributes for input/output sentinels as well as
trace identity, usage and metric labels.

The pinned LiteLLM 1.94 proxy-failure hook omits custom metadata labels on its
proxy failure/total samples. Those samples cannot reliably be grouped by lane.
Successful lane-labeled series, native spend rows and trace observations are
distinct evidence; an aggregate scrape containing a lane does not establish
failure-lane coverage. A failed native trace may also contain a zero cost
placeholder with no token usage. That is not evidence of a free provider call.

Langfuse UI health establishes reachability only. A lookup link does not establish
that a generation was emitted or ingested; the native gateway configuration and
actual per-run observation must be checked separately.
