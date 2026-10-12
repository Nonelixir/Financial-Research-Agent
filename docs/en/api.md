# API contracts

[中文](../zh-CN/api.md) · [README](../../README.en.md)

Verified against current implementation: 2026-10-12.

## Base contract

`api.py` and `workspace.py` expose Swagger at `/api/docs`, OpenAPI at `/api/openapi.json`; machine schemas are authoritative.
There is no authentication, tenant isolation or authorized download layer. IDs are not permissions. Use a trusted network/single-user deployment.
Scope includes language(zh/en), companies[{cik,ticker,name,aliases}], strict, forms, fiscal_years and restatement_policy.
Defaults: empty company/year lists, strict=false, 10-K/10-Q, latest_restated; schema allows up to 30 companies.
Settings.max_companies is not a universal autonomous-tool cap; do not promise every layer enforces three companies.

## Routes

| Method/path | Contract |
| --- | --- |
| GET /api/health | Liveness only; not full model/SEC/database readiness |
| GET /api/companies/search?q= | Local first then SEC; query 1..100 chars |
| POST /api/ingest | Scope; explicit cache ingestion, not mandatory before chat |
| POST /api/ask | AskRequest→Answer; no session file tools |
| POST /api/ask/stream | AskRequest→SSE; not the default persisted entry point |
| GET /api/execution/capabilities | execution.available=false |
| POST /api/tables | TableRequest→deterministic ComparisonTable |
| POST /api/exports/xlsx | Direct download, no session artifact registration |
| GET /api/sources/{citation_id} | Registered Citation; missing→404 |
| GET/PUT/DELETE /api/profile | profile_id/default and UserProfile; no automatic long-term memory |
| GET/POST /api/threads | List/create |
| GET/PATCH/DELETE /api/threads/{id} | Read/rename/delete; active deletion→409 |
| GET /api/threads/{id}/files | Work file index |
| POST /api/threads/{id}/artifacts/table | TableRequest→session table artifact |
| POST /api/threads/{id}/messages/stream | question, scope, optional replace_from; persisted SSE |
| GET /api/artifacts/{id}/download | Real file/hash check; additional table-data validation |
| GET /api/artifacts/{id}/xlsx | Compatibility download alias, not all artifacts are XLSX |

Session question length is 2..4000, title 1..100; consult OpenAPI/schema for exact bounds.
TableRequest carries scope, metrics and periods; frequency belongs to the Agent workbook tool, not this request. HTTP endpoints are not model tools.

## Persisted request example

```json
{
  "question": "Analyze AAOI's last two complete fiscal years.",
  "scope": {
    "language": "en", "companies": [], "fiscal_years": [],
    "strict": false, "forms": ["10-K", "10-Q"],
    "restatement_policy": "as_reported"
  }
}
```

POST /api/threads, then POST /api/threads/{id}/messages/stream.
Browser abort cancels SSE; there is no separate durable background-task cancel endpoint.

## Events/status

SSE uses event: name and data: JSON. Events include message.created, status, sources, plan, sample, artifact, answer.snapshot, error and done; legacy paths may add events.
answer.snapshot contains claims[{text,citation_ids,numeric_bindings?}], caveats, status and status_reason.
Tool status contains phase/state/tool_call_id/message/detail; distinct calls must not collapse solely by phase.
done is a terminal transport marker. complete means current gates passed, not correctness, complete data or full grounding.
Preserve partial/incomplete on errors/cancellation; an empty answer is not successful delivery. Source API 200 is not a semantic score.

## Failures

400/422 invalid inputs; 404 missing entities; 409 active sessions/file changes/table validation; 502 explicit SEC ingestion failure.
In-stream tool errors may not use HTTP error codes: inspect status details and final status_reason.
No event-ID replay/resumption after disconnect; reload persisted thread state.
