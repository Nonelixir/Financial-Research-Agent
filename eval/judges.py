from __future__ import annotations

from decimal import Decimal


def numeric_match(actual: Decimal, expected: Decimal, rel_tol: Decimal = Decimal("0.001")) -> bool:
    if actual == expected:
        return True
    if expected == 0:
        return abs(actual) <= rel_tol
    return abs(actual - expected) / abs(expected) <= rel_tol


def citation_accession_score(actual: set[str], expected: set[str]) -> dict[str, float]:
    if not expected:
        return {"precision": 1.0 if not actual else 0.0, "recall": 1.0}
    intersection = actual & expected
    return {
        "precision": len(intersection) / len(actual) if actual else 0.0,
        "recall": len(intersection) / len(expected),
    }

