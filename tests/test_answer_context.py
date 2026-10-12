from datetime import date
from decimal import Decimal

from finagent import api
from finagent.data.facts import FactResolver
from finagent.schemas import AskRequest, Company, FactRecord, ResearchScope
from finagent.storage import SQLiteStore


def record(company, concept, value, start, end, fp, year=2026):
    return FactRecord(
        cik=company.cik,
        ticker=company.ticker,
        concept=concept,
        unit="USD",
        value=Decimal(value),
        start=date.fromisoformat(start) if start else None,
        end=date.fromisoformat(end),
        fiscal_year=year,
        fiscal_period=fp,
        form="10-K" if fp == "FY" else "10-Q",
        accession_no=f"a-{year}-{fp}",
        filed=date(2026, 8, 6),
    )


def test_answer_receives_quarters_cashflow_balance_sheet_and_missing_year(tmp_path, monkeypatch):
    store = SQLiteStore(tmp_path / "context.sqlite3")
    company = Company(cik="1", ticker="TEST", name="Test")
    store.upsert_company(company)
    store.upsert_facts(
        [
            record(company, "Revenues", "100", "2026-01-01", "2026-03-31", "Q1"),
            record(company, "Revenues", "230", "2026-01-01", "2026-06-30", "Q2"),
            record(
                company,
                "NetCashProvidedByUsedInOperatingActivities",
                "-20",
                "2026-01-01",
                "2026-03-31",
                "Q1",
            ),
            record(company, "Assets", "900", None, "2026-03-31", "Q1"),
            record(company, "GrossProfit", "40", "2026-01-01", "2026-03-31", "Q1"),
        ]
    )
    monkeypatch.setattr(api, "store", lambda: store)
    hits, context, table = api._prepare_answer_context(
        AskRequest(
            question="分析财报",
            scope=ResearchScope(companies=[company], fiscal_years=[2026]),
        )
    )
    assert "operating_cash_flow 2026-Q1: -20" in context
    assert "assets 2026-Q1: 900" in context
    assert "gross_profit 2026-Q1: 40" in context
    assert "revenue 2026-Q2: 130" in context
    assert "MISSING / UNVERIFIED" in context
    assert "TEST revenue 2026-FY" in context
    assert hits and table.verified


def test_comparative_values_cannot_replace_current_period(tmp_path):
    store = SQLiteStore(tmp_path / "comparative.sqlite3")
    company = Company(cik="1", ticker="TEST", name="Test")
    store.upsert_company(company)
    store.upsert_facts(
        [
            record(company, "Revenues", "130", "2026-04-01", "2026-06-30", "Q2"),
            record(company, "Revenues", "999", "2025-04-01", "2025-06-30", "Q2"),
            record(company, "Assets", "900", None, "2026-06-30", "Q2"),
            record(company, "Assets", "9999", None, "2025-12-31", "Q2"),
        ]
    )
    resolver = FactResolver(store)
    assert resolver.resolve(company, "revenue", "2026-Q2").value == Decimal("130")
    assert resolver.resolve(company, "assets", "2026-Q2").value == Decimal("900")
