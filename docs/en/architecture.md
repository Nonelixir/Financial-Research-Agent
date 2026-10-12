# Architecture

[中文](../zh-CN/architecture.md) · [README](../../README.en.md)

Verified against current implementation: 2026-10-12.

## Runtime shape

One FastAPI/Uvicorn Python service serves API, SSE and the built React UI. Node is not needed in production.
SQLite WAL/FTS5 stores structured data, citations, source snapshots, sessions and artifact metadata; local session directories hold files.
There is no Redis, vector database, queue, worker or accepted code-execution backend. This is a single-user research prototype, not a multi-tenant terminal.

## Component responsibilities

| Component | Code | Responsibility |
| --- | --- | --- |
| Workbench | `frontend/src/main.tsx` | Chat, scope, plans, tool states, citations and artifacts |
| HTTP/events | `src/finagent/api.py` | Routes, model dispatch, event queue, timeout, static assets |
| Sessions | `src/finagent/workspace.py` | History, active-run lock, edits, file metadata, downloads |
| Agent | `src/finagent/agent.py` | Model configuration, tool registration, evidence, output and retries |
| Research tools | `src/finagent/research_tools.py` | Company/industry discovery, SEC/web/facts, computation and plans |
| Data | `src/finagent/data/`, `retrieval/` | SEC, fact selection, HTML chunks, FTS5 |
| Validation | `verify/`, `compute/evidence.py` | References, numeric checks, source lookup and expression replay |
| Files | `filesystem.py`, `tools.py`, `export/xlsx.py` | Restricted files, explicit publishing and verified workbooks |

## Default request lifecycle

1. Browser submits a question, optional scope and language; the session endpoint stores a user message and a running placeholder.
2. Session context includes bounded history, historical citation IDs, artifact summaries and the saved research sample.
3. The agent chooses tools on demand; tools register new evidence for subsequent model turns. There is no mandatory all-metrics prefetch.
4. Output becomes Answer/Claim. Only closed, checked claims enter public answer snapshots.
5. Files require explicit creation/publication. SSE carries states, sources, plans, samples, artifacts, answers and terminal status.
6. On completion/cancellation, the session stores the last answer and events. A restart does not resume an unfinished model task.

## Diagram and boundaries

[English diagram](../diagrams/architecture.en.html) · [Chinese diagram](../diagrams/architecture.zh-CN.html).
Publication checks summarize answer/file gates; they do not imply semantic validation on every download. Storage relationships are simplified.
Model requests and tool results form a loop; the model edge summarizes communication, not a one-way fixed pipeline.

A legacy path remains when `AGENTIC_RESEARCH=false` or a model is not configured: scoped ingestion, fixed context and explanation/extractive fallback.
Distinguish that compatibility path from the default autonomous entry point.
