from datetime import date

from finagent.retrieval.ingest import chunk_filing
from finagent.schemas import Filing


def test_html_chunk_has_stable_text_locator() -> None:
    filing = Filing(
        cik="0000000001",
        accession_no="0000000001-25-000001",
        form="10-K",
        filing_date=date(2025, 2, 1),
        primary_document="test.htm",
        sec_url="https://www.sec.gov/Archives/test.htm",
    )
    html = """
    <html><body><h2>Item 1A. Risk Factors</h2>
    <p>Our supply chain depends on a limited number of suppliers and disruption could
    materially affect revenue, delivery schedules, customer relationships, and gross margin.</p>
    </body></html>
    """
    first = chunk_filing(filing, "TEST", html)
    second = chunk_filing(filing, "TEST", html)
    assert len(first) == 1
    assert first[0].chunk_id == second[0].chunk_id
    assert first[0].section == "Item 1A. Risk Factors"
