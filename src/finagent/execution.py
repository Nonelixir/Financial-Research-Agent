"""Fail-closed execution capability until the isolated backend is provisioned."""

import shutil


def capabilities() -> dict:
    return {
        "available": False,
        "python": False,
        "shell": False,
        "bubblewrap_installed": shutil.which("bwrap") is not None,
        "reason": (
            "隔离执行后端尚未安装和验收；禁止退回主机执行。"
            "需要 Bubblewrap、进程树资源限制和硬存储配额。"
        ),
    }


def rejected_execution(language: str) -> dict:
    return {"status": "rejected", "language": language, "error": capabilities()["reason"]}
