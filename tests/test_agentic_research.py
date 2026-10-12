import asyncio
import json
from datetime import date

import pytest
from pydantic_ai.models.function import DeltaToolCall, FunctionModel
from test_facts_verifier_export import COMPANY, setup_store

from finagent import api, workspace
from finagent.agent import ResearchAgent
from finagent.config import Settings
from finagent.data.sec import SecClient
from finagent.execution import capabilities, rejected_execution
from finagent.schemas import Answer, AskRequest, Claim, Filing, ResearchScope


def test_model_fetches_data_without_initial_evidence(tmp_path, monkeypatch):
    store = setup_store(tmp_path / "agentic.sqlite3")
    calls = 0
    citation_ids = []
    events = []

    async def fetch(self, company):
        return store.list_facts(company.cik)

    monkeypatch.setattr(SecClient, "fetch_facts", fetch)

    async def model(messages, info):
        nonlocal calls
        calls += 1
        if calls == 1:
            assert any(
                "VERIFIED CONTEXT\nstrict_scope=false\nNone" in getattr(p, "content", "")
                for m in messages
                for p in m.parts
            )
            yield {
                0: DeltaToolCall(
                    name="get_financial_data",
                    json_args=json.dumps(
                        {
                            "metrics": ["revenue"],
                            "periods": ["2024-FY"],
                        }
                    ),
                )
            }
        else:
            assert citation_ids
            yield {
                0: DeltaToolCall(
                    name=info.output_tools[0].name,
                    json_args=Answer(
                        claims=[Claim(text="2024年收入为600美元。", citation_ids=citation_ids)],
                    ).model_dump_json(),
                )
            }

    monkeypatch.setattr(
        "pydantic_ai.models.openai.OpenAIResponsesModel",
        lambda *a, **kw: FunctionModel(stream_function=model),
    )
    agent = ResearchAgent(Settings(llm_api_key="fixture", llm_model="fixture"), store)

    def sink(event, data):
        events.append((event, data))
        if event == "sources":
            citation_ids.extend(c["citation_id"] for c in data["sources"])

    agent.event_sink = sink

    async def run():
        return [
            s
            async for s in agent.stream_answer(
                "查收入",
                ResearchScope(companies=[COMPANY], fiscal_years=[2024]),
                [],
            )
        ]

    result = asyncio.run(run())
    assert result[-1].status == "complete", result[-1]
    assert calls == 2
    assert any(
        e == "status" and d.get("phase") == "get_financial_data" and d["state"] == "complete"
        for e, d in events
    )


def test_read_search_pagination_scope_and_publication(tmp_path, monkeypatch):
    store = setup_store(tmp_path / "read.sqlite3")
    monkeypatch.setattr(api, "store", lambda: store)
    scope = ResearchScope(companies=[COMPANY], fiscal_years=[2024], strict=True)
    filing = Filing(
        cik=COMPANY.cik,
        accession_no="fixture-read",
        form="10-K",
        report_date=date(2024, 12, 31),
        filing_date=date(2025, 2, 1),
        sec_url="https://www.sec.gov/Archives/fixture.htm",
    )
    from finagent.retrieval.ingest import chunk_filing

    html = "<h1>Customers</h1>" + "".join(
        f"<p>Customer demand increased materially during this reporting period. Segment {i}.</p>"
        for i in range(24)
    )
    store.upsert_filing(filing, raw_html=html)
    store.upsert_chunks(chunk_filing(filing, COMPANY.ticker, html))

    async def listing(self, company, selected):
        return [filing]

    monkeypatch.setattr(SecClient, "list_filings", listing)
    thread = asyncio.run(workspace.create_thread())
    agent = ResearchAgent(Settings(llm_api_key="fixture", llm_model="fixture"), store)
    agent.tool_context = {"thread_id": thread["id"]}
    graph, _, deps = agent._build_run("研究客户", scope, [], "")
    tools = graph._function_toolset.tools
    from types import SimpleNamespace

    ctx = SimpleNamespace(deps=deps)

    async def run():
        try:
            first = await tools["search_filings"].function(ctx, query="customer", limit=8)
            second = await tools["search_filings"].function(
                ctx,
                query="customer",
                offset=8,
                limit=8,
            )
            assert first["next_offset"] == 8
            assert len(deps.allowed_citation_ids) == 16
            assert len(second["evidence"]) == 8
            read = await tools["read_filing"].function(ctx, accession=filing.accession_no, limit=2)
            assert len(read["evidence"]) == 2
            bad = await tools["get_financial_data"].function(
                ctx,
                metrics=["revenue"],
                periods=["2030-FY"],
            )
            assert bad["status"] == "failed"
            from finagent.tools import publish_workspace_file, write_workspace_file

            write_workspace_file(deps, "notes.md", "客户需求改善。")
            assert workspace.thread_data(thread["id"])["artifacts"] == []
            publish_workspace_file(deps, "notes.md")
            assert len(workspace.thread_data(thread["id"])["artifacts"]) == 1
        finally:
            await agent.research_tools.client.close()

    asyncio.run(run())


def test_agentic_api_skips_legacy_pipeline_and_finishes(tmp_path, monkeypatch):
    settings = Settings(llm_api_key="fixture", llm_model="fixture")
    monkeypatch.setattr(api, "get_settings", lambda: settings)

    def forbidden(*a, **kw):
        pytest.fail("Legacy preparation must not run in agentic mode")

    monkeypatch.setattr(api, "ingestion_service", forbidden)
    monkeypatch.setattr(api, "_prepare_answer_context", forbidden)

    class Agent:
        def __init__(self):
            self.generated_artifacts = []
            self.validation_errors = []

        async def stream_answer(self, question, scope, hits, **kw):
            assert hits == []
            self.event_sink(
                "status",
                {
                    "phase": "list_filings",
                    "tool_call_id": "test",
                    "state": "complete",
                    "message": "目录已读取",
                },
            )
            yield Answer(claims=[], caveats=["未找到可支持结论的来源"], status="refused")

    monkeypatch.setattr(api, "research_agent", Agent)

    async def run():
        return [
            e
            async for e in api._ask_events(
                AskRequest(
                    question="研究一下",
                    scope=ResearchScope(companies=[COMPANY], fiscal_years=[2024]),
                )
            )
        ]

    async def bounded():
        return await asyncio.wait_for(run(), timeout=3)

    events = asyncio.run(bounded())
    assert events[-1].startswith("event: done")
    assert not any('"phase": "files"' in e for e in events)
    assert any('"tool_call_id": "test"' in e for e in events), events


def test_execution_is_explicitly_rejected():
    assert capabilities()["available"] is False
    assert rejected_execution("python")["status"] == "rejected"
