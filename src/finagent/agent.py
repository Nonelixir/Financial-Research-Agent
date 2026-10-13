from __future__ import annotations

import functools
import re
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from finagent.config import Settings
from finagent.prompts import load_prompts
from finagent.schemas import Answer, Claim, CompletionStatus, ResearchScope, SearchHit
from finagent.storage import SQLiteStore
from finagent.verify.citations import CitationVerificationError, verify_answer_citations


@dataclass
class AgentDeps:
    store: SQLiteStore
    allowed_citation_ids: set[str]
    scope: ResearchScope
    tool_context: dict
    generated_artifacts: list[dict]
    evidence: dict = field(default_factory=dict)


class ResearchAgent:
    def __init__(self, settings: Settings, store: SQLiteStore) -> None:
        self.settings = settings
        self.store = store
        self.tool_context: dict = {}
        self.generated_artifacts: list[dict] = []
        self.event_sink = None
        self.validation_errors: list[str] = []
        self.tool_calls = 0
        self.committed_answer = None
        self.language = "zh"

    def text(self, zh: str, en: str) -> str:
        return en if self.language == "en" else zh

    def greeting(self, question: str, scope: ResearchScope) -> Answer | None:
        normalized = re.sub(r"[\s!！。,.，?？]+", "", question).casefold()
        if normalized not in {"你好", "您好", "嗨", "哈喽", "hello", "hi", "hey"}:
            return None
        return Answer(
            claims=[],
            message=(
                "Hello! I can help you research companies and financial filings. "
                "What would you like to explore?"
                if scope.language == "en"
                else "你好！我可以帮助你研究公司、分析财报或生成报告。你想了解什么？"
            ),
        )

    def emit(self, event: str, payload: dict) -> None:
        from finagent.localization import status_payload

        if self.event_sink:
            self.event_sink(event, status_payload(event, payload, self.language))

    def validation_failure(self, message: str, output: Answer | None = None) -> None:
        self.validation_errors.append(message)
        self.emit(
            "status",
            {
                "phase": "generation",
                "state": "active",
                "message": "回答或交付检查未通过，正在修正",
                "detail": {
                    "error": message,
                    "attempt": len(self.validation_errors),
                    "claim_previews": [c.model_dump() for c in output.claims[:3]] if output else [],
                },
            },
        )

    def trace_file_tool(self, func, run_context):
        @functools.wraps(func)
        async def wrapped(ctx, *args, **kwargs):
            self.tool_calls += 1
            self.tool_context["file_calls"] = self.tool_calls
            call_id = uuid4().hex
            name = func.__name__
            self.emit(
                "status",
                {
                    "phase": name,
                    "state": "active",
                    "tool_call_id": call_id,
                    "message": f"正在调用 {name}",
                    "detail": kwargs,
                },
            )
            try:
                if (
                    self.tool_calls + self.tool_context.get("research_calls", 0)
                    > self.settings.agent_max_tool_calls
                ):
                    raise ValueError("File tool-call budget exhausted")
                result = await func(ctx, *args, **kwargs)
                self.emit(
                    "status",
                    {
                        "phase": name,
                        "state": "warning" if result.get("status") == "failed" else "complete",
                        "tool_call_id": call_id,
                        "message": result.get("error", f"{name} 已完成"),
                        "detail": result,
                    },
                )
                return result
            except Exception as exc:
                self.emit(
                    "status",
                    {
                        "phase": name,
                        "state": "warning",
                        "tool_call_id": call_id,
                        "message": str(exc)[:1000],
                        "detail": {"error": str(exc)},
                    },
                )
                raise

        wrapped.__annotations__["ctx"] = run_context[AgentDeps]
        return wrapped

    async def answer(
        self,
        question: str,
        scope: ResearchScope,
        hits: list[SearchHit],
        extra_context: str = "",
    ) -> Answer:
        self.language = scope.language
        if greeting := self.greeting(question, scope):
            return greeting
        if not hits and (
            not self.settings.agentic_research
            or not self.settings.llm_api_key
            or not self.settings.llm_model
        ):
            return Answer(
                claims=[],
                caveats=[
                    self.text(
                        "在所选 SEC 文件中未找到足够证据。",
                        "Insufficient evidence in the selected SEC filings.",
                    )
                ],
                status=CompletionStatus.REFUSED,
                status_reason="no_evidence",
            )
        if not self.settings.llm_api_key or not self.settings.llm_model:
            first = hits[0]
            excerpt = first.text[:500].strip()
            return Answer(
                claims=[
                    Claim(
                        text=self.text(
                            "未配置生成模型；最相关的 SEC 原文为：",
                            "No generation model configured. Most relevant SEC excerpt: ",
                        )
                        + excerpt,
                        citation_ids=[first.citation.citation_id],
                    )
                ],
                caveats=[
                    self.text(
                        "这是抽取式降级结果，未进行生成式综合。",
                        "Extractive fallback only; no generative synthesis was performed.",
                    )
                ],
                status=CompletionStatus.COMPLETE,
            )
        try:
            return await self._run_pydantic_agent(question, scope, hits, extra_context)
        except CitationVerificationError as exc:
            return Answer(
                claims=[],
                caveats=[
                    self.text(
                        "模型输出未通过引用校验。", "Model output failed citation validation."
                    )
                ],
                status=CompletionStatus.REFUSED,
                status_reason=str(exc),
            )
        except Exception as exc:
            return self._error_answer(exc)

    async def stream_answer(
        self,
        question: str,
        scope: ResearchScope,
        hits: list[SearchHit],
        extra_context: str = "",
    ) -> AsyncIterator[Answer]:
        self.language = scope.language
        if greeting := self.greeting(question, scope):
            yield greeting
            return
        if (
            (not hits and not self.settings.agentic_research)
            or not self.settings.llm_api_key
            or not self.settings.llm_model
        ):
            yield await self.answer(question, scope, hits, extra_context)
            return
        try:
            async for snapshot in self._stream_pydantic_agent(question, scope, hits, extra_context):
                yield snapshot
        except CitationVerificationError as exc:
            yield Answer(
                claims=list(self.committed_answer.claims) if self.committed_answer else [],
                caveats=[
                    self.text(
                        "模型输出未通过引用校验。", "Model output failed citation validation."
                    )
                ],
                status=CompletionStatus.REFUSED,
                status_reason=str(exc),
            )
        except Exception as exc:
            yield self._error_answer(exc)

    def _error_answer(self, exc: Exception) -> Answer:
        message = str(exc)
        if self.validation_errors:
            message += "; validation: " + " | ".join(self.validation_errors[-3:])
        claims = list(self.committed_answer.claims) if self.committed_answer else []
        if self.committed_answer:
            claims.extend(c for c in self.committed_answer.recoverable if c not in claims)
        research = getattr(self, "research_tools", None)
        if not claims and research:
            # Extractive recovery, explicitly not an invented research conclusion.
            for citation in research.deps.evidence.values():
                if citation.value is not None:
                    claims.append(
                        Claim(
                            text=self.text(
                                "已获取数据（非完整分析）：",
                                "Retrieved data (not a complete analysis): ",
                            )
                            + f"{citation.source.ticker} {citation.locator.concept}; "
                            + f"period end {citation.locator.end}; "
                            + f"value {citation.value.amount} {citation.value.unit}.",
                            citation_ids=[citation.citation_id],
                        )
                    )
                if len(claims) >= 6:
                    break
        incomplete = bool(claims or self.generated_artifacts) or any(
            token in message.lower() for token in ["max_output", "length", "maximum output retries"]
        )
        return Answer(
            claims=claims,
            caveats=[
                self.text(
                    "本轮未完成。保留可核对的部分结果，不代表完整研报或已完成交付。",
                    "This turn is incomplete. Verifiable partial results are retained; "
                    "this is not a complete report or delivery.",
                )
            ],
            status=(CompletionStatus.INCOMPLETE if incomplete else CompletionStatus.ERROR),
            status_reason=message[:500],
        )

    async def _run_pydantic_agent(
        self,
        question: str,
        scope: ResearchScope,
        hits: list[SearchHit],
        extra_context: str,
    ) -> Answer:
        agent, prompt, deps = self._build_run(question, scope, hits, extra_context)
        from pydantic_ai.usage import UsageLimits

        try:
            result = await agent.run(
                prompt,
                deps=deps,
                usage_limits=UsageLimits(
                    request_limit=self.settings.agent_max_tool_calls + 5,
                    tool_calls_limit=self.settings.agent_max_tool_calls,
                ),
            )
            return verify_answer_citations(result.output, deps.allowed_citation_ids, self.store)
        finally:
            if self.research_tools:
                await self.research_tools.client.close()

    async def _stream_pydantic_agent(
        self,
        question: str,
        scope: ResearchScope,
        hits: list[SearchHit],
        extra_context: str,
    ) -> AsyncIterator[Answer]:
        agent, prompt, deps = self._build_run(question, scope, hits, extra_context)
        try:
            async for output in self._stream_graph(agent, prompt, deps):
                yield output
        finally:
            if self.research_tools:
                await self.research_tools.client.close()

    async def _stream_graph(self, agent, prompt, deps):
        from pydantic_ai.messages import RetryPromptPart, ToolCallPart
        from pydantic_ai.usage import UsageLimits

        from finagent.answer_stream import CommittedAnswer

        self.committed_answer = CommittedAnswer()

        attempts = 0
        called_tool = False
        async with agent.iter(
            prompt,
            deps=deps,
            usage_limits=UsageLimits(
                request_limit=self.settings.agent_max_tool_calls + 5,
                tool_calls_limit=self.settings.agent_max_tool_calls,
            ),
        ) as run:
            async for node in run:
                if agent.is_call_tools_node(node):
                    for part in node.model_response.parts:
                        # Public output drafts only; never capture private reasoning.
                        if (
                            isinstance(part, ToolCallPart)
                            and agent._output_toolset
                            and (part.tool_name in agent._output_toolset.processors)
                        ):
                            self.committed_answer.update(
                                part.args_as_json_str(), deps.allowed_citation_ids, self.store
                            )
                    tool_names = {
                        getattr(part, "tool_name", None) for part in node.model_response.parts
                    }
                    if tool_names & set(agent._function_toolset.tools):
                        called_tool = True
                    if not self.settings.agentic_research and tool_names & {
                        "generate_workbook",
                        "list_files",
                        "read_file",
                        "write_file",
                    }:
                        yield Answer(
                            claims=[],
                            caveats=[],
                            status=CompletionStatus.INCOMPLETE,
                            status_reason="workbook_running"
                            if "generate_workbook" in tool_names
                            else "files_running",
                        )
                if not agent.is_model_request_node(node):
                    continue
                attempts += 1
                for message in run.all_messages():
                    for part in message.parts:
                        if isinstance(part, RetryPromptPart):
                            detail = str(part.content)[:1800]
                            if detail not in self.validation_errors:
                                self.validation_failure(detail)
                if attempts > 1 and not called_tool:
                    yield Answer(
                        claims=[],
                        caveats=[],
                        status=CompletionStatus.INCOMPLETE,
                        status_reason="validation_retry",
                    )
                async with node.stream(run.ctx) as stream:
                    async for response in stream.stream_response(debounce_by=0.08):
                        # Only closed claims from output-tool arguments are public.
                        # Text/reasoning/tool planning and incomplete strings never enter the body.
                        for part in response.parts:
                            if not isinstance(part, ToolCallPart):
                                continue
                            if (
                                agent._output_toolset is None
                                or part.tool_name not in agent._output_toolset.processors
                            ):
                                continue
                            if (
                                self.tool_context.get("thread_id")
                                and deps.tool_context.get("requires_workbook")
                                and not any(a["kind"] == "table" for a in deps.generated_artifacts)
                            ):
                                continue
                            output = self.committed_answer.update(
                                part.args_as_json_str(), deps.allowed_citation_ids, self.store
                            )
                            if output is not None:
                                yield output
            if run.result is None:
                raise RuntimeError("Agent completed without a final result")
            final = run.result.output
        yield verify_answer_citations(final, deps.allowed_citation_ids, self.store)

    def _build_run(
        self,
        question: str,
        scope: ResearchScope,
        hits: list[SearchHit],
        extra_context: str,
    ) -> tuple[Any, str, AgentDeps]:
        try:
            from pydantic_ai import Agent, ModelRetry, RunContext
            from pydantic_ai.models.openai import OpenAIChatModel, OpenAIResponsesModel
            from pydantic_ai.providers.openai import OpenAIProvider
            from pydantic_ai.settings import ModelSettings
        except ImportError as exc:
            raise RuntimeError("Install the agent extra with: pip install -e '.[agent]'") from exc

        prompts = load_prompts(self.settings.prompt_config_path)
        self.tool_context["requires_workbook"] = bool(
            re.search(r"xlsx|excel|工作簿", question, re.IGNORECASE)
        )
        self.tool_context["requires_report"] = bool(
            re.search(
                r"(?:写|撰写|生成|输出|提供|给我).{0,30}(?:研报|研究报告)|"
                r"(?:write|generate|produce).{0,40}(?:research report|deep report)",
                question,
                re.I,
            )
        )
        provider = OpenAIProvider(
            base_url=self.settings.llm_base_url,
            api_key=self.settings.llm_api_key,
        )
        model_settings = ModelSettings(
            max_tokens=(
                max(self.settings.llm_max_output_tokens, self.settings.llm_report_output_tokens)
                if self.tool_context["requires_report"]
                else self.settings.llm_max_output_tokens
            )
        )
        if self.settings.llm_api_mode == "responses":
            model: Any = OpenAIResponsesModel(
                self.settings.llm_model, provider=provider, settings=model_settings
            )
        elif self.settings.llm_api_mode == "chat_completions":
            model = OpenAIChatModel(
                self.settings.llm_model, provider=provider, settings=model_settings
            )
        else:
            raise ValueError("LLM_API_MODE must be responses or chat_completions")
        agent: Any = Agent(
            model,
            deps_type=AgentDeps,
            output_type=Answer,
            system_prompt=prompts.system_for(scope.language),
            retries=self.settings.llm_max_retries,
        )

        if self.tool_context.get("thread_id"):

            async def generate_workbook(
                ctx: RunContext[AgentDeps],
                frequency: str = "quarterly",
                tickers: list[str] | None = None,
                years: list[int] | None = None,
            ) -> dict:
                """Generate a downloadable verified XLSX, annual or quarterly.

                Use quarterly for quarter comparisons with separate statement sheets.
                Pass resolved tickers and discovered fiscal years in open research.
                Fetch financial data first. Returns artifact and download URL.
                """
                from finagent.tools import generate_financial_workbook

                if frequency not in {"quarterly", "annual"}:
                    raise ModelRetry("frequency must be quarterly or annual")
                try:
                    export_scope = (
                        self.research_tools.scope(tickers, years)
                        if self.research_tools
                        else ctx.deps.scope
                    )
                    if not export_scope.fiscal_years:
                        raise ValueError(
                            "Provide discovered fiscal years via years before exporting"
                        )
                    return generate_financial_workbook(ctx.deps, frequency, export_scope)
                except ValueError as exc:
                    raise ModelRetry(str(exc)) from exc

            # RunContext is imported lazily; resolve it before the tool's
            # schema introspection evaluates postponed annotations.
            generate_workbook.__annotations__["ctx"] = RunContext[AgentDeps]
            agent.tool(self.trace_file_tool(generate_workbook, RunContext))

            async def list_files(ctx: RunContext[AgentDeps]) -> dict:
                """List files in this conversation's isolated working directory."""
                from finagent.tools import list_workspace_files

                try:
                    return {"files": list_workspace_files(ctx.deps)}
                except (OSError, ValueError) as exc:
                    raise ModelRetry(str(exc)) from exc

            async def read_file(ctx: RunContext[AgentDeps], filename: str) -> dict:
                """Read a UTF-8 md/txt/csv/json file in this session only; no directories."""
                from finagent.tools import read_workspace_file

                try:
                    return read_workspace_file(ctx.deps, filename)
                except (OSError, ValueError) as exc:
                    raise ModelRetry(str(exc)) from exc

            async def write_file(ctx: RunContext[AgentDeps], filename: str, content: str) -> dict:
                """Create a working UTF-8 md/txt/csv/json file. Does NOT publish an artifact.

                No overwrite; choose a new version filename. Use publish_artifact for delivery.
                """
                from finagent.tools import write_workspace_file

                try:
                    return write_workspace_file(ctx.deps, filename, content)
                except (OSError, ValueError) as exc:
                    raise ModelRetry(str(exc)) from exc

            async def publish_artifact(
                ctx: RunContext[AgentDeps], filename: str, title: str = ""
            ) -> dict:
                """Publish an existing text work file as an immutable downloadable deliverable."""
                from finagent.tools import publish_workspace_file

                try:
                    return publish_workspace_file(ctx.deps, filename, title)
                except (OSError, ValueError) as exc:
                    raise ModelRetry(str(exc)) from exc

            async def publish_report(
                ctx: RunContext[AgentDeps],
                title: str,
                sections: list[Claim],
                caveats: list[str] | None = None,
            ) -> dict:
                """Deliver a source-checked Markdown report with text and citation_ids per section.

                Include headings, narrative, tables, conclusions and limitations as sections.
                May call repeatedly to publish new report versions; never fabricate citations.
                """
                from finagent.tools import publish_research_report

                try:
                    return publish_research_report(ctx.deps, title, sections, caveats or [])
                except (ValueError, OSError) as exc:
                    self.validation_failure(str(exc))
                    return {
                        "status": "failed",
                        "error": str(exc),
                        "instruction": "Fix sections and retry publish_report; no file published.",
                    }

            for tool in (list_files, read_file, write_file, publish_artifact, publish_report):
                tool.__annotations__["ctx"] = RunContext[AgentDeps]
                agent.tool(self.trace_file_tool(tool, RunContext))

        @agent.output_validator
        async def validate_output(ctx: RunContext[AgentDeps], output: Answer) -> Answer:
            if ctx.partial_output:
                return output
            if self.committed_answer and not self.committed_answer.extends(output.claims):
                self.validation_failure("Published claim prefix changed", output)
                raise ModelRetry(
                    "Keep already published claims EXACTLY as the initial prefix; "
                    "only fix or append unpublished claims. Published claims: "
                    + Answer(claims=self.committed_answer.claims).model_dump_json()
                )
            if (
                self.tool_context.get("thread_id")
                and re.search(r"xlsx|excel|工作簿", question, re.IGNORECASE)
                and not any(a["kind"] == "table" for a in ctx.deps.generated_artifacts)
                and output.status == CompletionStatus.COMPLETE
            ):
                self.validation_failure("XLSX requested but no workbook delivered", output)
                raise ModelRetry("Call generate_workbook before claiming the XLSX is complete")
            if (
                self.tool_context.get("thread_id")
                and self.tool_context.get("requires_report")
                and output.status == CompletionStatus.COMPLETE
                and not any(a["data"].get("report") for a in ctx.deps.generated_artifacts)
            ):
                self.validation_failure(
                    "Report requested but no source-checked report delivered", output
                )
                raise ModelRetry(
                    "Call publish_report with cited sections before completing the report request"
                )
            try:
                return verify_answer_citations(
                    output, ctx.deps.allowed_citation_ids, ctx.deps.store
                )
            except CitationVerificationError as exc:
                self.validation_failure(str(exc), output)
                raise ModelRetry(str(exc)) from exc

        source_context = "\n\n".join(
            prompts.render(
                "source_template",
                citation_id=hit.citation.citation_id,
                ticker=hit.citation.source.ticker,
                form=hit.citation.source.form,
                locator=(
                    hit.citation.locator.model_dump_json() if hit.citation.value is None else ""
                ),
                text=hit.text,
            )
            for hit in hits
        )
        companies = ", ".join(
            f"{company.ticker} ({company.name}, CIK {company.cik})" for company in scope.companies
        )
        prompt = prompts.render(
            "user_template",
            companies=companies or "None selected; discover companies using research tools",
            forms=scope.forms,
            fiscal_years=scope.fiscal_years,
            sources=source_context,
            context=f"strict_scope={str(scope.strict).lower()}\n"
            + (extra_context or "None")
            + f"\nRequired output language: {'English' if scope.language == 'en' else 'Chinese'}",
            question=question,
        )
        deps = AgentDeps(
            store=self.store,
            allowed_citation_ids={hit.citation.citation_id for hit in hits},
            scope=scope,
            tool_context=self.tool_context,
            generated_artifacts=self.generated_artifacts,
            evidence={hit.citation.citation_id: hit.citation for hit in hits},
        )
        self.research_tools = None
        if self.settings.agentic_research:
            from finagent.research_tools import ResearchTools

            self.research_tools = ResearchTools(deps, self.settings, self.emit)
            self.research_tools.register(agent, RunContext, AgentDeps)
        return agent, prompt, deps
