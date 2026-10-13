# Testing, capabilities and known limits

[中文](../zh-CN/testing-capabilities.md) · [README](../../README.en.md)

Verified against current implementation: 2026-10-13.

## Capability levels

| Capability | Current status |
| --- | --- |
| Autonomous research without preselected companies | Implemented; industry search experimental, samples non-exhaustive |
| Historical SEC directory, 8-K, declared exhibits | HTML/TXT implemented; origin/directory availability limits remain |
| Annual/quarterly 22 metrics | Partial coverage; missing retained, not all metrics |
| Registered arithmetic/input lineage | Bounded arithmetic/replay implemented, no method semantics proof |
| Source/value citations and claim-end buttons | Implemented, not comprehensive sentence/number entailment |
| Persistent threads/bounded history | Implemented; no task resumption or unlimited memory |
| Real XLSX/Markdown artifacts | Implemented with different assurance levels; delivery can fail |
| Chinese/English UI/output requirements | Implemented for later requests; originals/history unchanged |
| Python/shell | Not implemented, always rejected |
| PDF/OCR, vector RAG, global comparable financials | Not implemented |
| Auth, multi-tenancy, isolated production execution | Not implemented |

## Known issues that must remain visible

- Fiscal-year/document-year ambiguity lacks a deterministic target-period gate; real evidence can be from the wrong year.
- HTML tables lack structured row/column/unit extraction; narrative digits only have literal support.
- Money parsing distinguishes formula/accounting parentheses and supports m/b/k/bn. Narrative outflow bindings still check negative literals and nearby wording without proving table row/column identity; narrative losses may require retries.
- Copied IDs/spans, wrong metrics/units may exhaust output retries.
- Frozen published prefixes conflict with retry rewriting; recoverable claims can contain semantic duplicates.
- Industry/sample coverage and causal extra assertions are not independently proved.
- Report-request recognition uses bounded keyword patterns, not robust general intent detection.
- Snapshots exist without complete immutable-version foreign keys, mandatory all-number bindings or semantic verification.
- Global SEC throttling, hard quotas, durable tasks and multi-process coordination are absent.

These are current use/maintenance boundaries, not a roadmap. complete/verified/200 is not proof of investment correctness.

## Local verification

```bash
uv run pytest -q
uv run ruff check src tests eval/runners/financebench_pilot.py
npm --prefix frontend run build
```

Current suite has 97 pytest cases covering facts/differences/verification, references, simulated streams/retries, files, languages, SEC mocks, unsafe AST, tampering and scope.
Counts evolve; record real runs. Unit tests do not measure model quality; builds do not prove browser usability.

## Existing evaluation method

`eval/dataset/financebench-pilot-10.json` fixes ten English questions drawn from FinanceBench's public 150 with seed=42.
This fixed sample and `eval/results/` are local-only, excluded pending licensing/privacy review.
Prepare a permitted sample matching the runner schema before using the command below; its default sample path does not exist in a fresh clone.
The real HTTP runner creates threads and sends questions plus target document names; gold/evidence remains evaluator-side.
Client budget 180 seconds/question, concurrency two, open company/year scope, as_reported, English; server budget is separate.
Model gpt-5.6-luna, Responses, 4000 normal output tokens, 60 tools, two retries; live sources and mixed warm caches.
Files retain metadata (including sample-file and source-code SHA256), gold, per-case events/answers/sources/persisted threads, results.jsonl and review.json.
Token/cost are unavailable, never zero. Numeric/accession judges do not replace entailment review.

```bash
uv run python eval/runners/financebench_pilot.py \
  --sample eval/dataset/financebench-pilot-10.json \
  --output eval/results/new-run \
  --timeout 180 --concurrency 2
```

Use a new output directory. Health is checked first, but not full model readiness. Runs create real threads/cache entries, not read-only diagnostics.

## Defensible current conclusion

Raw baseline/v2/v3/v4 data remains. The invalid startup run is marked separately and excluded.
Baseline and previous v4 each delivered 6/10 correct complete core answers. Current verification-opt-v1 delivered 9/10 (90%), mean 36.448 seconds versus v4 44.85 and baseline 70.39 seconds.
All ten current answers completed, but Ulta used the wrong target period and counts as incorrect. All final answers were revalidated; 48/48 citation API fetches succeeded.
This task stopped after one iteration because the 80% target was reached. Model/budgets and questions/gold stayed unchanged. Local verification-opt-v1 retains raw traces, source snapshots, review and further optimization directions.
Next priorities are document-year/issuer-FY resolution, publication after full validation, structured tables and bounded metric aliases, followed by unseen questions and repeated runs.
These questions informed development, so results are development regressions, not independent holdout scores. Cache/randomness/early failures affect latency.
No bare-model/ChatGPT comparison, full FinanceBench or end-to-end report/XLSX benchmark was run; superiority over ChatGPT is unproved.
Formal review requires fixed budgets/corpus cutoff, full traces, semantic/period/numeric/delivery review, unseen samples and repeated runs.
