from __future__ import annotations

import json
from pathlib import Path
from statistics import mean


def summarize(path: Path) -> dict[str, float | int]:
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    return {
        "questions": len(rows),
        "accuracy": mean(row.get("correct", 0) for row in rows) if rows else 0,
        "citation_recall": mean(row.get("citation_recall", 0) for row in rows) if rows else 0,
        "failure_rate": mean(row.get("failed", 0) for row in rows) if rows else 0,
    }

