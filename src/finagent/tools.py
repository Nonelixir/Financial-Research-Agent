from typing import Literal
from uuid import uuid4

from finagent.data.facts import METRIC_CONCEPTS, FactResolver, build_comparison
from finagent.export.xlsx import comparison_workbook, quarterly_workbook
from finagent.verify.numbers import verify_table


def publish_research_report(deps, title, sections, caveats):
    from finagent.schemas import Answer
    from finagent.verify.citations import verify_answer_citations
    from finagent.workspace import save_artifact

    if not title.strip() or not sections:
        raise ValueError("Report requires a title and source-backed sections")
    answer = verify_answer_citations(
        Answer(claims=sections, caveats=caveats), deps.allowed_citation_ids, deps.store
    )
    ids = list(dict.fromkeys(i for c in sections for i in c.citation_ids))
    content = (
        "# "
        + title
        + "\n\n"
        + "\n\n".join(
            c.text + " " + " ".join(f"[{ids.index(i) + 1}](#source-{i})" for i in c.citation_ids)
            for c in sections
        )
    )
    english = deps.scope.language == "en"
    content += (
        "\n\n## "
        + ("Limitations and methodology" if english else "限制与口径")
        + "\n\n"
        + "\n\n".join(caveats)
    )
    content += "\n\n## " + ("Sources" if english else "来源") + "\n\n"
    for index, cid in enumerate(ids, 1):
        c = deps.store.get_citation(cid)
        location = c.locator.model_dump_json()
        content += f"<a id='source-{cid}'></a>\n{index}. [{cid}]({c.source.sec_url}) "
        content += f"{c.source.ticker} {c.source.form} · {location}\n\n"
    artifact = save_artifact(
        deps.tool_context["thread_id"],
        "document",
        title,
        {
            "text": content,
            "report": True,
            "answer": answer.model_dump(mode="json"),
            "citation_ids": ids,
            "verification": "citation_rules_checked_not_semantic_or_amount_audited",
        },
        deps.scope,
        deps.tool_context.get("message_id"),
        filename=f"report-{uuid4().hex[:12]}.md",
        content=content.encode(),
    )
    deps.generated_artifacts.append(artifact)
    return {
        "artifact_id": artifact["id"],
        "download_url": f"/api/artifacts/{artifact['id']}/download",
        "sections": len(sections),
        "sources": len(ids),
        "verification": artifact["data"]["verification"],
    }


def generate_financial_workbook(
    deps, frequency: Literal["quarterly", "annual"] = "quarterly", export_scope=None
):
    """Create a verified downloadable XLSX using the current research scope.

    Quarterly files have separate income, cash-flow and balance-sheet sheets,
    plus exact source lineage and missing-data notes. Never exports model numbers.
    """
    scope, store = export_scope or deps.scope, deps.store
    for artifact in deps.generated_artifacts:
        if artifact["data"].get("workbook_layout") == frequency and artifact["data"].get(
            "export_scope"
        ) == scope.model_dump(mode="json"):
            return {
                "artifact_id": artifact["id"],
                "verified": True,
                "download_url": f"/api/artifacts/{artifact['id']}/xlsx",
            }
    periods = []
    resolver = FactResolver(store)
    for year in sorted(scope.fiscal_years):
        candidates = (
            [f"{year}-FY"]
            if frequency == "annual"
            else [f"{year}-Q{quarter}" for quarter in range(1, 5)]
        )
        for period in candidates:
            if any(
                resolver.resolve(company, "revenue", period) is not None
                for company in scope.companies
            ):
                periods.append(period)
    table = verify_table(build_comparison(store, scope, list(METRIC_CONCEPTS), periods), store)
    if not table.verified:
        raise ValueError("No verified financial periods are available; workbook cannot be exported")
    builder = quarterly_workbook if frequency == "quarterly" else comparison_workbook
    binary = (
        builder(table, store, language=scope.language)
        if frequency == "quarterly"
        else builder(table, store)
    )
    data = table.model_dump(mode="json")
    data["workbook_layout"] = frequency
    data["export_scope"] = scope.model_dump(mode="json")
    title = "季度财务对比 · 分 Sheet XLSX" if frequency == "quarterly" else "年度财务对比 XLSX"
    if scope.language == "en":
        title = (
            "Quarterly financial comparison XLSX"
            if frequency == "quarterly"
            else "Annual financial comparison XLSX"
        )
    if not deps.tool_context.get("thread_id"):
        raise ValueError("Workbook generation requires a persisted conversation")
    from finagent.workspace import save_artifact

    artifact = save_artifact(
        deps.tool_context["thread_id"],
        "table",
        title,
        data,
        scope,
        deps.tool_context.get("message_id"),
        filename=f"financial-{frequency}-{uuid4().hex[:12]}.xlsx",
        content=binary,
    )
    deps.generated_artifacts.append(artifact)
    return {
        "artifact_id": artifact["id"],
        "title": title,
        "download_url": f"/api/artifacts/{artifact['id']}/xlsx",
        "periods": periods,
        "bytes": len(binary),
        "verified": True,
        "sheets": [
            "季度损益",
            "季度现金流",
            "季度资产负债表",
            "数据与计算口径",
            "Provenance",
            "说明",
        ]
        if frequency == "quarterly" and scope.language != "en"
        else [
            "Quarterly income",
            "Quarterly cash flow",
            "Quarterly balance sheet",
            "Data and calculations",
            "Provenance",
            "Notes",
        ]
        if frequency == "quarterly"
        else ["Data", "Provenance"],
        "warnings": table.warnings,
    }


def list_workspace_files(deps):
    from finagent.workspace import session_files

    return session_files(deps.tool_context["thread_id"]).list()


def read_workspace_file(deps, filename: str):
    from finagent.workspace import session_files

    return {
        "filename": filename,
        "content": session_files(deps.tool_context["thread_id"])
        .read(filename, text_only=True)
        .decode("utf-8"),
    }


def write_workspace_file(deps, filename: str, content: str):
    from finagent.workspace import session_files

    metadata = session_files(deps.tool_context["thread_id"]).write(
        filename,
        content.encode("utf-8"),
        text_only=True,
    )
    return {
        "filename": filename,
        "file": metadata,
        "published": False,
        "verification": "model_generated_not_financially_verified",
    }


def publish_workspace_file(deps, filename: str, title: str = ""):
    from uuid import uuid4

    from finagent.workspace import save_artifact, session_files

    files = session_files(deps.tool_context["thread_id"])
    content = files.read(filename, text_only=True)
    from pathlib import Path

    published_name = f"published-{uuid4().hex[:12]}{Path(filename).suffix}"
    artifact = save_artifact(
        deps.tool_context["thread_id"],
        "document",
        title or filename,
        {
            "text": content.decode("utf-8"),
            "verification": "model_generated_not_financially_verified",
            "source_work_file": filename,
            "citation_ids_available": sorted(deps.allowed_citation_ids),
        },
        deps.scope,
        deps.tool_context.get("message_id"),
        filename=published_name,
        content=content,
    )
    deps.generated_artifacts.append(artifact)
    return {
        "artifact_id": artifact["id"],
        "filename": published_name,
        "download_url": f"/api/artifacts/{artifact['id']}/download",
        "verification": "model_generated_not_financially_verified",
    }
