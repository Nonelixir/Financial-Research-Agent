import asyncio
import json
import socket
from hashlib import sha256
from types import SimpleNamespace

import pytest
from pydantic_ai.models.function import DeltaToolCall, FunctionModel
from test_facts_verifier_export import COMPANY, setup_store

from finagent import api, workspace
from finagent.agent import ResearchAgent
from finagent.config import Settings
from finagent.schemas import Answer, Claim, Company, ResearchScope
from finagent.web import PublicWeb, public_addresses


def test_empty_scope_model_discovers_reads_and_sets_sample(tmp_path, monkeypatch):
    store = setup_store(tmp_path / "industry.sqlite3")
    monkeypatch.setattr(api, "store", lambda: store)
    thread = asyncio.run(workspace.create_thread())
    calls = 0
    ids = []

    async def web_read(self, url):
        return {
            "url": url,
            "title": "Test optical company",
            "content_sha256": "abc123",
            "fetched_at": "2026-10-12T00:00:00+00:00",
            "paragraphs": ["Test Corp develops optical communications products for data centers."],
        }

    monkeypatch.setattr(PublicWeb, "read", web_read)

    async def model(messages, info):
        nonlocal calls
        calls += 1
        if calls == 1:
            yield {0: DeltaToolCall(name="resolve_companies", json_args='{"query":"TEST"}')}
        elif calls == 2:
            yield {
                0: DeltaToolCall(name="read_web", json_args='{"url":"https://example.com/about"}')
            }
        elif calls == 3:
            assert ids
            yield {
                0: DeltaToolCall(
                    name="set_research_sample",
                    json_args=json.dumps(
                        {
                            "members": [
                                {"ticker": "TEST", "reason": "从事光通信产品", "citation_ids": ids}
                            ],
                        }
                    ),
                )
            }
        else:
            yield {
                0: DeltaToolCall(
                    name=info.output_tools[0].name,
                    json_args=Answer(
                        claims=[
                            Claim(
                                text="Test Corp 从事光通信产品，可作为非穷尽研究样本。",
                                citation_ids=ids,
                            ),
                        ]
                    ).model_dump_json(),
                )
            }

    monkeypatch.setattr(
        "pydantic_ai.models.openai.OpenAIResponsesModel",
        lambda *a, **kw: FunctionModel(stream_function=model),
    )
    agent = ResearchAgent(Settings(llm_api_key="fixture", llm_model="fixture"), store)
    agent.tool_context = {"thread_id": thread["id"]}

    def emit(event, data):
        if event == "sources":
            ids.extend(data["citation_ids"])

    agent.event_sink = emit

    async def run():
        return [item async for item in agent.stream_answer("研究光通信行业", ResearchScope(), [])]

    result = asyncio.run(run())
    assert result[-1].status == "complete", result[-1]
    assert calls == 4
    sample = workspace.thread_data(thread["id"])["research_sample"]
    assert sample["members"][0]["company"]["ticker"] == "TEST"
    assert sample["members"][0]["citation_ids"] == ids
    assert sample["exhaustive"] is False
    assert store.get_citation(ids[0]).source.source_type == "web"


def test_preferences_are_not_company_or_year_permissions(tmp_path):
    store = setup_store(tmp_path / "scope.sqlite3")
    other = Company(cik="2", ticker="OTHER", name="Other Company")
    store.upsert_company(other)
    settings = Settings(llm_api_key="fixture", llm_model="fixture")
    agent = ResearchAgent(settings, store)

    async def run():
        try:
            ctx = SimpleNamespace(deps=deps)
            result = await agent_graph._function_toolset.tools["resolve_companies"].function(
                ctx, query="OTHER"
            )
            assert result["companies"][0]["ticker"] == "OTHER"
            assert tools.scope(["OTHER"], [2025]).companies == [other]
        finally:
            await tools.client.close()

    agent_graph, _, deps = agent._build_run(
        "研究行业", ResearchScope(companies=[COMPANY], fiscal_years=[2024]), [], ""
    )
    tools = agent.research_tools
    asyncio.run(run())


def test_export_discovered_scope_without_ui_selection(tmp_path, monkeypatch):
    store = setup_store(tmp_path / "export.sqlite3")
    monkeypatch.setattr(api, "store", lambda: store)
    thread = asyncio.run(workspace.create_thread())
    agent = ResearchAgent(Settings(llm_api_key="fixture", llm_model="fixture"), store)
    agent.tool_context = {"thread_id": thread["id"]}
    graph, prompt, deps = agent._build_run("导出", ResearchScope(), [], "")
    assert "strict_scope=false" in prompt

    async def run():
        try:
            ctx = SimpleNamespace(deps=deps)
            await graph._function_toolset.tools["resolve_companies"].function(ctx, query="TEST")
            tool = graph._function_toolset.tools["generate_workbook"].function
            result = await tool(ctx, frequency="annual", tickers=["TEST"], years=[2024])
            assert result["verified"] is True
            assert result["periods"] == ["2024-FY"]
            # Identical export can reuse the artifact; changing scope cannot.
            repeated = await tool(ctx, frequency="annual", tickers=["TEST"], years=[2024])
            assert repeated["artifact_id"] == result["artifact_id"]
            assert len(workspace.thread_data(thread["id"])["artifacts"]) == 1
        finally:
            await agent.research_tools.client.close()

    asyncio.run(run())


def test_sec_citation_ids_survive_optional_web_fields(tmp_path):
    from finagent.data.facts import FactResolver
    from finagent.schemas import Citation

    store = setup_store(tmp_path / "ids.sqlite3")
    citation = FactResolver(store).resolve(COMPANY, "revenue", "2024-FY").citations[0]
    material = (
        citation.source.model_dump_json(exclude={"sec_url", "content_sha256", "title"})
        + citation.locator.model_dump_json()
    )
    legacy_id = "C" + sha256(material.encode()).hexdigest()[:16].upper()
    assert Citation.stable_id(citation.source, citation.locator) == legacy_id


def test_web_numeric_substrings_do_not_pass(tmp_path):
    from datetime import date

    from finagent.schemas import Citation, SourceRef, TextLocator
    from finagent.verify.citations import CitationVerificationError, verify_answer_citations

    store = setup_store(tmp_path / "numeric.sqlite3")
    quote = "The reported figure is 312, not a verified financial comparison."
    source = SourceRef(
        source_type="web",
        cik="",
        ticker="",
        form="web",
        accession_no="",
        filing_date=date(2026, 10, 12),
        sec_url="https://example.com",
        content_sha256=sha256(quote.encode()).hexdigest(),
    )
    locator = TextLocator(
        section="web",
        paragraph_index=0,
        exact_quote=quote,
        quote_sha256=sha256(quote.encode()).hexdigest(),
    )
    citation = Citation(
        citation_id=Citation.stable_id(source, locator), source=source, locator=locator
    )
    store.register_citation(citation)
    answer = Answer(claims=[Claim(text="金额为12。", citation_ids=[citation.citation_id])])
    with pytest.raises(CitationVerificationError):
        verify_answer_citations(answer, {citation.citation_id}, store)


@pytest.mark.parametrize("scenario", ["private_redirect", "oversized", "compressed"])
def test_public_transport_rejects_unsafe_responses(monkeypatch, scenario):
    import httpcore

    from finagent.web import fetch_public

    visited = []

    async def dns(host, *args, **kw):
        address = "127.0.0.1" if host == "127.0.0.1" else "8.8.8.8"
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 443))]

    class Response:
        status = 302 if scenario == "private_redirect" else 200
        headers = (
            [(b"location", b"https://127.0.0.1/secrets")]
            if scenario == "private_redirect"
            else [(b"content-type", b"text/plain")]
        ) + ([(b"content-encoding", b"gzip")] if scenario == "compressed" else [])

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def aiter_stream(self):
            yield b"12345"

    class Pool:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        def stream(self, method, url, **kwargs):
            visited.append(url)
            return Response()

    monkeypatch.setattr(httpcore, "AsyncConnectionPool", Pool)

    async def run():
        monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", dns)
        with pytest.raises(ValueError):
            await fetch_public("https://example.com", max_bytes=4)

    asyncio.run(run())
    assert visited == ["https://example.com"]


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com",
        "https://localhost/",
        "https://127.0.0.1/",
        "https://169.254.169.254/",
        "https://user:pass@example.com",
        "https://example.com:444/",
        "https://[::1]/",
    ],
)
def test_private_and_unsafe_urls_rejected(url):
    with pytest.raises(ValueError):
        asyncio.run(public_addresses(url))


def test_dns_mixed_private_address_rejected(monkeypatch):
    async def dns(*args, **kw):
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.1", 443)),
        ]

    async def run():
        monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", dns)
        with pytest.raises(ValueError):
            await public_addresses("https://example.com")

    asyncio.run(run())


def test_web_read_saves_original_snapshot(tmp_path, monkeypatch):
    store = setup_store(tmp_path / "web.sqlite3")

    async def fetch(url, max_bytes):
        return (
            url,
            "<title>Industry</title><p>Optical networks connect data centers around the world.</p>",
            "text/html",
        )

    monkeypatch.setattr("finagent.web.fetch_public", fetch)
    page = asyncio.run(PublicWeb(store, Settings()).read("https://example.com"))
    assert "Optical networks" in page["paragraphs"][0]
    with store.connect() as connection:
        snapshot = connection.execute("SELECT * FROM source_snapshots").fetchone()
        assert snapshot["content_sha256"] == page["content_sha256"]
        assert "<title>Industry</title>" in snapshot["body"]
