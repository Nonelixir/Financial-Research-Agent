from __future__ import annotations

from decimal import Decimal

from finagent.compute.whitelist import cagr, growth, margin, share
from finagent.schemas import (
    Cell,
    ComparisonTable,
    VerificationResult,
    VerificationStatus,
)
from finagent.storage import SQLiteStore


def _citation_values(cell: Cell, store: SQLiteStore) -> list[Decimal] | None:
    citations = store.get_citations(cell.source_citation_ids)
    if len(citations) != len(cell.source_citation_ids):
        return None
    values: list[Decimal] = []
    for citation_id in cell.source_citation_ids:
        citation = citations[citation_id]
        if citation.value is None:
            return None
        stored_value = store.lookup_xbrl_value(citation)
        if stored_value is None or stored_value != citation.value.amount:
            return None
        values.append(stored_value)
    return values


def verify_cell(cell: Cell, store: SQLiteStore) -> Cell:
    if cell.value is None:
        return cell
    values = _citation_values(cell, store)
    if not values or cell.formula is None:
        cell.verification = VerificationResult(
            status=VerificationStatus.MISMATCH,
            message="Missing source values or formula",
        )
        return cell
    operation = cell.formula.operation
    expected: Decimal | None
    if operation == "direct":
        expected = values[0]
    elif operation == "subtract" and len(values) == 2:
        expected = values[0] - values[1]
    elif operation == "divide" and len(values) == 2:
        expected = margin(values[0], values[1])
    elif operation == "growth" and len(values) == 2:
        expected = growth(values[0], values[1])
    elif operation == "cagr" and len(values) == 3:
        expected = cagr(values[0], values[1], int(values[2]))
    elif operation == "share" and len(values) == 2:
        expected = share(values[0], values[1])
    else:
        expected = None
    if expected is None or expected != cell.value:
        cell.verification = VerificationResult(
            status=VerificationStatus.MISMATCH,
            message="Independent recomputation did not match",
            expected=expected,
            actual=cell.value,
        )
    else:
        cell.verification = VerificationResult(
            status=VerificationStatus.VERIFIED,
            message="Source identity and formula recomputation passed",
            expected=expected,
            actual=cell.value,
        )
    return cell


def verify_table(table: ComparisonTable, store: SQLiteStore) -> ComparisonTable:
    for row in table.rows:
        row.cell = verify_cell(row.cell, store)
    statuses = [row.cell.verification.status for row in table.rows]
    table.verified = (
        bool(statuses)
        and any(status == VerificationStatus.VERIFIED for status in statuses)
        and all(
            row.cell.verification.status
            in {VerificationStatus.VERIFIED, VerificationStatus.MISSING}
            for row in table.rows
        )
    )
    if not table.verified:
        table.warnings.append("Verifier found a mismatch; export is blocked")
    return table
