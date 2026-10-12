from datetime import date
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

import pytest

from finagent.data.facts import FactResolver, build_comparison
from finagent.export.xlsx import comparison_workbook
from finagent.schemas import Company, FactRecord, ResearchScope, VerificationStatus
from finagent.storage import SQLiteStore
from finagent.verify.numbers import verify_table

COMPANY = Company(cik="1", ticker="TEST", name="Test Corp")


def fact(
    *,
    value: str,
    start: str,
    end: str,
    fp: str,
    accession: str,
    filed: str,
    form: str = "10-Q",
) -> FactRecord:
    return FactRecord(
        cik=COMPANY.cik,
        ticker=COMPANY.ticker,
        concept="RevenueFromContractWithCustomerExcludingAssessedTax",
        unit="USD",
        value=Decimal(value),
        start=date.fromisoformat(start),
        end=date.fromisoformat(end),
        fiscal_year=2024,
        fiscal_period=fp,
        form=form,
        accession_no=accession,
        filed=date.fromisoformat(filed),
    )


def setup_store(path: Path) -> SQLiteStore:
    store = SQLiteStore(path)
    store.upsert_company(COMPANY)
    store.upsert_facts(
        [
            fact(
                value="100",
                start="2024-01-01",
                end="2024-03-31",
                fp="Q1",
                accession="a1",
                filed="2024-05-01",
            ),
            fact(
                value="250",
                start="2024-01-01",
                end="2024-06-30",
                fp="Q2",
                accession="a2",
                filed="2024-08-01",
            ),
            fact(
                value="420",
                start="2024-01-01",
                end="2024-09-30",
                fp="Q3",
                accession="a3",
                filed="2024-11-01",
            ),
            fact(
                value="600",
                start="2024-01-01",
                end="2024-12-31",
                fp="FY",
                accession="a4",
                filed="2025-02-01",
                form="10-K",
            ),
        ]
    )
    return store


def test_ytd_and_q4_derivation_expose_all_inputs(tmp_path: Path) -> None:
    store = setup_store(tmp_path / "facts.sqlite3")
    resolver = FactResolver(store)
    q2 = resolver.resolve(COMPANY, "revenue", "2024-Q2")
    q4 = resolver.resolve(COMPANY, "revenue", "2024-Q4")
    assert q2 and q2.value == Decimal("150")
    assert q4 and q4.value == Decimal("180")
    assert len(q2.citations) == 2
    assert len(q4.citations) == 2
    assert q4.formula.input_citation_ids == [item.citation_id for item in q4.citations]


def test_verifier_blocks_tampered_workbook(tmp_path: Path) -> None:
    store = setup_store(tmp_path / "verify.sqlite3")
    scope = ResearchScope(companies=[COMPANY], fiscal_years=[2024])
    table = verify_table(build_comparison(store, scope, ["revenue"], ["2024-Q4"]), store)
    assert table.verified
    assert table.rows[0].cell.verification.status == VerificationStatus.VERIFIED
    with ZipFile(BytesIO(comparison_workbook(table, store))) as workbook:
        expected_sheets = {"xl/worksheets/sheet1.xml", "xl/worksheets/sheet2.xml"}
        assert expected_sheets.issubset(workbook.namelist())

    table.rows[0].cell.value = Decimal("999")
    tampered = verify_table(table, store)
    assert not tampered.verified
    with pytest.raises(ValueError, match="blocked"):
        comparison_workbook(tampered, store)


def test_verifier_reconciles_citation_against_fact_store(tmp_path: Path) -> None:
    store = setup_store(tmp_path / "citation-tamper.sqlite3")
    scope = ResearchScope(companies=[COMPANY], fiscal_years=[2024])
    table = build_comparison(store, scope, ["revenue"], ["2024-FY"])
    citation_id = table.rows[0].cell.source_citation_ids[0]
    citation = store.get_citation(citation_id)
    assert citation and citation.value
    citation.value.amount = Decimal("999")
    store.register_citation(citation)
    verified = verify_table(table, store)
    assert not verified.verified
    assert verified.rows[0].cell.verification.status == VerificationStatus.MISMATCH
