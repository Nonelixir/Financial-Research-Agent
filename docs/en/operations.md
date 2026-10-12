# Configuration, deployment and operations

[中文](../zh-CN/operations.md) · [README](../../README.en.md)

Verified against current implementation: 2026-10-12.

## Setup and startup

Python≥3.12 and uv; frontend builds require Node 22+ and npm with package-lock. From repository root:

```bash
uv sync --extra dev --extra agent
cp .env.example .env
npm --prefix frontend ci
npm --prefix frontend run build
uv run uvicorn finagent.api:app --host 127.0.0.1 --port 8000
```

Do not overwrite an existing .env. Node is not required in production, but build the UI; otherwise the legacy static page is used.
/api/health is liveness, /api/docs is API documentation. Test one real research request to check provider compatibility.
Startup does not prove SEC/model/XLSX functionality. Use a trusted network; remote access may bind 0.0.0.0 behind authenticated TLS ingress.
Authentication is not built in. Use a single process/worker: active_threads is not shared across workers.

## Settings

`config.py` reads environment/.env (environment wins); get_settings is cached, so restart after changes.
Prompt TOML is reread per request, unlike environment settings.

| Setting | Default | Meaning |
| --- | --- | --- |
| DATABASE_PATH | .data/finagent.sqlite3 | SQLite and default workspace base |
| SEC_IDENTITY | Financial Research Agent analyst@example.com | Replace with real contact identity |
| SEC_REQUESTS_PER_SECOND | 5 | Per-client throttle, 0.5..10 |
| REQUEST_TIMEOUT_SECONDS | 30 | SEC HTTP timeout, 5..120 |
| LLM_BASE_URL | https://api.openai.com/v1 | Compatible endpoint; OpenRouter not required |
| LLM_API_KEY / LLM_MODEL | empty | Server secret/model; never sent to browser |
| LLM_API_MODE | responses | responses or chat_completions |
| LLM_MAX_OUTPUT_TOKENS | 4000 | Normal output, 256..16000 |
| LLM_REPORT_OUTPUT_TOKENS | 8000 | Recognized report requests, 256..16000 |
| LLM_MAX_RETRIES | 2 | Output retries, 0..3 |
| AGENTIC_RESEARCH | true | Autonomous default; false retains legacy |
| AGENT_MAX_TOOL_CALLS | 60 | 1..200; request limit adds five |
| AGENT_TIMEOUT_SECONDS | 600 | Total research time, 10..1800 |
| WEB_MAX_BYTES | 2097152 | Public response limit, 1024..10485760 |
| PROMPT_CONFIG_PATH | default prompts.toml | Optional custom template |
| MAX_RETRIEVAL_HITS | 12 | Legacy total limit, 3..30; not autonomous run cap |
| MAX_COMPANIES | 3 | Legacy setting, 1..8; not universal tool enforcement |
| WORKSPACE_ROOT | workspaces beside DB | Session root |
| WORKSPACE_MAX_FILE_BYTES | 10485760 | 10 MiB/file |
| WORKSPACE_MAX_TOTAL_BYTES | 104857600 | 100 MiB/session |
| WORKSPACE_MAX_FILES | 200 | File count |
| WORKSPACE_MAX_TEXT_BYTES | 262144 | 256 KiB text |
| APP_NAME / ENVIRONMENT | Financial Research Agent / development | Metadata, not security isolation |

The provider must support the selected protocol, streams, tools and structured output. A configured model string does not attest the provider's underlying model identity.
Keep secrets only in protected server configuration; never commit/log them or send them to the browser.
LLM_BASE_URL is administrator-trusted; HTTP is unencrypted. Use HTTPS for deployed providers.

## Troubleshooting

- UI unreachable: process/port, health, proxy, assets and restart after first build.
- Model 4xx: API mode, endpoint, permissions, schema/tool compatibility; no automatic provider switching.
- SEC 403/429/50x: identity, rate, origin restrictions, cache warnings; not proof of absent filings.
- Incomplete answers: generation/status_reason and tool detail distinguish retrieval, numbers, files and retries.
- Artifact 409: missing/changed bytes or failed source checks; do not modify registered files manually.
- Apparently running threads: reload after restart displays incomplete; no automatic task recovery.

## Backup/security/cleanup

Use SQLite online backup or a consistent stopped-service backup. Copying a live sqlite file alone can omit WAL state.
Back up workspace files too; restore both and verify artifact hashes. Do not commit runtime data, .env or logs.
File quotas/network checks are not a whole-application sandbox. No isolated execution, global hard disk/CPU limits, auth or complete audit administration.
Deleting threads retains disk files; cache/snapshot retention is manual. Check references before cleanup; do not remove files still referenced by database artifacts.
