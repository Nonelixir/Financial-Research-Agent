"""Prepare the pinned public FinanceBench pilot locally, without bundling its data."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import random
from pathlib import Path

import httpx

GIT_BLOB = "4aef1d43a443474ba193f158f2baf70550ff528d"
DATA_SHA256 = "a5a2aa673e573e55675fc3c0f9aa38c1cf59d2abc91edb077534f71f10a71877"
SOURCE_URL = f"https://api.github.com/repos/patronus-ai/financebench/git/blobs/{GIT_BLOB}"


def prepare(output: Path) -> None:
    if output.exists():
        raise FileExistsError("Sample already exists; choose a new output path")
    response = httpx.get(SOURCE_URL, timeout=30)
    response.raise_for_status()
    blob = response.json()
    if blob.get("sha") != GIT_BLOB or blob.get("encoding") != "base64":
        raise ValueError("Unexpected upstream dataset metadata")
    content = base64.b64decode(blob["content"])
    if hashlib.sha256(content).hexdigest() != DATA_SHA256:
        raise ValueError("Upstream dataset checksum mismatch")
    rows = [json.loads(line) for line in content.splitlines() if line.strip()]
    if len(rows) != 150:
        raise ValueError("Pinned dataset must contain 150 questions")
    sample = {
        "total": len(rows),
        "sha256": DATA_SHA256,
        "git_blob": GIT_BLOB,
        "seed": 42,
        "rows": random.Random(42).sample(rows, 10),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as handle:
        json.dump(sample, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    print(f"Prepared 10 of 150 questions (seed=42): {output}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    prepare(arguments.output)
