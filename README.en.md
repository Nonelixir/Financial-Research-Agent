# Financial Research Agent

[中文](README.md)

A lightweight, provenance-first financial research workbench. The model chooses SEC, public web, retrieval, financial-data and computation tools over multiple turns. Companies/years are optional preferences; strict scope constrains access. Real XLSX and Markdown deliverables are supported; ordinary answers are not artifacts.

This is a single-user prototype: FastAPI, Pydantic AI, SQLite WAL/FTS5 and session file directories, with React/assistant-ui/AI Elements.
Python/shell execution is unavailable. Fiscal-period semantics, numeric validation and retry recovery have known issues. Hallucination-free output and superiority over ChatGPT are not established.

## Quick start

Python≥3.12 and uv; frontend build requires Node 22+ and npm. From this repository root:

```bash
uv sync --extra dev --extra agent
cp .env.example .env
npm --prefix frontend ci
npm --prefix frontend run build
uv run uvicorn finagent.api:app --host 127.0.0.1 --port 8000
```

Do not overwrite an existing `.env`. Configure a real SEC contact identity and your model endpoint/secret/name:

```env
SEC_IDENTITY=Financial Research Agent your-email@example.com
LLM_BASE_URL=https://provider.example/v1
LLM_API_KEY=your-server-side-key
LLM_MODEL=your-model
LLM_API_MODE=responses
```

Compatible `responses` / `chat_completions` providers are supported; OpenRouter is not required. Secrets stay server-side.
Without a model, extractive/deterministic-table fallback remains, not autonomous deep research. Build the UI; production needs no Node server.
UI: http://127.0.0.1:8000/ ; API: /api/docs; liveness: /api/health, not model/SEC readiness.
For trusted-network access, bind 0.0.0.0 behind proper controls. No authentication is built in; do not expose directly to the public internet. Use one process/worker.

## Current documentation

Verified: 2026-10-13. Each module has Chinese and English versions describing current implementation only.
Transitional designs, repair histories and evaluation-report Markdown have been removed. Code/machine schemas are authoritative; keep both languages synchronized.

| Module | English | 中文 |
| --- | --- | --- |
| Architecture | [Read](docs/en/architecture.md) | [整体架构](docs/zh-CN/architecture.md) |
| Agent, tools and prompts | [Read](docs/en/agent-tools.md) | [Agent 与工具、Prompt](docs/zh-CN/agent-tools.md) |
| SEC, web and retrieval | [Read](docs/en/sources-retrieval.md) | [SEC、网页与检索](docs/zh-CN/sources-retrieval.md) |
| Financial data and computation | [Read](docs/en/financial-computation.md) | [财务数据与计算](docs/zh-CN/financial-computation.md) |
| Provenance and validation | [Read](docs/en/provenance-validation.md) | [Provenance 与校验](docs/zh-CN/provenance-validation.md) |
| Sessions, storage and artifacts | [Read](docs/en/sessions-artifacts.md) | [会话、存储与产物](docs/zh-CN/sessions-artifacts.md) |
| Frontend and language interaction | [Read](docs/en/frontend.md) | [前端与语言交互](docs/zh-CN/frontend.md) |
| API contracts | [Read](docs/en/api.md) | [API 契约](docs/zh-CN/api.md) |
| Configuration, deployment and operations | [Read](docs/en/operations.md) | [配置、部署与运维](docs/zh-CN/operations.md) |
| Testing, capabilities and known limits | [Read](docs/en/testing-capabilities.md) | [测试、能力与已知限制](docs/zh-CN/testing-capabilities.md) |
| Interactive architecture | [English HTML](docs/diagrams/architecture.en.html) | [中文 HTML](docs/diagrams/architecture.zh-CN.html) |
| Third-party components | [Notice](frontend/THIRD_PARTY.en.md) | [说明](frontend/THIRD_PARTY.md) |

Rebuilt with archify; JSON is the source, with built-in themes, zoom, search and export.
Maintenance/acceptance receipts: [English](docs/en/diagrams.md) · [中文](docs/zh-CN/diagrams.md).

## Source map

```text
src/finagent/
  api.py                 HTTP/SSE, default and compatibility paths
  agent.py               Model loop, tools, output gates
  research_tools.py      On-demand research capabilities
  data/ retrieval/       SEC, facts, HTML and FTS5
  compute/ verify/       Expressions, source lookup, answer checks
  storage.py             SQLite, source caches
  workspace.py           Threads, history, artifact metadata
  filesystem.py tools.py Restricted files, explicit delivery
  export/                XLSX
  prompts.toml           Editable prompt configuration
frontend/                React UI and third-party notices
docs/zh-CN/ docs/en/      Current module documentation
docs/diagrams/            Current diagram/source
tests/ eval/              Tests, synthetic example and evaluation runners
```

Runtime data defaults to `.data/`; SEC caches are in SQLite, session files in `.data/workspaces/<thread_id>/`.
The sibling `sec-filing-room` is obsolete, not this running implementation or documentation set.

## Verification and limits

```bash
uv run pytest -q
uv run ruff check src tests eval/runners/financebench_pilot.py
npm --prefix frontend run build
```

Current tests: 97 passing; Ruff passes. The fixed live-model FinanceBench pilot delivered 9/10 correct complete core answers (90%) in verification-opt-v1 versus 6/10 in baseline and previous v4.
This task stopped after one iteration upon reaching its 80% target. Mean time: 36.448 seconds versus v4 44.85 and baseline 70.39 seconds.
Model/budgets and questions/gold stayed unchanged. Ulta target-period ambiguity remains incorrect. This single development regression with mixed warm caches and stochastic output does not establish accuracy on unseen questions.
Raw JSON/events/citations/reviews remain locally in `eval/results/` and are excluded from the public repository. The fixed FinanceBench sample is also excluded pending redistribution review.
The public runner requires a separately prepared, permitted sample matching its input schema. These scores are local development results, not an independently auditable benchmark bundled with this repository.
No full benchmark, bare-model/ChatGPT comparison or full report-delivery benchmark exists.
See testing/capabilities for methodology; passing tests do not establish investment correctness.

## Publication scope and licensing

The repository contains effective source code, tests, dependency locks, configuration examples, current bilingual module documentation and architecture diagrams.
Credentials, real `.env` files, databases, session/download artifacts, logs, dependencies, build outputs, independent product research and local acceptance files are excluded.
The project license has not been selected; public visibility does not grant an open-source license. See third-party notices for component requirements.

## Maintenance policy

Tools/prompts→Agent; sources/index→retrieval; metrics/periods→financials; references/checks→provenance;
threads/files→artifacts; interaction→frontend; routes→API; settings/deployment→operations; feature bounds/tests→capabilities.
Architecture changes require both JSON sources and renewed validation.
Update both languages, verification date and README together; do not append obsolete workflow snapshots or process design documents.
