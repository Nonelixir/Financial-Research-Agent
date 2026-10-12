from datetime import date
from pathlib import Path

from finagent.retrieval.query import FilingRetriever, expand_query
from finagent.schemas import Company, Filing, FilingChunk, ResearchScope
from finagent.storage import SQLiteStore


def seeded_store(path: Path) -> tuple[SQLiteStore, Company]:
    store = SQLiteStore(path)
    company = Company(cik="1", ticker="TEST", name="Test Corp")
    store.upsert_company(company)
    filing = Filing(
        cik=company.cik,
        accession_no="0000000001-25-000001",
        form="10-K",
        filing_date=date(2025, 2, 1),
        report_date=date(2024, 12, 31),
        primary_document="test.htm",
        sec_url="https://www.sec.gov/Archives/test.htm",
    )
    store.upsert_filing(filing, raw_html="<p>raw</p>")
    store.upsert_chunks(
        [
            FilingChunk(
                chunk_id="chunk-1",
                cik=company.cik,
                ticker=company.ticker,
                accession_no=filing.accession_no,
                form=filing.form,
                filing_date=filing.filing_date,
                section="Risk Factors",
                paragraph_index=0,
                text="Supply chain constraints may adversely affect revenue and gross margin.",
                dom_path="div/p",
                sec_url=filing.sec_url,
            )
        ]
    )
    return store, company


def test_sqlite_fts_is_persistent_and_registers_citation(tmp_path: Path) -> None:
    database = tmp_path / "agent.sqlite3"
    _store, company = seeded_store(database)
    reopened = SQLiteStore(database)
    scope = ResearchScope(companies=[company], fiscal_years=[2024])
    hits = FilingRetriever(reopened).search("供应链和收入风险", scope)
    assert len(hits) == 1
    assert hits[0].citation.source.accession_no == "0000000001-25-000001"
    assert reopened.get_citation(hits[0].citation.citation_id) is not None


def test_chinese_query_expands_to_english_terms() -> None:
    assert "supply chain" in expand_query("分析供应链风险")
    assert "risk" in expand_query("分析供应链风险")
    assert "liquidity" in expand_query("分析近三年财报")


def test_general_analysis_and_followup_retrieve_text(tmp_path: Path) -> None:
    store, company = seeded_store(tmp_path / "overview.sqlite3")
    scope = ResearchScope(companies=[company], fiscal_years=[2024])
    assert FilingRetriever(store).search("分析近三年财报", scope)
    assert FilingRetriever(store).search("继续", scope)
