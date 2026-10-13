# Provenance and validation

[中文](../zh-CN/provenance-validation.md) · [README](../../README.en.md)

Verified against current implementation: 2026-10-13.

## Data model and assurance levels

Code: `schemas.py`, `storage.py`, `verify/citations.py`, `verify/numbers.py`.

Citation contains citation_id, SourceRef, Locator, optional ValueRef and retrieved_at.
SourceRef retains type (xbrl/filing_text/derived/web), issuer, form/accession, filing date, URL, filename and optional hash/title.
Locator is XBRL concept/unit/start/end/fy/fp/frame/dimensions, text section/index/DOM path/quote/hash, or derived operation/input IDs.

| Level | Actual check | Does not prove |
| --- | --- | --- |
| Registered source | Run-allowed ID exists in SQLite | Support for every assertion |
| Literal numeric support | Quote contains normalized digits | Correct column, unit, period, metric or cause |
| Numeric binding | Exact span→one ValueRef; scale/rounding/sign | Mandatory binding of every number |
| Table verification | Original XBRL lookup and formula replay | Complete cells or reliable fiscal-year semantics |
| Derived replay | Input/record presence, recursive lookup, equal result | Correct financial method or independent second implementation |
| File integrity | Real file, same hash; table recheck | Financial review of arbitrary documents |

## Answer publication checks

1. Pydantic parses Answer; every Claim has citations, numeric_bindings is optional.
2. All citations must be allowed in this run and exist. Near IDs are suggested, never automatically substituted.
3. Derived citations recursively replay and compare recorded inputs/results.
4. A binding text must occur exactly in the Claim, and its citation must belong to that Claim.
5. Numeric bindings compare scaled/rounded amounts. Signed keeps the sign; positive outflow/loss magnitudes require negative evidence and explicit local wording.
6. Narrative bindings check literal digits. Outflow/loss also requires a negative literal (minus sign or accounting parentheses) in the same quote and local outflow/loss wording in the answer. No ValueRef is created; table row/column identity is not proved.
7. Paragraph currency checks still compare values; verified single-source bindings are not re-signed by fuzzy context. Mixed text/derived claims can retain literal number+scale support.
8. Percentages/days require reported digits or matching-unit derived evidence. Percentage points are not percent.
9. Without numeric evidence, substantive digits need quote support; dates, registered identifiers, forms and list labels receive bounded exclusions.

MONEY handles USD/$/Chinese currency and scales plus m/b/k/bn abbreviations. Accounting parentheses must enclose a complete single amount; formula grouping does not change an amount’s sign.
Changed spans, wrong presentations and mismatched citations can exhaust two retries. Closed-claim verification is not comprehensive semantic proof.

## Tables and files

`verify_cell` looks up original XBRL for source IDs, compares values and replays supported formulas.
table.verified requires at least one verified cell and all others verified/missing; mismatches block XLSX.
`publish_report` applies answer citation rules to sections; generic `publish_artifact` does not financially verify text.
Ordinary replies are not artifacts. Downloads compare file hashes and recheck table data; report downloads do not prove semantics again.

## Snapshots and residual risk

source_snapshots retains URL+body hash, but citations lack a complete immutable-version foreign key. Non-web stable IDs omit title/content hash; registration may update records.
Derived SourceRef inherits the first input; full lineage requires input IDs and computations. The UI is not a complete interactive lineage browser.
There is no unified target-period gate, structured table-cell extraction, sentence entailment or coverage proof. Real citations can refer to the wrong period.
Analysts must verify issuer, actual dates, units, metric definitions, non-GAAP reconciliation and causal passages.

Answer.message is for greetings, capabilities, clarification and scope explanations without citations. It cannot coexist with claims; explicit financial amounts and percentages are rejected. It is not a substitute for research claims and lacks comprehensive semantic validation.
