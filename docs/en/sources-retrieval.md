# SEC, web and retrieval

[中文](../zh-CN/sources-retrieval.md) · [README](../../README.en.md)

Verified against current implementation: 2026-10-12.

## SEC integration

Code: `data/sec.py`. SEC ticker directory identifies companies; local companies may carry aliases. CIK is zero-padded to ten digits, ticker uppercased.
Resolution proves issuer identity, not industry membership. Samples require registered web/filing evidence.

- Submissions recent plus historical files shards overlapping requested years; deduplicate/sort by filing date. No years means no exhaustive historical scan.
- Text directory supports 10-K/10-Q/8-K; 8-K uses filing-date year, others report date with filing-date fallback.
- list_filings accepts filed_from/to and returns accessions, not all downloaded bodies.
- Primary bodies are cached. Attachments must be declared in accession-index.html; no guessed filenames. HTML/TXT only, no PDF/OCR.
- Company Facts retains values, units, taxonomy/concept, start/end, fy/fp, accession/form/filed/frame; non-finite values are rejected.
- Numeric facts accept 10-K/10-Q including amendments, not all forms or all SEC tags as comparable metrics.

## Cache and network

Ticker/attachment index/bodies normally cache for 86400 seconds, submissions for 3600 and Company Facts for 21600.
source_cache and URL+SHA256 source_snapshots retain content. Failures may use cached facts with warnings, never synthetic zeros.
SEC uses an identifying User-Agent, an HTTPS host allowlist, no arbitrary redirects, default 5 requests/second per client and 30-second request timeout.
Concurrent Agent clients do not share a process-wide SEC limiter. A local cache does not prove the origin is currently reachable.

## FTS5 and pagination

`retrieval/ingest.py` creates HTML paragraph blocks with section/index/DOM path/quote/hash.
Tables are mostly flattened text; complete row/column/unit structure is not guaranteed.
`retrieval/query.py` uses SQLite FTS5 unicode61, OR terms and BM25, not vector or semantic search.
A small dictionary expands common Chinese finance terms into English. English queries use terms directly; unknown Chinese concepts can have weak recall.

Autonomous tools page repeatedly; there is no fixed 12-passage run cap.
Broad search indexes at most the newest 12 filing bodies per company per call. Discover more accessions and explicitly read/search them for deeper history.
Passage limits are 1..20. The legacy retriever still has a default total limit of 12 with company quotas and filing round-robin selection.

## Public web

`web.py` uses experimental Bing RSS leads. read_web registers original URL, body hash, fetch time and paragraph quotes.
Public fetch validates HTTPS, DNS/IP and redirects, pins addresses, denies private/loopback destinations and bounds size/time.
Search quality, 403s, dynamic JS, paywalls and PDFs limit research. Documents are untrusted data, never executable instructions.
Public fetch has a 45-second total limit and at most four request/redirect iterations; only public HTTPS port 443 without URL credentials is accepted. Compressed responses are currently rejected.
Industry context may extend beyond SEC; comparable structured financials remain focused on supported issuers. FTS hits do not prove causality.
