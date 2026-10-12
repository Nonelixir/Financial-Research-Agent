import asyncio
from datetime import date
from pathlib import Path

from finagent.agent import ResearchAgent
from finagent.config import Settings
from finagent.schemas import (
    Citation,
    Company,
    ResearchScope,
    SearchHit,
    SourceRef,
    TextLocator,
)
from finagent.storage import SQLiteStore


def test_agent_has_auditable_offline_fallback(tmp_path: Path) -> None:
    store = SQLiteStore(tmp_path / "offline.sqlite3")
    company = Company(cik="1", ticker="TEST", name="Test")
    source = SourceRef(
        source_type="filing_text",
        cik=company.cik,
        ticker=company.ticker,
        form="10-K",
        accession_no="a1",
        filing_date=date(2025, 1, 1),
        sec_url="https://www.sec.gov/Archives/test.htm",
    )
    locator = TextLocator(
        section="Business",
        paragraph_index=0,
        exact_quote=(
            "Revenue increased because customer demand improved materially during the year."
        ),
        quote_sha256="hash",
    )
    citation = Citation(
        citation_id=Citation.stable_id(source, locator), source=source, locator=locator
    )
    store.register_citation(citation)
    hit = SearchHit(citation=citation, text=locator.exact_quote, score=1)
    answer = asyncio.run(
        ResearchAgent(Settings(llm_api_key="", llm_model=""), store).answer(
            "收入为什么增长？", ResearchScope(companies=[company]), [hit]
        )
    )
    assert answer.claims[0].citation_ids == [citation.citation_id]
    assert "未配置生成模型" in answer.claims[0].text
