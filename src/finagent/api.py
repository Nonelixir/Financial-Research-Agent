from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from datetime import date
from functools import lru_cache
from io import BytesIO
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from finagent.agent import ResearchAgent
from finagent.config import Settings, get_settings
from finagent.data.facts import METRIC_CONCEPTS, FactResolver, build_comparison
from finagent.data.sec import SecClient
from finagent.export.xlsx import comparison_workbook
from finagent.profile import ProfileService
from finagent.prompts import load_prompts
from finagent.retrieval.ingest import IngestionService
from finagent.retrieval.query import FilingRetriever
from finagent.schemas import (
    Answer,
    AskRequest,
    Citation,
    Company,
    ComparisonTable,
    ResearchScope,
    SearchHit,
    TableRequest,
    UserProfile,
)
from finagent.storage import SQLiteStore
from finagent.verify.numbers import verify_table
from finagent.workspace import router as workspace_router

STATIC_DIR = Path(__file__).parent / "static"


@lru_cache
def store() -> SQLiteStore:
    return SQLiteStore(get_settings().database_path)


@lru_cache
def sec_client() -> SecClient:
    return SecClient(get_settings(), store=store())


def ingestion_service() -> IngestionService:
    return IngestionService(store(), sec_client())


def retriever() -> FilingRetriever:
    return FilingRetriever(store())


def research_agent() -> ResearchAgent:
    return ResearchAgent(get_settings(), store())


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    store()
    yield
    await sec_client().close()


app = FastAPI(
    title="Financial Research Agent",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
app.include_router(workspace_router)
if (STATIC_DIR / "workspace" / "assets").exists():
    app.mount("/assets", StaticFiles(directory=STATIC_DIR / "workspace" / "assets"), name="assets")


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def index() -> FileResponse:
    workspace = STATIC_DIR / "workspace" / "index.html"
    return FileResponse(workspace if workspace.exists() else STATIC_DIR / "index.html")


@app.get("/api/health")
async def health(settings: Annotated[Settings, Depends(get_settings)]) -> dict[str, str]:
    return {"status": "ok", "service": settings.app_name}


@app.get("/api/companies/search", response_model=list[Company])
async def search_companies(
    q: Annotated[str, Query(min_length=1, max_length=100)],
) -> list[Company]:
    local = store().search_companies(q)
    if local:
        return local
    companies = await sec_client().search_companies(q)
    for company in companies:
        store().upsert_company(company)
    return companies


@app.post("/api/ingest")
async def ingest(scope: ResearchScope) -> dict[str, int]:
    try:
        return await ingestion_service().ingest_scope(scope)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"SEC ingestion failed: {exc}") from exc


@app.post("/api/ask", response_model=Answer)
async def ask(request: AskRequest) -> Answer:
    if get_settings().agentic_research and get_settings().llm_api_key and get_settings().llm_model:
        context = json.dumps(
            {"history": request.history, "saved_tables": request.table_context}, ensure_ascii=False
        )
        async with asyncio.timeout(get_settings().agent_timeout_seconds):
            return await research_agent().answer(request.question, request.scope, [], context)
    with suppress(Exception):
        await ingestion_service().ingest_scope(request.scope)
    # Cached evidence remains usable during a temporary SEC outage.
    hits, financial_context, _ = _prepare_answer_context(request)
    return await research_agent().answer(
        request.question,
        request.scope,
        hits,
        extra_context=financial_context,
    )


def _prepare_answer_context(
    request: AskRequest,
) -> tuple[list[SearchHit], str, ComparisonTable]:
    hits = retriever().search(
        request.question,
        request.scope,
        limit=get_settings().max_retrieval_hits,
    )
    periods = [f"{year}-FY" for year in request.scope.fiscal_years]
    resolver = FactResolver(store())
    if "10-Q" in request.scope.forms:
        for year in request.scope.fiscal_years:
            for quarter in ("Q1", "Q2", "Q3", "Q4"):
                period = f"{year}-{quarter}"
                if any(
                    resolver.resolve(company, "revenue", period) is not None
                    for company in request.scope.companies
                ):
                    periods.append(period)
    table_request = TableRequest(
        scope=request.scope,
        metrics=list(METRIC_CONCEPTS),
        periods=periods,
    )
    financial_table = _verified_table(table_request)
    context_tables = [financial_table]
    for saved in request.table_context:
        candidate = verify_table(ComparisonTable.model_validate(saved), store())
        if candidate.verified:
            context_tables.append(candidate)
    prompts = load_prompts(get_settings().prompt_config_path)
    financial_context: list[str] = [prompts.coverage]
    missing: list[str] = []
    existing_ids = {hit.citation.citation_id for hit in hits}
    for row in [row for candidate in context_tables for row in candidate.rows]:
        cell = row.cell
        if cell.value is None or cell.verification.status.value != "verified":
            missing.append(f"{row.company.ticker} {row.metric} {row.period}")
            continue
        ends = []
        for citation_id in cell.source_citation_ids:
            citation = store().get_citation(citation_id)
            if citation and hasattr(citation.locator, "end"):
                ends.append(str(citation.locator.end))
        financial_context.append(
            f"{row.company.ticker} {row.metric} {row.period}: {cell.value} {cell.unit}; "
            f"source_period_ends={ends}; "
            f"formula={cell.formula.expression if cell.formula else 'none'}; "
            f"citations={cell.source_citation_ids}"
        )
        for citation_id in cell.source_citation_ids:
            if citation_id in existing_ids:
                continue
            citation = store().get_citation(citation_id)
            if citation is None:
                continue
            hits.append(
                SearchHit(
                    citation=citation,
                    text=(
                        f"Verified XBRL input for {row.company.ticker} {row.metric} "
                        f"{row.period}: {citation.value.amount if citation.value else ''} "
                        f"{citation.value.unit if citation.value else ''}"
                    ),
                    score=100,
                )
            )
            existing_ids.add(citation_id)
    if missing:
        financial_context.append(prompts.render("missing_template", missing="; ".join(missing)))
    history = json.dumps(request.history, ensure_ascii=False)
    if request.history:
        financial_context.append(prompts.render("history_template", history=history))
    return hits, "\n".join(financial_context), financial_table


def _sse(event: str, payload: object) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False, default=str)}\n\n"


async def _ask_events(request: AskRequest) -> AsyncIterator[str]:
    queue: asyncio.Queue[str | None] = asyncio.Queue(maxsize=32)

    async def produce() -> None:
        # Keep the model's async context managers in one task across yields.
        # Advancing each snapshot in a new task breaks AnyIO cancel scopes.
        try:
            async for event in _research_events(request):
                await queue.put(event)
        except Exception as exc:
            await queue.put(
                _sse(
                    "error",
                    {
                        "message": "研究任务失败，请重试或缩小研究范围。",
                        "detail": str(exc)[:1000],
                    },
                )
            )
            await queue.put(
                _sse(
                    "done",
                    {
                        "status": "error",
                        "status_reason": "research_failed",
                    },
                )
            )
        finally:
            if not asyncio.current_task().cancelling():
                await queue.put(None)

    producer = asyncio.create_task(produce())
    try:
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=10)
            except TimeoutError:
                yield ": heartbeat\n\n"
                continue
            if event is None:
                break
            yield event
    finally:
        producer.cancel()
        with suppress(asyncio.CancelledError):
            await producer


async def _research_events(request: AskRequest) -> AsyncIterator[str]:
    if get_settings().agentic_research and get_settings().llm_api_key and get_settings().llm_model:
        async for event in _agentic_events(request):
            yield event
        return
    yield _sse(
        "status",
        {"phase": "request", "state": "complete", "message": "研究任务已建立"},
    )
    queue: asyncio.Queue[str] = asyncio.Queue()

    async def progress(message: str) -> None:
        await queue.put(message)

    yield _sse(
        "status",
        {"phase": "ingestion", "state": "active", "message": "正在同步 SEC 数据"},
    )
    task = asyncio.create_task(ingestion_service().ingest_scope(request.scope, progress))
    try:
        while not task.done() or not queue.empty():
            try:
                message = await asyncio.wait_for(queue.get(), timeout=0.2)
                yield _sse(
                    "status",
                    {"phase": "ingestion", "state": "active", "message": message},
                )
            except TimeoutError:
                continue
        totals = await task
        yield _sse(
            "status",
            {
                "phase": "ingestion",
                "state": "complete",
                "message": "SEC 数据与本地缓存已就绪",
                "detail": totals,
            },
        )
    except Exception as exc:
        yield _sse(
            "status",
            {
                "phase": "ingestion",
                "state": "warning",
                "message": "SEC 暂时不可用，继续使用本地缓存",
                "detail": str(exc)[:240],
            },
        )
    finally:
        if not task.done():
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

    yield _sse(
        "status",
        {"phase": "retrieval", "state": "active", "message": "正在检索财报证据"},
    )
    hits, financial_context, financial_table = _prepare_answer_context(request)
    narrative_count = sum(hit.citation.source.source_type == "filing_text" for hit in hits)
    xbrl_count = sum(hit.citation.source.source_type == "xbrl" for hit in hits)
    yield _sse(
        "sources",
        {
            "count": len(hits),
            "narrative_count": narrative_count,
            "xbrl_count": xbrl_count,
            "sources": [hit.citation.model_dump(mode="json") for hit in hits],
        },
    )
    yield _sse(
        "status",
        {
            "phase": "retrieval",
            "state": "complete",
            "message": f"已注册 {len(hits)} 条可核验来源",
        },
    )
    yield _sse(
        "status",
        {
            "phase": "verification",
            "state": "complete" if financial_table.verified else "warning",
            "message": (
                "确定性财务数据核验通过"
                if financial_table.verified
                else "部分财务数据缺失，回答将明确保留意见"
            ),
            "detail": {
                "rows": len(financial_table.rows),
                "verified_rows": sum(
                    row.cell.verification.status.value == "verified" for row in financial_table.rows
                ),
                "missing_rows": sum(row.cell.value is None for row in financial_table.rows),
                "warnings": financial_table.warnings,
            },
        },
    )
    yield _sse(
        "status",
        {"phase": "generation", "state": "active", "message": "模型正在组织带引用结论"},
    )
    final_answer: Answer | None = None
    research = research_agent()
    if request.workspace_thread_id:
        research.tool_context = {
            "thread_id": request.workspace_thread_id,
            "message_id": request.workspace_message_id,
        }
    emitted_artifacts = 0
    async for snapshot in research.stream_answer(
        request.question,
        request.scope,
        hits,
        extra_context=financial_context,
    ):
        for artifact in getattr(research, "generated_artifacts", [])[emitted_artifacts:]:
            yield _sse(
                "status",
                {
                    "phase": "workbook" if artifact["kind"] == "table" else "files",
                    "state": "complete",
                    "message": "XLSX 已生成并通过核验"
                    if artifact["kind"] == "table"
                    else "文件已保存到会话工作目录",
                },
            )
            yield _sse("artifact", artifact)
            emitted_artifacts += 1
        final_answer = snapshot
        if snapshot.status_reason in {"workbook_running", "files_running"}:
            yield _sse(
                "status",
                {
                    "phase": "workbook"
                    if snapshot.status_reason == "workbook_running"
                    else "files",
                    "state": "active",
                    "message": "正在生成并核验分 Sheet 财务工作簿"
                    if snapshot.status_reason == "workbook_running"
                    else "正在执行受限会话文件操作",
                },
            )
            continue
        if snapshot.status_reason == "validation_retry":
            yield _sse(
                "status",
                {
                    "phase": "generation",
                    "state": "active",
                    "message": "引用校验发现问题，模型正在修正回答",
                },
            )
            continue
        yield _sse("answer.snapshot", snapshot.model_dump(mode="json"))
    if final_answer is None:
        final_answer = Answer(
            claims=[],
            caveats=["模型未返回可验证输出。"],
            status="error",
            status_reason="empty_model_output",
        )
        yield _sse("answer.snapshot", final_answer.model_dump(mode="json"))
    generation_state = "complete" if final_answer.status.value == "complete" else "warning"
    yield _sse(
        "status",
        {
            "phase": "generation",
            "state": generation_state,
            "message": (
                "回答已完成并通过引用校验"
                if generation_state == "complete"
                else f"回答状态：{final_answer.status.value}"
            ),
            "detail": {"reason": final_answer.status_reason},
        },
    )
    yield _sse(
        "done",
        {
            "status": final_answer.status.value,
            "status_reason": final_answer.status_reason,
        },
    )


async def _agentic_events(request: AskRequest) -> AsyncIterator[str]:
    """No pre-ingestion or precomputed metrics: stream actual model-selected tools."""
    from finagent.localization import status_payload

    def localized_sse(event, payload):
        return _sse(event, status_payload(event, payload, request.scope.language))
    research = research_agent()
    research.tool_context = {
        "thread_id": request.workspace_thread_id,
        "message_id": request.workspace_message_id,
    }
    queue: asyncio.Queue[tuple[str, dict] | None] = asyncio.Queue(maxsize=512)

    def emit(event, payload):
        queue.put_nowait((event, payload))

    research.event_sink = emit
    saved_sample = None
    saved_artifacts = []
    if request.workspace_thread_id:
        from finagent.workspace import thread_data

        saved_thread = thread_data(request.workspace_thread_id)
        saved_sample = saved_thread.get("research_sample")
        saved_artifacts = [
            {
                "id": a["id"],
                "title": a["title"],
                "file": a.get("file"),
                "download_url": f"/api/artifacts/{a['id']}/download",
            }
            for a in saved_thread["artifacts"][-10:]
        ]
    context = json.dumps(
        {
            "history": request.history,
            "saved_tables_available": bool(request.table_context),
            "instruction": "Use list_files/read_file or data tools to inspect saved data; "
            "do not assume history is verified evidence.",
            "strict_scope": request.scope.strict,
            "previous_research_sample": saved_sample,
            "saved_artifacts": saved_artifacts,
            "current_date": date.today().isoformat(),
        },
        ensure_ascii=False,
    )

    async def produce():
        final = None
        emitted = 0
        stream = research.stream_answer(request.question, request.scope, [], extra_context=context)
        try:
            async with asyncio.timeout(get_settings().agent_timeout_seconds):
                async for snapshot in stream:
                    for artifact in research.generated_artifacts[emitted:]:
                        await queue.put(("artifact", artifact))
                        await queue.put(
                            (
                                "status",
                                {
                                    "phase": "workbook"
                                    if artifact["kind"] == "table"
                                    else "publish_artifact",
                                    "state": "complete",
                                    "message": "交付文件已创建并保存",
                                    "detail": artifact["file"],
                                },
                            )
                        )
                        emitted += 1
                    if snapshot.status_reason in {"workbook_running", "files_running"}:
                        await queue.put(
                            (
                                "status",
                                {
                                    "phase": "workbook"
                                    if snapshot.status_reason == "workbook_running"
                                    else "files",
                                    "state": "active",
                                    "message": "Agent 正在调用会话文件工具",
                                },
                            )
                        )
                        continue
                    if snapshot.status_reason == "validation_retry":
                        await queue.put(
                            (
                                "status",
                                {
                                    "phase": "generation",
                                    "state": "active",
                                    "message": "正在修正未发布的回答段落",
                                },
                            )
                        )
                        continue
                    final = snapshot
                    await queue.put(("answer.snapshot", snapshot.model_dump(mode="json")))
        except Exception as exc:
            final = Answer(
                claims=final.claims if final is not None else [],
                status="incomplete" if isinstance(exc, TimeoutError) else "error",
                status_reason="research_timeout"
                if isinstance(exc, TimeoutError)
                else str(exc)[:1000],
            )
            await queue.put(("answer.snapshot", final.model_dump(mode="json")))
        finally:
            await stream.aclose()
            if not asyncio.current_task().cancelling():
                for artifact in research.generated_artifacts[emitted:]:
                    await queue.put(("artifact", artifact))
                final = final or Answer(
                    claims=[], status="error", status_reason="empty_model_output"
                )
                await queue.put(
                    (
                        "status",
                        {
                            "phase": "generation",
                            "state": "complete" if final.status.value == "complete" else "warning",
                            "message": "研究结论已完成"
                            if final.status.value == "complete"
                            else "研究未完整完成",
                            "detail": {
                                "reason": final.status_reason,
                                "validation_errors": getattr(research, "validation_errors", []),
                            },
                        },
                    )
                )
                await queue.put(
                    ("done", {"status": final.status.value, "status_reason": final.status_reason})
                )
                await queue.put(None)

    yield localized_sse(
        "status",
        {
            "phase": "generation",
            "state": "active",
            "message": "Agent 已开始自主研究；数据由工具按需获取",
        },
    )
    task = asyncio.create_task(produce())
    try:
        while True:
            if task.done() and queue.empty():
                task.result()
                break
            try:
                event = await asyncio.wait_for(queue.get(), timeout=0.2)
            except TimeoutError:
                continue
            if event is None:
                break
            yield localized_sse(*event)
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


@app.get("/api/execution/capabilities")
async def execution_capabilities():
    from finagent.execution import capabilities

    return capabilities()


@app.post("/api/ask/stream")
async def ask_stream(request: AskRequest) -> StreamingResponse:
    return StreamingResponse(
        _ask_events(request),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-store",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


def _periods(request: TableRequest) -> list[str]:
    if request.periods:
        return request.periods
    return [f"{year}-FY" for year in request.scope.fiscal_years]


def _verified_table(request: TableRequest) -> ComparisonTable:
    table = build_comparison(store(), request.scope, request.metrics, _periods(request))
    return verify_table(table, store())


@app.post("/api/tables", response_model=ComparisonTable)
async def table(request: TableRequest) -> ComparisonTable:
    if not request.scope.companies:
        raise HTTPException(400, "对比表需要公司；可以先提问，由 Agent 发现研究对象。")
    with suppress(Exception):
        await ingestion_service().ingest_scope(request.scope)
    return _verified_table(request)


@app.post("/api/exports/xlsx")
async def export_xlsx(request: TableRequest) -> StreamingResponse:
    if not request.scope.companies:
        raise HTTPException(400, "导出对比表需要指定公司。")
    with suppress(Exception):
        await ingestion_service().ingest_scope(request.scope)
    table_value = _verified_table(request)
    if not table_value.verified:
        raise HTTPException(status_code=409, detail="Verification failed; export is blocked")
    output = comparison_workbook(table_value, store())
    return StreamingResponse(
        BytesIO(output),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="financial-comparison.xlsx"'},
    )


@app.get("/api/sources/{citation_id}", response_model=Citation)
async def source(citation_id: str) -> Citation:
    citation = store().get_citation(citation_id)
    if citation is None:
        raise HTTPException(status_code=404, detail="Citation not found")
    return citation


@app.get("/api/profile", response_model=UserProfile)
async def get_profile(profile_id: str = "default") -> UserProfile:
    return ProfileService(store()).get(profile_id)


@app.put("/api/profile", response_model=UserProfile)
async def put_profile(profile: UserProfile) -> UserProfile:
    return ProfileService(store()).update(profile)


@app.delete("/api/profile", status_code=204)
async def delete_profile(profile_id: str = "default") -> None:
    ProfileService(store()).clear(profile_id)


def run() -> None:
    import uvicorn

    uvicorn.run("finagent.api:app", host="127.0.0.1", port=8000, reload=False)
