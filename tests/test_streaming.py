import asyncio
import json
from datetime import date
from itertools import pairwise

import pytest
from pydantic_ai.models.function import DeltaToolCall, FunctionModel

from finagent import api
from finagent.agent import ResearchAgent
from finagent.config import Settings
from finagent.schemas import (
    Answer,
    AskRequest,
    Citation,
    Claim,
    Company,
    ComparisonTable,
    ResearchScope,
    SearchHit,
    SourceRef,
    TextLocator,
)
from finagent.storage import SQLiteStore
from finagent.verify.citations import CitationVerificationError, verify_answer_citations


@pytest.fixture(autouse=True)
def legacy_pipeline_settings(monkeypatch):
    monkeypatch.setattr(api, "get_settings", lambda: Settings(agentic_research=False))


def evidence(tmp_path):
    store = SQLiteStore(tmp_path / "stream.sqlite3")
    company = Company(cik="1", ticker="TEST", name="Test")
    citation = Citation(
        citation_id="source-1",
        source=SourceRef(
            source_type="filing_text",
            cik=company.cik,
            ticker="TEST",
            form="10-K",
            accession_no="a1",
            filing_date=date(2025, 1, 1),
            sec_url="https://www.sec.gov/Archives/test.htm",
        ),
        locator=TextLocator(
            section="Business",
            paragraph_index=0,
            exact_quote="Demand increased in 2024.",
            quote_sha256="hash",
        ),
    )
    store.register_citation(citation)
    return (
        store,
        ResearchScope(companies=[company]),
        SearchHit(
            citation=citation,
            text=citation.locator.exact_quote,
            score=1,
        ),
    )


def test_stream_retries_invalid_citation_and_only_then_completes(tmp_path, monkeypatch):
    store, scope, hit = evidence(tmp_path)
    calls = 0

    async def model_stream(messages, info):
        nonlocal calls
        calls += 1
        payload = Answer(
            claims=[
                Claim(
                    citation_ids=["invented" if calls == 1 else "source-1"],
                    text="2024 年需求有所改善。",
                )
            ]
        ).model_dump_json()
        yield {0: DeltaToolCall(name=info.output_tools[0].name, json_args=payload[:65])}
        await asyncio.sleep(0.1)
        yield {0: DeltaToolCall(json_args=payload[65:])}

    monkeypatch.setattr(
        "pydantic_ai.models.openai.OpenAIResponsesModel",
        lambda *args, **kwargs: FunctionModel(stream_function=model_stream),
    )
    agent = ResearchAgent(Settings(llm_api_key="fixture", llm_model="fixture"), store)

    async def collect():
        return [item async for item in agent.stream_answer("分析需求", scope, [hit])]

    snapshots = asyncio.run(collect())
    assert calls == 2
    assert any(item.status_reason == "validation_retry" for item in snapshots)
    assert all(item.status != "complete" for item in snapshots[:-1])
    assert snapshots[-1].status == "complete"
    assert snapshots[-1].claims[0].citation_ids == ["source-1"]
    assert all("invented" not in claim.citation_ids for item in snapshots for claim in item.claims)


def test_closed_claim_stream_is_append_only_and_hides_partial_strings(tmp_path):
    from finagent.answer_stream import CommittedAnswer, closed_claims

    store, _, _ = evidence(tmp_path)
    first = Claim(text="需求改善。", citation_ids=["source-1"])
    second = Claim(text="仍须关注风险。", citation_ids=["source-1"])
    raw = '{"claims":[' + first.model_dump_json() + ","
    assert closed_claims(raw + '{"text":"未完成') == [first]
    committed = CommittedAnswer()
    assert committed.update(raw, {"source-1"}, store).claims == [first]
    assert committed.update(raw, {"source-1"}, store) is None
    rewritten = Answer(claims=[second]).model_dump_json()
    assert committed.update(rewritten, {"source-1"}, store) is None
    extended = Answer(claims=[first, second]).model_dump_json()
    assert committed.update(extended, {"source-1"}, store).claims == [first, second]


def test_retry_cannot_replace_a_published_claim(tmp_path, monkeypatch):
    store, scope, hit = evidence(tmp_path)
    calls = 0
    first = Claim(text="已核对的需求描述。", citation_ids=["source-1"])

    async def model_stream(messages, info):
        nonlocal calls
        calls += 1
        if calls == 1:
            claims = [first, Claim(text="错误草稿", citation_ids=["invented"])]
        elif calls == 2:
            claims = [Claim(text="试图替换已展示文字", citation_ids=["source-1"])]
        else:
            claims = [first, Claim(text="修正后的风险描述。", citation_ids=["source-1"])]
        payload = Answer(claims=claims).model_dump_json()
        cut = payload.index("},") + 2 if calls != 2 else len(payload) // 2
        yield {0: DeltaToolCall(name=info.output_tools[0].name, json_args=payload[:cut])}
        await asyncio.sleep(0.1)
        yield {0: DeltaToolCall(json_args=payload[cut:])}

    monkeypatch.setattr(
        "pydantic_ai.models.openai.OpenAIResponsesModel",
        lambda *args, **kwargs: FunctionModel(stream_function=model_stream),
    )
    agent = ResearchAgent(Settings(llm_api_key="fixture", llm_model="fixture"), store)

    async def collect():
        return [item async for item in agent.stream_answer("分析", scope, [hit])]

    snapshots = asyncio.run(collect())
    visible = [item for item in snapshots if item.claims]
    assert calls == 3
    assert visible[-1].status == "complete"
    assert len(visible[0].claims) == 1
    for previous, current in pairwise(visible):
        assert current.claims[: len(previous.claims)] == previous.claims
    assert all(
        "错误草稿" not in c.text and "试图替换" not in c.text for s in visible for c in s.claims
    )


def test_year_does_not_require_xbrl_but_amount_does(tmp_path):
    store, _, _ = evidence(tmp_path)
    answer = Answer(claims=[Claim(citation_ids=["source-1"], text="2024 年 Q1 需求改善")])
    verify_answer_citations(answer, {"source-1"}, store)
    answer.claims[0].text = "2024 年收入为 123 万美元"
    with pytest.raises(CitationVerificationError, match="numeric"):
        verify_answer_citations(answer, {"source-1"}, store)


def test_sse_orders_sources_before_answer_and_done(tmp_path, monkeypatch):
    _, scope, hit = evidence(tmp_path)

    class Ingestion:
        async def ingest_scope(self, scope, progress):
            await progress("本地缓存命中")
            return {"facts": 1}

    class Agent:
        async def stream_answer(self, *args, **kwargs):
            owner = asyncio.current_task()
            yield Answer(claims=[], status="incomplete", status_reason="streaming")
            assert asyncio.current_task() is owner
            yield Answer(claims=[Claim(citation_ids=["source-1"], text="需求改善")])

    monkeypatch.setattr(api, "ingestion_service", Ingestion)
    monkeypatch.setattr(api, "research_agent", Agent)
    monkeypatch.setattr(
        api,
        "_prepare_answer_context",
        lambda request: (
            [hit],
            "",
            ComparisonTable(title="fixture", rows=[], verified=True),
        ),
    )

    async def collect():
        request = AskRequest(question="分析需求", scope=scope)
        return [event async for event in api._ask_events(request)]

    events = asyncio.run(collect())
    names = [event.splitlines()[0] for event in events]
    assert names.index("event: sources") < names.index("event: answer.snapshot")
    assert names[-1] == "event: done"
    assert json.loads(events[-1].split("data: ")[1])["status"] == "complete"


def test_sse_context_error_has_terminal_event(tmp_path, monkeypatch):
    _, scope, _ = evidence(tmp_path)

    class Ingestion:
        async def ingest_scope(self, scope, progress):
            return {}

    def fail(request):
        raise RuntimeError("fixture database failure")

    monkeypatch.setattr(api, "ingestion_service", Ingestion)
    monkeypatch.setattr(api, "_prepare_answer_context", fail)

    async def collect():
        request = AskRequest(question="分析需求", scope=scope)
        return [event async for event in api._ask_events(request)]

    events = asyncio.run(collect())
    assert events[-2].startswith("event: error")
    assert events[-1].startswith("event: done")
    assert '"status": "error"' in events[-1]


def test_disconnect_cancels_ingestion(tmp_path, monkeypatch):
    _, scope, _ = evidence(tmp_path)
    started = asyncio.Event()
    cancelled = asyncio.Event()

    class Ingestion:
        async def ingest_scope(self, scope, progress):
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

    monkeypatch.setattr(api, "ingestion_service", Ingestion)

    async def disconnect():
        events = api._ask_events(AskRequest(question="分析需求", scope=scope))
        await anext(events)
        await anext(events)
        pending = asyncio.create_task(anext(events))
        await started.wait()
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending
        await events.aclose()
        assert cancelled.is_set()

    asyncio.run(disconnect())
