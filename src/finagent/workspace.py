from __future__ import annotations

import asyncio
import json
from contextlib import suppress
from hashlib import sha256
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from finagent.filesystem import SessionFiles
from finagent.schemas import AskRequest, ResearchScope, TableRequest

router = APIRouter(prefix="/api")
active_threads: set[str] = set()
SCHEMA = """
CREATE TABLE IF NOT EXISTS threads (
 id TEXT PRIMARY KEY, title TEXT NOT NULL, scope_json TEXT,
 created_at TEXT DEFAULT CURRENT_TIMESTAMP, updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS messages (
 id TEXT PRIMARY KEY, thread_id TEXT NOT NULL REFERENCES threads(id) ON DELETE CASCADE,
 role TEXT NOT NULL, content TEXT NOT NULL, answer_json TEXT,
 events_json TEXT NOT NULL DEFAULT '[]',
 status TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS artifacts (
 id TEXT PRIMARY KEY, thread_id TEXT NOT NULL REFERENCES threads(id) ON DELETE CASCADE,
 message_id TEXT REFERENCES messages(id) ON DELETE CASCADE,
 kind TEXT NOT NULL, title TEXT NOT NULL, data_json TEXT NOT NULL, scope_json TEXT NOT NULL,
 created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_messages_thread ON messages(thread_id);
CREATE INDEX IF NOT EXISTS idx_artifacts_thread ON artifacts(thread_id);
CREATE TABLE IF NOT EXISTS research_samples (
 id TEXT PRIMARY KEY, thread_id TEXT REFERENCES threads(id) ON DELETE CASCADE,
 data_json TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
"""


def db():
    from finagent.api import store

    value = store()
    with value.transaction() as connection:
        connection.executescript(SCHEMA)
        columns = {row[1] for row in connection.execute("PRAGMA table_info(artifacts)")}
        if "file_json" not in columns:
            connection.execute("ALTER TABLE artifacts ADD COLUMN file_json TEXT")
            # Files survive conversation editing; only explicit deletion removes them.
            connection.execute("UPDATE artifacts SET message_id=NULL")
    return value


def session_files(thread_id: str) -> SessionFiles:
    from finagent.config import get_settings

    settings = get_settings()
    root = settings.workspace_root or db().path.parent / "workspaces"
    return SessionFiles(
        root,
        thread_id,
        max_file=settings.workspace_max_file_bytes,
        max_total=settings.workspace_max_total_bytes,
        max_files=settings.workspace_max_files,
        max_text=settings.workspace_max_text_bytes,
    )


def thread_data(thread_id: str) -> dict:
    with db().transaction() as connection:
        row = connection.execute("SELECT * FROM threads WHERE id=?", (thread_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "会话不存在")
        result = dict(row)
        result["scope"] = json.loads(result.pop("scope_json") or "null")
        result["messages"] = []
        for item in connection.execute(
            "SELECT * FROM messages WHERE thread_id=? ORDER BY rowid", (thread_id,)
        ):
            message = dict(item)
            message["answer"] = json.loads(message.pop("answer_json") or "null")
            message["events"] = json.loads(message.pop("events_json"))
            # An interrupted process cannot leave messages apparently running.
            if message["status"] == "running" and thread_id not in active_threads:
                message["status"] = "incomplete"
            result["messages"].append(message)
        result["artifacts"] = []
        samples = connection.execute(
            "SELECT data_json FROM research_samples WHERE thread_id=? ORDER BY rowid DESC LIMIT 1",
            (thread_id,),
        ).fetchone()
        result["research_sample"] = json.loads(samples["data_json"]) if samples else None
        for item in connection.execute(
            "SELECT * FROM artifacts WHERE thread_id=? ORDER BY rowid", (thread_id,)
        ):
            artifact = dict(item)
            artifact["data"] = json.loads(artifact.pop("data_json"))
            artifact["scope"] = json.loads(artifact.pop("scope_json"))
            artifact["file"] = json.loads(artifact.pop("file_json") or "null")
            if artifact["file"]:
                result["artifacts"].append(artifact)
        return result


class ThreadPatch(BaseModel):
    title: str = Field(min_length=1, max_length=100)


class MessageRequest(BaseModel):
    question: str = Field(min_length=2, max_length=4000)
    scope: ResearchScope
    replace_from: str | None = None


@router.get("/threads")
async def list_threads():
    with db().transaction() as connection:
        return [
            dict(row)
            for row in connection.execute(
                "SELECT id,title,updated_at FROM threads ORDER BY updated_at DESC,rowid DESC"
            )
        ]


@router.post("/threads")
async def create_thread():
    thread_id = uuid4().hex
    with db().transaction() as connection:
        connection.execute("INSERT INTO threads(id,title) VALUES (?,?)", (thread_id, "新对话"))
    session_files(thread_id).list()
    return thread_data(thread_id)


@router.get("/threads/{thread_id}")
async def get_thread(thread_id: str):
    return thread_data(thread_id)


@router.patch("/threads/{thread_id}")
async def rename_thread(thread_id: str, request: ThreadPatch):
    thread_data(thread_id)
    with db().transaction() as connection:
        connection.execute("UPDATE threads SET title=? WHERE id=?", (request.title, thread_id))
    return thread_data(thread_id)


@router.delete("/threads/{thread_id}", status_code=204)
async def delete_thread(thread_id: str):
    if thread_id in active_threads:
        raise HTTPException(409, "请先停止当前生成")
    with db().transaction() as connection:
        connection.execute("DELETE FROM threads WHERE id=?", (thread_id,))
    # Keep files on disk as a recoverable archive; inaccessible through deleted session APIs.


@router.get("/threads/{thread_id}/files")
async def list_thread_files(thread_id: str):
    thread_data(thread_id)
    return session_files(thread_id).list()


def migrate_artifact_files() -> dict:
    """Preserve historical artifacts and IDs while materializing real files."""
    from finagent.export.xlsx import comparison_workbook, quarterly_workbook
    from finagent.schemas import ComparisonTable
    from finagent.verify.numbers import verify_table

    with db().transaction() as connection:
        rows = connection.execute("SELECT * FROM artifacts WHERE file_json IS NULL").fetchall()
    migrated, failed = 0, []
    for row in rows:
        try:
            data = json.loads(row["data_json"])
            if row["kind"] == "table":
                table = verify_table(ComparisonTable.model_validate(data), db())
                builder = (
                    quarterly_workbook
                    if data.get("workbook_layout") == "quarterly"
                    else comparison_workbook
                )
                content = builder(table, db())
                name, kind = f"financial-{row['id'][:12]}.xlsx", "table"
            else:
                text = "\n\n".join(item["text"] for item in data.get("claims", []))
                text += "\n\n" + "\n".join(data.get("caveats", []))
                content = text.encode("utf-8")
                name, kind = f"legacy-report-{row['id'][:12]}.md", "document"
                data = {
                    "text": text,
                    "legacy": True,
                    "verification": "model_generated_not_financially_verified",
                }
            metadata = session_files(row["thread_id"]).write(name, content)
            with db().transaction() as connection:
                connection.execute(
                    "UPDATE artifacts SET kind=?,data_json=?,file_json=? WHERE id=?",
                    (kind, json.dumps(data, ensure_ascii=False), json.dumps(metadata), row["id"]),
                )
            migrated += 1
        except (ValueError, OSError) as exc:
            failed.append({"artifact_id": row["id"], "error": str(exc)})
    return {"migrated": migrated, "failed": failed}


def save_artifact(
    thread_id, kind, title, data, scope, message_id=None, filename=None, content=None
):
    artifact_id = uuid4().hex
    if content is None:
        if kind != "table":
            raise ValueError("Artifacts require an actual file")
        from finagent.export.xlsx import comparison_workbook, quarterly_workbook
        from finagent.schemas import ComparisonTable
        from finagent.verify.numbers import verify_table

        table = verify_table(ComparisonTable.model_validate(data), db())
        builder = (
            quarterly_workbook
            if data.get("workbook_layout") == "quarterly"
            else comparison_workbook
        )
        content = builder(table, db())
        filename = f"financial-{artifact_id[:12]}.xlsx"
    metadata = session_files(thread_id).write(filename, content, text_only=kind == "document")
    metadata["origin_message_id"] = message_id
    with db().transaction() as connection:
        connection.execute(
            "INSERT INTO artifacts("
            "id,thread_id,message_id,kind,title,data_json,scope_json,file_json) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (
                artifact_id,
                thread_id,
                None,
                kind,
                title,
                json.dumps(data, ensure_ascii=False),
                scope.model_dump_json(),
                json.dumps(metadata, ensure_ascii=False),
            ),
        )
    return next(item for item in thread_data(thread_id)["artifacts"] if item["id"] == artifact_id)


@router.post("/threads/{thread_id}/artifacts/table")
async def create_table_artifact(thread_id: str, request: TableRequest):
    from finagent.api import table

    thread_data(thread_id)
    if thread_id in active_threads:
        raise HTTPException(409, "请等待当前研究完成")
    active_threads.add(thread_id)
    try:
        value = await table(request)
        with db().transaction() as connection:
            connection.execute(
                "UPDATE threads SET scope_json=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (request.scope.model_dump_json(), thread_id),
            )
        return save_artifact(
            thread_id,
            "table",
            "Financial comparison" if request.scope.language == "en" else "财务对比表",
            value.model_dump(mode="json"),
            request.scope,
        )
    finally:
        active_threads.discard(thread_id)


@router.get("/artifacts/{artifact_id}/xlsx")
async def export_artifact(artifact_id: str):
    return await download_artifact(artifact_id)


@router.get("/artifacts/{artifact_id}/download")
async def download_artifact(artifact_id: str):
    import mimetypes
    from io import BytesIO
    from urllib.parse import quote

    with db().transaction() as connection:
        row = connection.execute("SELECT * FROM artifacts WHERE id=?", (artifact_id,)).fetchone()
    if row is None or not row["file_json"]:
        raise HTTPException(404, "文件不存在")
    metadata = json.loads(row["file_json"])
    try:
        content = session_files(row["thread_id"]).read(metadata["relative_path"])
    except (OSError, ValueError) as exc:
        raise HTTPException(409, "产物文件缺失或不可读取") from exc
    if sha256(content).hexdigest() != metadata["sha256"]:
        raise HTTPException(409, "产物文件已变更，与登记版本不一致")
    if row["kind"] == "table":
        from finagent.schemas import ComparisonTable
        from finagent.verify.numbers import verify_table

        if not verify_table(ComparisonTable.model_validate_json(row["data_json"]), db()).verified:
            raise HTTPException(409, "财务数据核验失败")
    return StreamingResponse(
        BytesIO(content),
        media_type=mimetypes.guess_type(metadata["relative_path"])[0] or "application/octet-stream",
        headers={
            "Content-Disposition": "attachment; filename*=UTF-8''"
            + quote(metadata["relative_path"])
        },
    )


@router.post("/threads/{thread_id}/messages/stream")
async def send_message(thread_id: str, request: MessageRequest):
    from finagent.api import _ask_events, _sse

    previous = thread_data(thread_id)
    if thread_id in active_threads:
        raise HTTPException(409, "当前会话正在生成")
    active_threads.add(thread_id)
    user_id, assistant_id = uuid4().hex, uuid4().hex
    try:
        with db().transaction() as connection:
            if request.replace_from:
                target = connection.execute(
                    "SELECT rowid,role FROM messages WHERE id=? AND thread_id=?",
                    (request.replace_from, thread_id),
                ).fetchone()
                if target is None or target["role"] != "user":
                    raise HTTPException(400, "只能编辑当前会话的用户消息")
                connection.execute(
                    "DELETE FROM messages WHERE thread_id=? AND rowid>=?",
                    (thread_id, target["rowid"]),
                )
            history = [
                dict(item)
                for item in connection.execute(
                    "SELECT role,substr(content,1,8000) AS content FROM messages "
                    "WHERE thread_id=? AND status='complete' ORDER BY rowid",
                    (thread_id,),
                )
            ]
            evidence_history = connection.execute(
                "SELECT events_json FROM messages WHERE thread_id=? AND role='assistant' "
                "ORDER BY rowid DESC LIMIT 10",
                (thread_id,),
            ).fetchall()
            ids = list(
                dict.fromkeys(
                    citation_id
                    for row in evidence_history
                    for event in json.loads(row["events_json"])
                    if event["event"] == "sources"
                    for citation_id in event["data"].get("citation_ids", [])
                )
            )
            if ids:
                history.append(
                    {
                        "role": "assistant",
                        "content": "Historical citation IDs "
                        "(call inspect_evidence before reusing): " + json.dumps(ids[:300]),
                    }
                )
            connection.execute(
                "INSERT INTO messages(id,thread_id,role,content,status) "
                "VALUES (?,?, 'user',?,'complete')",
                (user_id, thread_id, request.question),
            )
            connection.execute(
                "INSERT INTO messages(id,thread_id,role,content,status) "
                "VALUES (?,?,'assistant','','running')",
                (assistant_id, thread_id),
            )
            title = request.question[:40] if previous["title"] == "新对话" else previous["title"]
            connection.execute(
                "UPDATE threads SET title=?,scope_json=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (title, request.scope.model_dump_json(), thread_id),
            )
    except BaseException:
        active_threads.discard(thread_id)
        raise

    artifacts = thread_data(thread_id)["artifacts"]
    table_context = [
        item["data"]
        for item in artifacts
        if item["kind"] == "table" and item["scope"] == request.scope.model_dump(mode="json")
    ]

    async def events():
        answer: dict | None = None
        log: list[dict] = []
        status = "incomplete"
        stream = _ask_events(
            AskRequest(
                question=request.question,
                scope=request.scope,
                history=history[-20:],
                table_context=table_context[-3:],
                workspace_thread_id=thread_id,
                workspace_message_id=assistant_id,
            )
        )
        try:
            yield _sse("message.created", {"user_id": user_id, "assistant_id": assistant_id})
            async for event in stream:
                if event.startswith(":"):
                    yield event
                    continue
                name = event.splitlines()[0].removeprefix("event: ")
                payload = json.loads(event.split("data: ", 1)[1])
                if name == "answer.snapshot":
                    answer = payload
                elif name == "done":
                    status = payload["status"]
                elif name in {"status", "sources", "error", "plan", "sample"}:
                    if name == "sources":
                        payload = {key: value for key, value in payload.items() if key != "sources"}
                    log.append({"event": name, "data": payload})
                yield event
        except asyncio.CancelledError:
            status = "incomplete"
            raise
        finally:
            with suppress(Exception):
                await stream.aclose()
            if answer and status != "complete":
                answer["status"] = status
                answer["status_reason"] = answer.get("status_reason") or "生成中断"
            content = "\n\n".join(
                filter(
                    None,
                    [
                        (answer or {}).get("message", ""),
                        *(item["text"] for item in (answer or {}).get("claims", [])),
                    ],
                )
            )
            with db().transaction() as connection:
                connection.execute(
                    "UPDATE messages SET content=?,answer_json=?,events_json=?,status=? WHERE id=?",
                    (
                        content,
                        json.dumps(answer, ensure_ascii=False),
                        json.dumps(log, ensure_ascii=False),
                        status,
                        assistant_id,
                    ),
                )
            active_threads.discard(thread_id)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-store",
            "X-Accel-Buffering": "no",
        },
    )
