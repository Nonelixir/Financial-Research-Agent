# Sessions, storage and artifacts

[中文](../zh-CN/sessions-artifacts.md) · [README](../../README.en.md)

Verified against current implementation: 2026-10-13.

## Persistence and context

Core SQLite tables: companies, filings, facts, chunks/chunks_fts, citations, profiles, ingestion_runs, source_cache/source_snapshots.
Session schema: threads/messages/artifacts; research creates web_pages/research_samples on demand; computation creates computations.
SQLite WAL, transactions and in-process locks are not distributed storage. active_threads is process-local; multiple workers are not safe session coordination.

Messages retain role/content/answer_json/events_json/status; a thread stores scope.
Next turns use the last 20 complete messages, at most 8000 characters each. Historical citations come from up to ten assistant event logs, capped at 300 IDs; inspect_evidence is required before reuse.
At most three exact-scope table contexts enter requests. The default agent receives availability, the last ten artifact summaries and saved sample, not a full automatic table dump; tools must inspect files/data.
Context is bounded. Profile APIs do not currently provide automatic long-term memory injection.

## Edits, cancellation and restart

Concurrent sends in one thread return 409. replace_from must target its user message; messages from that point are replaced, files/artifacts survive.
SSE completion/cancellation persists the last checked answer, events and status. Disconnects do not automatically resume; unfinished tasks do not survive process restarts.
A stored running message without an active in-process task is displayed incomplete.
Active threads cannot be deleted. Deletion removes session database records but retains disk files as a recoverable archive; deleted-session APIs no longer access them.

## File boundaries

Default: `workspaces/<thread_id>/` beside DATABASE_PATH; WORKSPACE_ROOT overrides it.
Thread ID is 32 lowercase hex characters; flat names ≤200 bytes, no absolute paths, directories, hidden names, separators, NUL or control characters.
Text tools support .md/.txt/.csv/.json. The file layer also accepts .xlsx/.png/.jpg/.webp; this does not mean the agent can generate every format.
dir_fd/O_NOFOLLOW prevents symlink traversal; O_EXCL disallows overwrites, files 0600/directories 0700. Reads require regular, single-link files.

Defaults: 10 MiB/file, 100 MiB/session, 200 files, 256 KiB/text. Quotas are application checks, not OS hard quotas.
No model directory/overwrite/arbitrary-delete tools. Agent work and published files remain in its session directory; shared SEC caches live in SQLite.
Restricted file tools are not a Python/shell sandbox. Execution remains unavailable and never falls back to the host.

## Artifact definition/publication

An artifact is a real registered deliverable file with a download path; normal replies are not artifacts.
write_file creates unpublished work files; get_financial_data can create a JSON work file without publishing it.
publish_artifact creates a published- copy marked model_generated_not_financially_verified.
publish_report creates cited Markdown with source locators and report=true; generate_workbook builds XLSX from deterministic verified data.
Quarterly sheets separate income/cash flow/balance sheet/data/calculations/Provenance/notes; annual sheets are Data/Provenance.
Period inclusion requires revenue for at least one company; every company/metric is not guaranteed complete.

## Download/maintenance

Downloads resolve artifact metadata, read bytes, check SHA256 and revalidate table source data; missing/changed files return 409.
Generic text publication has no financial verification. Work files are not automatically downloadable artifacts; only artifacts with file metadata appear.
Back up both a consistent SQLite snapshot and all workspace files. Thread deletion does not reclaim disk; archive cleanup is an explicit operational action.

Conversational Answer.message is included in messages.content; it creates neither research evidence nor artifacts.
