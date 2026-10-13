import asyncio

import pytest
from pydantic_ai.models.function import DeltaToolCall, FunctionModel
from test_streaming import evidence

from finagent.agent import ResearchAgent
from finagent.config import Settings
from finagent.schemas import Answer, ResearchScope
from finagent.verify.citations import CitationVerificationError, verify_answer_citations


@pytest.mark.parametrize("question", ["你好", "您好！", "hi", "Hello!"])
def test_greetings_do_not_call_model_or_research(tmp_path, monkeypatch, question):
    store, _, _ = evidence(tmp_path)
    agent = ResearchAgent(Settings(llm_api_key="fixture", llm_model="fixture"), store)

    def fail(*args, **kwargs):
        raise AssertionError("Greeting started research")

    monkeypatch.setattr(agent, "_build_run", fail)

    async def run():
        scope = ResearchScope(language="zh")
        direct = await agent.answer(question, scope, [])
        streamed = [a async for a in agent.stream_answer(question, scope, [])]
        assert direct == streamed[-1]
        assert direct.status == "complete" and direct.message and direct.claims == []
        assert not agent.validation_errors

    asyncio.run(run())


def test_unrelated_structured_reply_needs_no_citations(tmp_path, monkeypatch):
    store, scope, _ = evidence(tmp_path)

    async def model(messages, info):
        yield {
            0: DeltaToolCall(
                name=info.output_tools[0].name,
                json_args=Answer(
                    claims=[], message="我主要帮助分析财报和公司研究。"
                ).model_dump_json(),
            )
        }

    monkeypatch.setattr(
        "pydantic_ai.models.openai.OpenAIResponsesModel",
        lambda *args, **kwargs: FunctionModel(stream_function=model),
    )
    agent = ResearchAgent(Settings(llm_api_key="fixture", llm_model="fixture"), store)

    async def run():
        outputs = [a async for a in agent.stream_answer("帮我写菜谱", scope, [])]
        assert outputs[-1].status == "complete"
        assert outputs[-1].message and outputs[-1].claims == []
        assert not agent.validation_errors

    asyncio.run(run())


@pytest.mark.parametrize("message", ["Revenue is $600.", "收入600万元。", "Margin is 30%."])
def test_conversational_field_cannot_bypass_amount_verification(tmp_path, message):
    store, _, _ = evidence(tmp_path)
    with pytest.raises(CitationVerificationError, match="Conversational"):
        verify_answer_citations(Answer(claims=[], message=message), set(), store)
