"""Localize application messages only; never rewrite evidence or generated claims."""

import re


def status_payload(event: str, payload: dict, language: str) -> dict:
    if language != "en" or event not in {"status", "error"}:
        return payload
    message = payload.get("message", "")
    if not re.search(r"[\u3400-\u9fff]", message):
        return payload
    translations = {
        "Agent 已开始自主研究；数据由工具按需获取": (
            "Autonomous research started; tools will fetch evidence as needed."
        ),
        "回答或交付检查未通过，正在修正": (
            "Answer or delivery validation failed; revising unpublished content."
        ),
        "交付文件已创建并保存": "Deliverable created and saved.",
        "Agent 正在调用会话文件工具": "Agent is using session file tools.",
        "正在修正未发布的回答段落": "Revising unpublished answer sections.",
        "研究结论已完成": "Research findings completed.",
        "研究未完整完成": "Research is incomplete.",
    }
    phase, state = payload.get("phase", "research"), payload.get("state", "active")
    fallback = f"{phase}: " + {
        "active": "running",
        "complete": "completed",
        "warning": "failed or limited",
    }.get(state, state)
    # Original diagnostics remain in detail; do not hide failures by reporting success.
    result = {**payload, "message": translations.get(message, fallback)}
    if message not in translations:
        result["detail"] = {"original_message": message, "result": payload.get("detail")}
    return result
