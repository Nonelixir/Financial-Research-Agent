import asyncio
from decimal import Decimal
from types import SimpleNamespace

import httpx
import pytest
from test_facts_verifier_export import COMPANY, setup_store
from test_streaming import evidence

from finagent.agent import ResearchAgent
from finagent.compute.evidence import compute_evidence, evaluate, replay_computation
from finagent.config import Settings
from finagent.data.facts import FactResolver
from finagent.data.sec import SecClient
from finagent.schemas import Answer, Claim, NumericBinding, ResearchScope
from finagent.verify.citations import (
    MONEY,
    CitationVerificationError,
    money_value,
    verify_answer_citations,
)


@pytest.mark.parametrize("text", ["-$600", "$-600", "(USD 600)", "−$600", "-600美元"])
def test_negative_currency_forms(text):
    assert money_value(MONEY.search(text))[0] == -600


def test_formula_parentheses_and_currency_abbreviations():
    text = "365 * (($1,587m + $1,174m) / 2)"
    assert [money_value(m)[0] for m in MONEY.finditer(text)] == [
        Decimal("1587000000"), Decimal("1174000000")
    ]
    assert money_value(MONEY.search("($1.5m)"))[0] == Decimal("-1500000")


def test_original_cashflow_outflow_binding(tmp_path):
    store, _, hit = evidence(tmp_path)
    c = hit.citation
    c.locator.exact_quote = (
        "In millions. Operating activities 3,565; Financing activities (3,264)."
    )
    store.register_citation(c)
    claim = Claim(
        text="Financing activities used $3,264 million.",
        citation_ids=[c.citation_id],
        numeric_bindings=[
            NumericBinding(text="$3,264 million", citation_id=c.citation_id,
                           presentation="outflow")
        ],
    )
    verify_answer_citations(Answer(claims=[claim]), {c.citation_id}, store)
    claim.text = "Operating activities used $3,565 million."
    claim.numeric_bindings[0].text = "$3,565 million"
    with pytest.raises(CitationVerificationError, match="negative literal"):
        verify_answer_citations(Answer(claims=[claim]), {c.citation_id}, store)
    claim.text = "Financing activities provided $3,264 million."
    claim.numeric_bindings[0].text = "$3,264 million"
    with pytest.raises(CitationVerificationError, match="outflow/loss"):
        verify_answer_citations(Answer(claims=[claim]), {c.citation_id}, store)


def test_outflow_not_inflow_and_explicit_binding(tmp_path):
    store = setup_store(tmp_path / "signed.sqlite3")
    c = FactResolver(store).resolve(COMPANY, "revenue", "2024-FY").citations[0]
    c.value.amount = Decimal("-600")
    c.citation_id = "negative-fixture"
    store.register_citation(c)
    for text in [
        "Financing activities used $600.",
        "融资现金流流出600美元。",
        "Financing cash flow was -$600.",
    ]:
        verify_answer_citations(
            Answer(claims=[Claim(text=text, citation_ids=[c.citation_id])]), {c.citation_id}, store
        )
    with pytest.raises(CitationVerificationError):
        verify_answer_citations(
            Answer(
                claims=[
                    Claim(text="Financing activities provided $600.", citation_ids=[c.citation_id])
                ]
            ),
            {c.citation_id},
            store,
        )
    bound = Claim(
        text="Financing activities used $600.",
        citation_ids=[c.citation_id],
        numeric_bindings=[
            NumericBinding(text="$600", citation_id=c.citation_id, presentation="outflow")
        ],
    )
    verify_answer_citations(Answer(claims=[bound]), {c.citation_id}, store)
    bound.text = "Financing activities provided $600."
    with pytest.raises(CitationVerificationError, match="magnitude"):
        verify_answer_citations(Answer(claims=[bound]), {c.citation_id}, store)


def test_known_identifiers_and_dates_not_amounts(tmp_path):
    store, _, hit = evidence(tmp_path)
    c = hit.citation
    c.locator.exact_quote = "3M 1.500% Notes due 2026 MMM26 registered on NYSE."
    store.register_citation(c)
    text = "3M on June 30, 2023: 1.500% Notes due 2026 (MMM26), registered on NYSE."
    verify_answer_citations(
        Answer(claims=[Claim(text=text, citation_ids=[c.citation_id])]), {c.citation_id}, store
    )
    with pytest.raises(CitationVerificationError):
        verify_answer_citations(
            Answer(claims=[Claim(text="3M revenue $100 billion.", citation_ids=[c.citation_id])]),
            {c.citation_id},
            store,
        )


def test_computation_replay_units_and_numeric_leak(tmp_path):
    store = setup_store(tmp_path / "calc.sqlite3")
    resolver = FactResolver(store)
    current = resolver.resolve(COMPANY, "revenue", "2024-FY").citations[0]
    prior = resolver.resolve(COMPANY, "revenue", "2024-Q1").citations[0]
    deps = SimpleNamespace(
        store=store, allowed_citation_ids={current.citation_id, prior.citation_id}
    )
    derived, record = compute_evidence(
        deps,
        "(current/prior-1)*100",
        {"current": current.citation_id, "prior": prior.citation_id},
        "percent",
    )
    assert derived.value.amount == 500
    assert record["inputs"]["current"] == current.citation_id
    assert replay_computation(store, derived.citation_id) == 500
    allowed = deps.allowed_citation_ids | {derived.citation_id}
    answer = Answer(
        claims=[Claim(text="The computed increase was 500%.", citation_ids=[derived.citation_id])]
    )
    verify_answer_citations(answer, allowed, store)
    answer.claims[0].text = "The computed increase was 999%."
    with pytest.raises(CitationVerificationError, match="compute_financial"):
        verify_answer_citations(answer, allowed, store)
    answer.claims[0].citation_ids = [current.citation_id]
    with pytest.raises(CitationVerificationError, match="compute_financial"):
        verify_answer_citations(answer, allowed, store)
    with pytest.raises(ValueError):
        evaluate('__import__("os").system("pwd")', {})
    with pytest.raises(ValueError, match="compatible units"):
        evaluate("a+b", {"a": (Decimal(1), "USD"), "b": (Decimal(1), "days")})
    with pytest.raises(ValueError, match="zero"):
        evaluate("a/0", {"a": (Decimal(1), "USD")})
    with pytest.raises(ValueError, match="Every supplied"):
        compute_evidence(deps, "1", {"unused": current.citation_id}, "ratio")
    derived.value.amount = Decimal("999")
    store.register_citation(derived)
    with pytest.raises(ValueError, match="mismatch"):
        replay_computation(store, derived.citation_id)


def test_registered_issuer_and_exhibit_labels_without_quote_name(tmp_path):
    store, _, hit = evidence(tmp_path)
    from finagent.schemas import Company

    store.upsert_company(Company(cik="1", ticker="MMM", name="3M CO"))
    c = hit.citation
    c.source.ticker = "MMM"
    c.locator.exact_quote = "Securities registered: 1.500% Notes due 2026 MMM26 on NYSE."
    store.register_citation(c)
    text = "3M's Form 8-K on June 30, 2023, Exhibit 99.1: 1.500% Notes due 2026 (MMM26)."
    verify_answer_citations(
        Answer(claims=[Claim(text=text, citation_ids=[c.citation_id])]), {c.citation_id}, store
    )


def test_narrative_numeric_binding_is_literal_not_calculable(tmp_path):
    store, _, hit = evidence(tmp_path)
    c = hit.citation
    c.locator.exact_quote = "Adjusted non-GAAP EBITDA 2,018 ($ million), year ended June 30."
    store.register_citation(c)
    claim = Claim(
        text="Adjusted EBITDA was $2,018 million.",
        citation_ids=[c.citation_id],
        numeric_bindings=[NumericBinding(text="$2,018 million", citation_id=c.citation_id)],
    )
    verify_answer_citations(Answer(claims=[claim]), {c.citation_id}, store)
    claim.numeric_bindings[0].text = "$9,999 million"
    claim.text = "Adjusted EBITDA was $9,999 million."
    with pytest.raises(CitationVerificationError, match="literal support"):
        verify_answer_citations(Answer(claims=[claim]), {c.citation_id}, store)
    deps = SimpleNamespace(store=store, allowed_citation_ids={c.citation_id})
    with pytest.raises(ValueError, match="numeric value"):
        compute_evidence(deps, "a*2", {"a": c.citation_id}, "USD")


def test_derived_percentage_points_and_direction_sentence_boundary(tmp_path):
    store = setup_store(tmp_path / "points.sqlite3")
    c = FactResolver(store).resolve(COMPANY, "revenue", "2024-FY").citations[0]
    deps = SimpleNamespace(store=store, allowed_citation_ids={c.citation_id})
    a, _ = compute_evidence(deps, "a/a*19.4", {"a": c.citation_id}, "percent")
    b, _ = compute_evidence(deps, "a/a*18.5", {"a": c.citation_id}, "percent")
    deps.allowed_citation_ids.update({a.citation_id, b.citation_id})
    d, _ = compute_evidence(
        deps, "a-b", {"a": a.citation_id, "b": b.citation_id}, "percentage_points"
    )
    assert replay_computation(store, d.citation_id) == Decimal("0.9")
    claim = Claim(text="The reduction was 0.9 percentage points.", citation_ids=[d.citation_id])
    verify_answer_citations(Answer(claims=[claim]), {d.citation_id}, store)
    claim.text = "The reduction was 0.9%."
    with pytest.raises(CitationVerificationError):
        verify_answer_citations(Answer(claims=[claim]), {d.citation_id}, store)
    claim = Claim(
        text="Earlier years recorded a loss. Revenue is $600.", citation_ids=[c.citation_id]
    )
    verify_answer_citations(Answer(claims=[claim]), {c.citation_id}, store)


def test_used_as_is_not_cash_outflow_and_bound_value_wins(tmp_path):
    store = setup_store(tmp_path / "language.sqlite3")
    c = FactResolver(store).resolve(COMPANY, "revenue", "2024-FY").citations[0]
    for text in [
        "Cost of revenue (used as COGS) was $600.",
        "Cost of revenue was used as COGS and was $600.",
    ]:
        claim = Claim(
            text=text,
            citation_ids=[c.citation_id],
            numeric_bindings=[NumericBinding(text="$600", citation_id=c.citation_id)],
        )
        verify_answer_citations(Answer(claims=[claim]), {c.citation_id}, store)


def test_inline_enumeration_and_literal_maturity_binding(tmp_path):
    store, _, hit = evidence(tmp_path)
    c = hit.citation
    c.locator.exact_quote = "1.500% Notes due 2026; 1.750% Notes due 2030; 1.500% Notes due 2031."
    store.register_citation(c)
    claim = Claim(
        text="Notes: (1) 1.500% due 2026; (2) 1.750% due 2030; and (3) 1.500% due 2031.",
        citation_ids=[c.citation_id],
        numeric_bindings=[NumericBinding(text="2026", citation_id=c.citation_id)],
    )
    verify_answer_citations(Answer(claims=[claim]), {c.citation_id}, store)


def test_mixed_text_amount_and_derived_percent(tmp_path):
    store = setup_store(tmp_path / "mixed.sqlite3")
    c = FactResolver(store).resolve(COMPANY, "revenue", "2024-FY").citations[0]
    deps = SimpleNamespace(store=store, allowed_citation_ids={c.citation_id})
    d, _ = compute_evidence(deps, "a/a*18.5", {"a": c.citation_id}, "percent")
    _, _, hit = evidence(tmp_path)
    narrative = hit.citation
    narrative.locator.exact_quote = "Gross profit 2,725 ($ million); gross margin 18.5%."
    store.register_citation(narrative)
    allowed = {d.citation_id, narrative.citation_id}
    claim = Claim(
        text="Gross profit was $2,725 million, and gross margin was 18.5%.",
        citation_ids=list(allowed),
    )
    verify_answer_citations(Answer(claims=[claim]), allowed, store)
    claim.text = "Gross profit was $2,725 billion, and gross margin was 18.5%."
    with pytest.raises(CitationVerificationError, match="USD amount"):
        verify_answer_citations(Answer(claims=[claim]), allowed, store)


def test_historical_shard_8k_event_date_and_declared_exhibit(tmp_path):
    visited = []

    def handler(request):
        path = request.url.path
        visited.append(path)
        if path.endswith("CIK0000000001.json"):
            return httpx.Response(
                200,
                json={
                    "filings": {
                        "recent": {},
                        "files": [
                            {
                                "name": "CIK0000000001-submissions-001.json",
                                "filingFrom": "2019-01-01",
                                "filingTo": "2023-12-31",
                            }
                        ],
                    }
                },
            )
        if path.endswith("001.json"):
            return httpx.Response(
                200,
                json={
                    "accessionNumber": ["0000000001-22-000001"],
                    "form": ["8-K"],
                    "filingDate": ["2022-07-01"],
                    "reportDate": [""],
                    "primaryDocument": ["event.htm"],
                },
            )
        if path.endswith("-index.html"):
            return httpx.Response(
                200,
                text="<table><tr><td>1</td><td>Earnings Release</td>"
                '<td><a href="/Archives/ex991.htm">ex991.htm</a></td><td>EX-99.1</td></tr></table>',
            )
        return httpx.Response(200, text="<p>Original issuer earnings release evidence.</p>")

    async def run():
        client = SecClient(Settings(), transport=httpx.MockTransport(handler))
        try:
            files = await client.list_filings(
                COMPANY, ResearchScope(forms=["8-K"], fiscal_years=[2022])
            )
            assert len(files) == 1 and files[0].report_date is None
            docs = await client.list_documents(files[0])
            assert docs[0]["type"] == "EX-99.1"
            body = await client.fetch_document(files[0], "ex991.htm")
            assert "Original issuer" in body
            with pytest.raises(ValueError, match="not declared"):
                await client.fetch_document(files[0], "guessed.htm")
        finally:
            await client.close()

    asyncio.run(run())
    assert any("submissions-001" in p for p in visited)


def test_end_year_discovery_and_strict_form_guard(tmp_path, monkeypatch):
    store = setup_store(tmp_path / "dates.sqlite3")

    async def fetch(self, company):
        return store.list_facts(company.cik)

    monkeypatch.setattr(SecClient, "fetch_facts", fetch)
    agent = ResearchAgent(Settings(llm_api_key="fixture", llm_model="fixture"), store)
    graph, _, deps = agent._build_run(
        "Discover years",
        ResearchScope(companies=[COMPANY], fiscal_years=[2024], strict=True),
        [],
        "",
    )

    async def run():
        try:
            ctx = SimpleNamespace(deps=deps)
            tools = graph._function_toolset.tools
            result = await tools["discover_financial_periods"].function(
                ctx, tickers=["TEST"], end_years=[2024]
            )
            assert result["companies"][0]["periods"][0]["end"] == "2024-12-31"
            result = await tools["list_filings"].function(ctx, forms=["8-K"])
            assert result["status"] == "failed" and "strict" in result["error"]["message"]
        finally:
            await agent.research_tools.client.close()

    asyncio.run(run())
