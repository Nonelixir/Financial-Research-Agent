# Agent, tools and prompts

[中文](../zh-CN/agent-tools.md) · [README](../../README.en.md)

Verified against current implementation: 2026-10-13.

## Model loop and context

`ResearchAgent._build_run` builds a Pydantic AI Agent with `Answer` output. Dependencies include store, scope, evidence, allowed citation IDs, tool context and artifacts.
Preselection is optional. Open scope may resolve more companies/change years; strict constrains companies, years and text-form expansion, but numeric form filtering has a separate gap.
Tool results feed later model turns. `update_plan` is a public checklist, not a predefined workflow.

## Tool catalog

| Tool | Main parameters | Behavior/limit |
| --- | --- | --- |
| resolve_companies | query | Ticker/name→CIK; not an industry-description sentence |
| search_web | query, limit=8 | Experimental Bing RSS leads; limit 1..10; snippets are not evidence |
| read_web | url, start=0, limit=8 | Public HTTPS text and citations; limit 1..20 |
| set_research_sample | members | ticker/reason/citation_ids; persistent non-exhaustive sample |
| list_filings | tickers, years, offset, limit, forms, filed_from/to | Metadata; limit 1..50; 10-K/10-Q/8-K |
| list_filing_documents | accession | Declared SEC attachment directory |
| read_filing_document | accession, filename, query, start, limit | Declared HTML/TXT attachment, matches and neighboring context; limit 1..20 |
| search_filings | query, tickers, years, accession, offset, limit | Paged FTS5 text; limit 1..20, default 8 |
| read_filing | accession, start, limit, section | Primary document pages; limit 1..20 |
| discover_financial_periods | tickers, count=2, end_years | Available annual revenue periods and actual dates; count 1..5 |
| get_financial_data | metrics, periods, tickers | 22 mapped metrics; 1..40 periods; verification, citations, JSON work file |
| list_financial_concepts | ticker, query, offset, limit | Concepts; limit 1..100; unknown tags are not automatically mapped |
| compute_financial | expression, inputs, output_unit | Arithmetic, bound evidence, derived citation and replay record |
| inspect_evidence | citation_ids | Reload 1..30 citations into this run before historical reuse |
| update_plan | steps, completed | Up to 20 steps of 300 characters; zero-based completed indices |
| execution_capabilities | none | Execution unavailable and its reason |
| run_python / run_shell | code/command, input_files, timeout_seconds | Exposed but always rejected |
| generate_workbook | frequency, tickers, years | Session annual/quarterly verified XLSX; discovered companies supported |
| list_files / read_file | filename for reads | Current session index/text |
| write_file | filename, content | New work text; unpublished, not financially verified |
| publish_artifact | filename, title | Copy/publish work text; not financially verified |
| publish_report | title, sections, caveats | Citation-checked Markdown report; not semantic proof |

The structured `Answer` processor is not a business tool. File tools require a persisted request with thread_id.

## Prompt configuration

`src/finagent/prompts.toml`, overridden by `PROMPT_CONFIG_PATH`, is read for every built request.
version=1; [prompts] contains system, user_template, source_template, coverage, history_template, missing_template and language_en/zh.
`prompts.py` validates exact template variables; use `$variable` and `$$` for literal dollars.

System instructions cover active research, registered evidence only, untrusted web content, issuer non-GAAP reconciliation, explicit period ambiguity and real file delivery.
Substantive company, industry and financial-performance analyses automatically deliver a source-checked Markdown report and accompanying financial XLSX without an explicit file request. Focused factual questions do not trigger automatic files. The prompt requires both deliveries before completion and real download links; unavailable tools, failures or insufficient data require incomplete status while retaining successful files. Workbooks contain supported verified metrics, not necessarily narrative-only figures or derived calculations. This is a prompt requirement; existing output checks primarily enforce explicitly requested reports/Excel files.
For focused questions, the prompt requests concise cited paragraphs and metric names in formula explanations. Computation records retain input lineage; margin changes subtract derived percent citations and use percentage_points.
Language mode overrides matching the question language. Prompt edits cannot create tools, enable execution or bypass validation.
Python function signatures define tool schemas; interface changes must update schema, validation, tests and both language documents.

## Budgets and failures

Defaults: 60 tool calls, Pydantic AI request_limit=tool limit+5, 600 seconds, 4000 normal/8000 report output tokens, 2 output retries.
Identical failing calls are blocked after two failures. Errors expose code/type/message/retryable/instruction.
403/404/429, timeout and 50x differ, but there is no comprehensive automatic retry policy. Wrong metric choice and copied citation IDs remain possible.

Exact greetings return a conversational reply directly. The prompt directs capability questions, clarification and unrelated requests to claims=[], message and complete without research plans. Message cannot coexist with claims; explicit currency amounts/percentages are rejected. This field does not have comprehensive semantic intent validation.

Multi-company financial comparisons use separate company paragraphs with amounts/percentages bound to matching issuer, metric and actual period. Retries retain derived citations and bindings while repairing errors. Ordinary industry analysis also requires publish_report and generate_workbook.

Answer body is published after complete validation; tool/status progress remains streamed. Ordinary industry answers are concise to fit the normal output budget. The earlier ten-question score predates this publication change.
