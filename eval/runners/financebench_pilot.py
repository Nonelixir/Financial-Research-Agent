"""Run a seeded, unmodified FinanceBench sample against the actual HTTP agent.

Gold answers/evidence are saved separately and never passed to the agent.
Runtime output files are benchmark results, not application artifacts.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx

from finagent.config import Settings
from finagent.prompts import DEFAULT_PROMPT_PATH


async def run(args):
    async with httpx.AsyncClient(base_url=args.base_url, timeout=10) as readiness:
        response = await readiness.get("/api/health")
        response.raise_for_status()
    payload = json.loads(args.sample.read_text())
    rows = payload["rows"]
    if len(rows) != 10:
        raise ValueError("Pilot requires exactly ten fixed questions")
    args.output.mkdir(parents=True, exist_ok=False)
    settings = Settings()
    metadata = {
        "started_at": datetime.now(UTC).isoformat(),
        "dataset": "FinanceBench open-source sample",
        "source_url": "https://github.com/patronus-ai/financebench",
        "dataset_git_blob": payload["git_blob"],
        "dataset_sha256": payload["sha256"],
        "selection": f"random.Random({payload['seed']}).sample(original_order, 10)",
        "dataset_size": payload["total"],
        "questions": len(rows),
        "base_url": args.base_url,
        "language": "en",
        "restatement_policy": "as_reported",
        "model": settings.llm_model,
        "api_mode": settings.llm_api_mode,
        "prompt_sha256": hashlib.sha256(DEFAULT_PROMPT_PATH.read_bytes()).hexdigest(),
        "max_output_tokens": settings.llm_max_output_tokens,
        "max_tool_calls": settings.agent_max_tool_calls,
        "model_retries": settings.llm_max_retries,
        "server_timeout_seconds": settings.agent_timeout_seconds,
        "pilot_wall_time_limit_seconds": args.timeout,
        "concurrency": args.concurrency,
        "cache": "existing mixed/warm; not controlled",
        "corpus_cutoff": "Live SEC/public-web sources; requested historical document specified",
        "gold_leakage": "Only original question and doc_name sent; no answer or gold evidence",
        "baseline": "None in this pilot",
        "token_usage": None,
        "cost": None,
        "usage_note": "Current HTTP event contract does not expose model usage or pricing",
    }
    (args.output / "metadata.json").write_text(json.dumps(metadata, indent=2))
    (args.output / "gold.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    semaphore = asyncio.Semaphore(args.concurrency)
    results = []

    async def one(index, item):
        async with semaphore:
            start = time.monotonic()
            result = {
                "index": index + 1,
                "id": item["financebench_id"],
                "company": item["company"],
                "doc_name": item["doc_name"],
                "question": item["question"],
                "events": [],
                "answer": None,
            }
            print(f"START {index + 1}/10 {item['company']} {item['financebench_id']}", flush=True)
            async with httpx.AsyncClient(base_url=args.base_url, timeout=30) as client:
                try:
                    response = await client.post("/api/threads")
                    response.raise_for_status()
                    tid = response.json()["id"]
                    result["thread_id"] = tid
                    body = {
                        "question": item["question"]
                        + "\nTarget source document: "
                        + item["doc_name"]
                        + ". Use the historical filing requested, not latest-year data.",
                        "scope": {
                            "companies": [],
                            "fiscal_years": [],
                            "forms": ["10-K", "10-Q"],
                            "strict": False,
                            "language": "en",
                            "restatement_policy": "as_reported",
                        },
                    }
                    result["request"] = body
                    event = ""
                    async with asyncio.timeout(args.timeout):
                        async with client.stream(
                            "POST", f"/api/threads/{tid}/messages/stream", json=body, timeout=None
                        ) as stream:
                            stream.raise_for_status()
                            async for line in stream.aiter_lines():
                                if line.startswith("event:"):
                                    event = line[6:].strip()
                                elif line.startswith("data:"):
                                    data = json.loads(line[5:])
                                    result["events"].append(
                                        {
                                            "event": event,
                                            "data": data,
                                            "elapsed": round(time.monotonic() - start, 3),
                                        }
                                    )
                                    if event == "answer.snapshot":
                                        result["answer"] = data
                                    elif event == "done":
                                        result["terminal"] = data
                                    elif event == "status" and data.get("state") == "warning":
                                        print(
                                            f"WARN {index + 1}: {data.get('message', '')[:160]}",
                                            flush=True,
                                        )
                except Exception as exc:
                    result["client_error"] = type(exc).__name__ + ": " + str(exc)
                result["latency_seconds"] = round(time.monotonic() - start, 3)
                # Fetch exact registered citations for independent review; never feed back gold.
                citations = {}
                for claim in (result.get("answer") or {}).get("claims", []):
                    for cid in claim["citation_ids"]:
                        if cid in citations:
                            continue
                        try:
                            response = await client.get("/api/sources/" + cid)
                            response.raise_for_status()
                            citations[cid] = response.json()
                        except Exception as exc:
                            citations[cid] = {"fetch_error": str(exc)}
                result["citations"] = citations
                if result.get("thread_id"):
                    try:
                        response = await client.get("/api/threads/" + result["thread_id"])
                        response.raise_for_status()
                        result["persisted_thread"] = response.json()
                    except Exception as exc:
                        result["persistence_error"] = str(exc)
            (args.output / f"case-{index + 1:02d}.json").write_text(json.dumps(result, indent=2))
            results.append(result)
            print(
                f"END {index + 1}/10 status={result.get('terminal')} "
                f"seconds={result['latency_seconds']} error={result.get('client_error')}",
                flush=True,
            )

    await asyncio.gather(*(one(i, item) for i, item in enumerate(rows)))
    (args.output / "results.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in sorted(results, key=lambda r: r["index"]))
    )
    print("RESULTS " + str(args.output), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--concurrency", type=int, default=2)
    asyncio.run(run(parser.parse_args()))
