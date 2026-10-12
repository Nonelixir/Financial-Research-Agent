import asyncio
import json
from types import SimpleNamespace

import pytest
from pydantic_ai.models.function import DeltaToolCall, FunctionModel
from test_streaming import evidence

from finagent import api, workspace
from finagent.agent import ResearchAgent
from finagent.answer_stream import CommittedAnswer
from finagent.config import Settings
from finagent.schemas import Answer, Claim
from finagent.tools import publish_research_report
from finagent.verify.citations import CitationVerificationError, verify_answer_citations


@pytest.mark.parametrize(
    "text",
    [
        "研究覆盖6家公司。",
        "近2年需求有所改善。",
        "依据10-K研究。",
        "3D封装属于技术路线。",
        "1. 行业概览",
        "近2年口径为2024-01-28至2025-01-26，2025 Q4另列。",
        "研报下载：/api/artifacts/400dd51687ab4b8ab8df91706bca16c5/download",
    ],
)
def test_scope_numbers_not_financial_amounts(tmp_path, text):
    store, _, _ = evidence(tmp_path)
    verify_answer_citations(
        Answer(claims=[Claim(text=text, citation_ids=["source-1"])]), {"source-1"}, store
    )


def test_real_amount_still_rejected_and_error_identifies_claim(tmp_path):
    store, _, _ = evidence(tmp_path)
    with pytest.raises(CitationVerificationError, match=r"Claim 1.*unsupported"):
        verify_answer_citations(
            Answer(claims=[Claim(text="收入123美元", citation_ids=["source-1"])]),
            {"source-1"},
            store,
        )


def test_failure_recovers_valid_sections_after_bad_first_claim(tmp_path):
    store, _, _ = evidence(tmp_path)
    stream = CommittedAnswer()
    good = Claim(text="可以核对的原文摘要。", citation_ids=["source-1"])
    assert (
        stream.update(
            Answer(claims=[Claim(text="错误", citation_ids=["fake"]), good]).model_dump_json(),
            {"source-1"},
            store,
        )
        is None
    )
    agent = ResearchAgent(Settings(), store)
    agent.committed_answer = stream
    result = agent._error_answer(RuntimeError("Exceeded maximum output retries"))
    assert result.status == "incomplete"
    assert result.claims == [good]


def test_wrong_chinese_currency_scale_blocked(tmp_path):
    from test_facts_verifier_export import COMPANY, setup_store

    from finagent.data.facts import FactResolver

    store = setup_store(tmp_path / "amount.sqlite3")
    citation = FactResolver(store).resolve(COMPANY, "revenue", "2024-FY").citations[0]
    ids = {citation.citation_id}
    for text in ["收入为600美元。", "收入为0.000006亿美元。"]:
        verify_answer_citations(
            Answer(claims=[Claim(text=text, citation_ids=list(ids))]), ids, store
        )
    with pytest.raises(CitationVerificationError, match="unit mismatch"):
        verify_answer_citations(
            Answer(claims=[Claim(text="收入为600亿美元。", citation_ids=list(ids))]), ids, store
        )


def test_report_is_real_source_checked_file(tmp_path, monkeypatch):
    store, scope, _ = evidence(tmp_path)
    monkeypatch.setattr(api, "store", lambda: store)
    thread = asyncio.run(workspace.create_thread())
    deps = SimpleNamespace(
        store=store,
        scope=scope,
        allowed_citation_ids={"source-1"},
        generated_artifacts=[],
        tool_context={"thread_id": thread["id"]},
    )
    result = publish_research_report(
        deps,
        "研究报告",
        [Claim(text="## 行业\n\n近2年需求改善。", citation_ids=["source-1"])],
        ["仅为非穷尽样本。"],
    )
    artifact = workspace.thread_data(thread["id"])["artifacts"][0]
    assert artifact["id"] == result["artifact_id"]
    assert artifact["data"]["citation_ids"] == ["source-1"]
    assert (
        workspace.session_files(thread["id"])
        .read(artifact["file"]["relative_path"])
        .startswith("# 研究报告".encode())
    )
    with pytest.raises(CitationVerificationError):
        publish_research_report(deps, "失败", [Claim(text="伪造", citation_ids=["fake"])], [])
    assert len(deps.generated_artifacts) == 1


def test_model_cannot_complete_report_without_delivery(tmp_path, monkeypatch):
    store, scope, hit = evidence(tmp_path)
    monkeypatch.setattr(api, "store", lambda: store)
    thread = asyncio.run(workspace.create_thread())
    calls = 0

    async def model(messages, info):
        nonlocal calls
        calls += 1
        if calls == 2:
            yield {
                0: DeltaToolCall(
                    name="publish_report",
                    json_args=json.dumps(
                        {
                            "title": "研报",
                            "sections": [
                                {"text": "## 结论\n需求改善。", "citation_ids": ["source-1"]}
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
                        claims=[Claim(text="研究结果可核对。", citation_ids=["source-1"])]
                    ).model_dump_json(),
                )
            }

    monkeypatch.setattr(
        "pydantic_ai.models.openai.OpenAIResponsesModel",
        lambda *a, **kw: FunctionModel(stream_function=model),
    )
    agent = ResearchAgent(Settings(llm_api_key="fixture", llm_model="fixture"), store)
    agent.tool_context = {"thread_id": thread["id"]}

    async def run():
        return [s async for s in agent.stream_answer("写一份深度研报", scope, [hit])]

    output = asyncio.run(run())
    assert calls == 3
    assert output[-1].status == "complete"
    assert agent.generated_artifacts[0]["data"]["report"] is True
    assert any("no source-checked report" in e for e in agent.validation_errors)


def test_discover_periods_and_report_plan_guard(tmp_path, monkeypatch):
    from test_facts_verifier_export import COMPANY, setup_store

    from finagent.data.sec import SecClient
    from finagent.schemas import ResearchScope

    store = setup_store(tmp_path / "periods.sqlite3")

    async def fetch(self, company):
        return store.list_facts(company.cik)

    monkeypatch.setattr(SecClient, "fetch_facts", fetch)
    agent = ResearchAgent(Settings(llm_api_key="fixture", llm_model="fixture"), store)
    graph, _, deps = agent._build_run("写研报", ResearchScope(companies=[COMPANY]), [], "")

    async def run():
        try:
            ctx = SimpleNamespace(deps=deps)
            functions = graph._function_toolset.tools
            result = await functions["discover_financial_periods"].function(ctx, tickers=["TEST"])
            assert result["companies"][0]["periods"][0]["period"] == "2024-FY"
            result = await functions["update_plan"].function(ctx, steps=["交付研报"], completed=[0])
            assert result["status"] == "failed"
            assert "publish_report" in result["error"]["message"]
            result = await functions["update_plan"].function(ctx, steps=["研究"], completed=[1])
            assert result["status"] == "failed"
            assert "ZERO-based" in result["error"]["message"]
            result = await functions["get_financial_data"].function(
                ctx, tickers=["TEST"], metrics=["capex"], periods=["2024-FY"]
            )
            assert result["rows"][0]["metric"] == "capital_expenditure"
        finally:
            await agent.research_tools.client.close()

    asyncio.run(run())
