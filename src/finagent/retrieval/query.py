from __future__ import annotations

import re
from datetime import date
from hashlib import sha256

from finagent.schemas import (
    Citation,
    ResearchScope,
    SearchHit,
    SourceRef,
    TextLocator,
)
from finagent.storage import SQLiteStore

TERM_EXPANSIONS = {
    "收入": ["revenue", "sales", "net sales"],
    "营收": ["revenue", "sales", "net sales"],
    "利润": ["profit", "income", "earnings"],
    "净利润": ["net income", "net loss"],
    "毛利率": ["gross margin", "gross profit"],
    "现金流": ["cash flow", "operating activities"],
    "风险": ["risk", "uncertainty", "adverse"],
    "供应链": ["supply chain", "supplier"],
    "客户": ["customer", "concentration"],
    "战略": ["strategy", "business"],
    "财报": ["revenue", "liquidity", "cash flow", "risk", "customer", "management"],
    "财务": ["revenue", "liquidity", "cash flow", "gross margin", "operating expenses"],
}
OVERVIEW_TERMS = ["revenue", "liquidity", "cash flow", "risk", "customer", "business"]


def expand_query(query: str) -> list[str]:
    terms = re.findall(r"[A-Za-z][A-Za-z0-9_-]{1,}|[\u4e00-\u9fff]{2,}", query)
    expanded: list[str] = [term for term in terms if re.match(r"[A-Za-z]", term)]
    for chinese, english_terms in TERM_EXPANSIONS.items():
        if chinese in query:
            expanded.extend(english_terms)
    return list(dict.fromkeys(term.lower() for term in expanded))


class FilingRetriever:
    def __init__(self, store: SQLiteStore) -> None:
        self.store = store

    def search(self, query: str, scope: ResearchScope, limit: int = 12) -> list[SearchHit]:
        if not scope.companies:
            return []
        terms = expand_query(query)
        if not terms:
            terms = OVERVIEW_TERMS
        fts_query = " OR ".join(f'"{term.replace(chr(34), "")}"' for term in terms)
        per_company = max(1, limit // len(scope.companies))
        hits: list[SearchHit] = []
        for company in scope.companies:
            candidates = self._search_company(fts_query, company.cik, scope, per_company * 4)
            # Round-robin across filings prevents one annual report from taking
            # the entire context when several years/quarters are in scope.
            groups: dict[str, list[SearchHit]] = {}
            for hit in candidates:
                groups.setdefault(hit.citation.source.accession_no, []).append(hit)
            selected: list[SearchHit] = []
            while groups and len(selected) < per_company:
                for key in list(groups):
                    selected.append(groups[key].pop(0))
                    if not groups[key]:
                        del groups[key]
                    if len(selected) >= per_company:
                        break
            hits.extend(selected)
        hits.sort(key=lambda hit: hit.score, reverse=True)
        return hits[:limit]

    def _search_company(
        self,
        fts_query: str,
        cik: str,
        scope: ResearchScope,
        limit: int,
        accession: str = "",
    ) -> list[SearchHit]:
        clauses = ["c.cik = ?", "chunks_fts MATCH ?"]
        parameters: list[object] = [cik, fts_query]
        if accession:
            clauses.append("c.accession_no = ?")
            parameters.append(accession)
        if scope.forms:
            clauses.append(f"REPLACE(c.form, '/A', '') IN ({','.join('?' for _ in scope.forms)})")
            parameters.extend(scope.forms)
        if scope.fiscal_years:
            placeholders = ",".join("?" for _ in scope.fiscal_years)
            clauses.append(
                "CAST(SUBSTR(COALESCE(f.report_date, f.filing_date), 1, 4) AS INTEGER) "
                f"IN ({placeholders})"
            )
            parameters.extend(scope.fiscal_years)
        parameters.append(limit)
        sql = f"""
            SELECT c.*, f.primary_document, bm25(chunks_fts, 1.0, 2.0, 0.5) AS rank
            FROM chunks_fts
            JOIN chunks c ON c.rowid = chunks_fts.rowid
            JOIN filings f ON f.accession_no = c.accession_no
            WHERE {" AND ".join(clauses)}
            ORDER BY rank
            LIMIT ?
        """
        with self.store.connect() as connection:
            rows = connection.execute(sql, parameters).fetchall()
        results: list[SearchHit] = []
        for row in rows:
            source = SourceRef(
                source_type="filing_text",
                cik=row["cik"],
                ticker=row["ticker"],
                form=row["form"],
                accession_no=row["accession_no"],
                filing_date=date.fromisoformat(row["filing_date"]),
                primary_document=row["primary_document"],
                sec_url=row["sec_url"],
            )
            locator = TextLocator(
                section=row["section"],
                paragraph_index=row["paragraph_index"],
                dom_path=row["dom_path"],
                exact_quote=row["text"],
                quote_sha256=sha256(row["text"].encode()).hexdigest(),
            )
            citation = Citation(
                citation_id=Citation.stable_id(source, locator),
                source=source,
                locator=locator,
            )
            self.store.register_citation(citation)
            results.append(
                SearchHit(citation=citation, text=row["text"], score=-float(row["rank"]))
            )
        return results
