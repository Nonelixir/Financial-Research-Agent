import asyncio
from hashlib import sha256
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from finagent import api, workspace
from finagent.filesystem import SessionFiles
from finagent.schemas import Company, ResearchScope
from finagent.storage import SQLiteStore
from finagent.tools import read_workspace_file, write_workspace_file


def test_paths_symlinks_isolation_and_limits(tmp_path):
    first = SessionFiles(tmp_path / "workspaces", "a" * 32, max_file=10, max_text=10)
    second = SessionFiles(tmp_path / "workspaces", "b" * 32)
    first.write("note.md", b"hello", text_only=True)
    assert first.read("note.md", text_only=True) == b"hello"
    with pytest.raises(FileExistsError):
        first.write("note.md", b"changed")
    with pytest.raises(FileNotFoundError):
        second.read("note.md")
    for path in ["../secret.txt", "/etc/passwd", "sub/file.md", ".env", "code.py", "x\\y.md"]:
        with pytest.raises(ValueError):
            first.write(path, b"bad")
    with pytest.raises(ValueError):
        first.write("large.txt", b"x" * 11)
    outside = tmp_path / "secret.txt"
    outside.write_text("secret")
    (tmp_path / "workspaces" / ("a" * 32) / "link.txt").symlink_to(outside)
    with pytest.raises(OSError):
        first.read("link.txt")
    import os

    os.link(outside, tmp_path / "workspaces" / ("a" * 32) / "hardlink.txt")
    with pytest.raises(ValueError):
        first.read("hardlink.txt")
    linked = tmp_path / "linked"
    linked.symlink_to(tmp_path / "workspaces", target_is_directory=True)
    with pytest.raises(ValueError):
        SessionFiles(linked, "a" * 32).list()
    limited = SessionFiles(tmp_path / "workspaces", "c" * 32, max_files=1)
    limited.write("one.md", b"1")
    with pytest.raises(ValueError, match="quota"):
        limited.write("two.md", b"2")


def test_file_tool_persistence_hash_and_no_overwrite(tmp_path, monkeypatch):
    store = SQLiteStore(tmp_path / "data.sqlite3")
    monkeypatch.setattr(api, "store", lambda: store)
    thread = asyncio.run(workspace.create_thread())
    deps = SimpleNamespace(
        tool_context={"thread_id": thread["id"]},
        generated_artifacts=[],
        allowed_citation_ids=set(),
        scope=ResearchScope(companies=[Company(cik="1", ticker="TEST", name="Test")]),
    )
    result = write_workspace_file(deps, "report.md", "# Requested report")
    assert result["published"] is False
    assert workspace.thread_data(thread["id"])["artifacts"] == []
    from finagent.tools import publish_workspace_file

    result = publish_workspace_file(deps, "report.md")
    artifact = workspace.thread_data(thread["id"])["artifacts"][0]
    assert artifact["file"]["sha256"] == sha256(b"# Requested report").hexdigest()
    assert read_workspace_file(deps, "report.md")["content"] == "# Requested report"
    with pytest.raises(FileExistsError):
        write_workspace_file(deps, "report.md", "overwrite")

    async def download():
        response = await workspace.download_artifact(result["artifact_id"])
        return b"".join([chunk async for chunk in response.body_iterator])

    assert asyncio.run(download()) == b"# Requested report"
    file = store.path.parent / "workspaces" / thread["id"] / artifact["file"]["relative_path"]
    file.write_text("tampered")
    with pytest.raises(HTTPException) as exc:
        asyncio.run(download())
    assert exc.value.status_code == 409
