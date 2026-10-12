import asyncio
import json

import pytest
from fastapi import HTTPException

from finagent import api, workspace
from finagent.schemas import Answer, Claim, Company, ResearchScope
from finagent.storage import SQLiteStore


def setup(tmp_path, monkeypatch):
    store = SQLiteStore(tmp_path / "workspace.sqlite3")
    monkeypatch.setattr(api, "store", lambda: store)
    scope = ResearchScope(companies=[Company(cik="1", ticker="TEST", name="Test")])
    return scope


def test_conversation_history_edit_and_artifact_cascade(tmp_path, monkeypatch):
    scope = setup(tmp_path, monkeypatch)
    requests = []

    async def fake_events(request):
        requests.append(request)
        yield api._sse("status", {"phase": "retrieval", "state": "complete"})
        answer = Answer(claims=[Claim(text="需求改善", citation_ids=["fixture"])])
        yield api._sse("answer.snapshot", answer.model_dump(mode="json"))
        yield api._sse("done", {"status": "complete"})

    monkeypatch.setattr(api, "_ask_events", fake_events)

    async def send(thread_id, question, replace=None):
        response = await workspace.send_message(
            thread_id,
            workspace.MessageRequest(
                question=question,
                scope=scope,
                replace_from=replace,
            ),
        )
        return [event async for event in response.body_iterator]

    async def run():
        thread = await workspace.create_thread()
        await send(thread["id"], "分析需求")
        first = workspace.thread_data(thread["id"])
        assert len(first["messages"]) == 2
        assert first["artifacts"] == []
        assert first["messages"][-1]["events"][0]["event"] == "status"
        await send(thread["id"], "继续分析")
        assert requests[-1].history == [
            {"role": "user", "content": "分析需求"},
            {"role": "assistant", "content": "需求改善"},
        ]
        await send(thread["id"], "重新分析", first["messages"][0]["id"])
        edited = workspace.thread_data(thread["id"])
        assert len(edited["messages"]) == 2
        assert edited["artifacts"] == []
        assert requests[-1].history == []
        await workspace.delete_thread(thread["id"])
        with pytest.raises(HTTPException):
            workspace.thread_data(thread["id"])

    asyncio.run(run())


def test_scope_filters_saved_tables_and_cancel_unlocks(tmp_path, monkeypatch):
    scope = setup(tmp_path, monkeypatch)
    requests = []

    async def fake_events(request):
        requests.append(request)
        yield api._sse(
            "answer.snapshot",
            {
                "claims": [],
                "caveats": [],
                "status": "incomplete",
            },
        )
        await asyncio.Event().wait()

    monkeypatch.setattr(api, "_ask_events", fake_events)

    async def run():
        thread = await workspace.create_thread()
        workspace.save_artifact(
            thread["id"],
            "table",
            "same scope",
            {"rows": []},
            scope,
            filename="fixture.xlsx",
            content=b"fixture",
        )
        other = scope.model_copy(update={"fiscal_years": [2020]})
        workspace.save_artifact(
            thread["id"],
            "table",
            "old scope",
            {"old": True},
            other,
            filename="old.xlsx",
            content=b"fixture",
        )
        response = await workspace.send_message(
            thread["id"],
            workspace.MessageRequest(
                question="分析刚才的表",
                scope=scope,
            ),
        )
        iterator = response.body_iterator
        await anext(iterator)
        await anext(iterator)
        assert requests[0].table_context == [{"rows": []}]
        with pytest.raises(HTTPException) as exc:
            await workspace.send_message(
                thread["id"],
                workspace.MessageRequest(
                    question="并发请求",
                    scope=scope,
                ),
            )
        assert exc.value.status_code == 409
        await iterator.aclose()
        assert thread["id"] not in workspace.active_threads
        saved = workspace.thread_data(thread["id"])
        assert saved["messages"][-1]["status"] == "incomplete"
        assert json.dumps(saved["messages"][-1]["answer"])

    asyncio.run(run())
