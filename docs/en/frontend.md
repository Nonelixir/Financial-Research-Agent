# Frontend and language interaction

[中文](../zh-CN/frontend.md) · [README](../../README.en.md)

Verified against current implementation: 2026-10-15.

## Technology and responsibilities

React 19, TypeScript and Vite. assistant-ui supplies chat primitives/external-store runtime; AI Elements supplies Tool/Artifact source components.
The application does not use a full AI SDK server message protocol: `api.ts` parses custom SSE and `main.tsx` owns session state.
Radix, react-markdown/remark-gfm, highlight.js and Lucide handle primitives/rendering. See [third-party notice](../../frontend/THIRD_PARTY.en.md).

Features include thread list/title filtering, create/rename/delete, message editing, regeneration, copy, stop, scrolling, theme and optional company/year/form/strict controls.
Title search is local substring filtering, not full-message search. UI form checkboxes offer 10-K/10-Q; open tools may discover 8-K.
Selected companies and persisted samples are non-exhaustive, not the entire industry; sample evidence is accessible.

## Streaming behavior

Tool states group by tool_call_id or phase and show active/complete/warning. Sources/plans/samples/artifacts update the workbench.
Answer bodies are not raw token streams: the backend parses structured Answer and publishes its body after whole-answer validation.
Progress can continue with an empty answer body. Reasoning and incomplete JSON are not public text.
Tool progress remains live, while answer text is buffered until full validation passes. Retries can rewrite unpublished drafts; only the latest candidate is retained for incomplete recovery.

## Citations and artifacts

Claim-end numbered buttons load original quotes/values, locators, dates, URLs and optional hashes in a side panel.
Model-authored reference text may create redundant labels. The UI is not fine-grained span-level citation binding.
Derived operations can display, but input lineage lacks full interactive browsing; the first-input SourceRef is not the whole provenance chain.
Artifacts preview Markdown/JSON/tables and revenue bars, with download/expand. Charts are table views, not arbitrary executable applications.
No safe interactive HTML artifacts, code execution, upload or general image-generation entry point is implemented.

## Languages

`i18n.tsx`, `localization.py` and `prompts.toml` handle UI, server states and model-language requirements.
English/Chinese selection persists in localStorage; later requests carry Scope.language. Plans, answers, report titles and quarterly sheets follow it.
Historical content, original quotes, tickers and citation IDs are not translated. Unknown state labels may fall back to raw strings.
Annual workbooks retain fixed Data/Provenance templates; complete translation of arbitrary binary artifacts is not guaranteed.
The diagram is standalone HTML with separate language entries, independent of chat localStorage.

## Build and maintenance

Run `npm --prefix frontend ci` and `npm --prefix frontend run build`; output is `src/finagent/static/workspace/`.
FastAPI serves /assets on the same origin; no production Node service. Restart after the first asset build to register its mount.
SSE changes require coordinated types/parser/state changes; UI copy needs both languages. Never bypass backend validation to expose scratch text.

Conversational message text renders separately and is also saved in persistent message content, remaining visible after reload without fabricated citations.

Answer body is published after complete validation; tool/status progress remains streamed. Ordinary industry answers are concise to fit the normal output budget. The earlier ten-question score predates this publication change.

## Yellow notices and terminal state

`AnswerBody` renders `answer.caveats` in order as `.notice` paragraphs. The model supplies normal research caveats; fallback/error code may supply fixed messages. Yellow color does not establish completion, failure or validation. Body content comes from claims or conversational message; recovery snapshots can be incomplete. See the [complete processing flow](processing-flow.md) for SSE, cancellation and persistence.
