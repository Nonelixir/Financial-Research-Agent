# Evaluation runner entry point

[中文](README.md) · [Project README](../../README.en.md)

Current methodology/budgets/scoring/limits live in [Testing and capabilities](../../docs/en/testing-capabilities.md).
Runner: `financebench_pilot.py`; fixed questions: `../dataset/financebench-pilot-10.json`; raw data: `../results/`.
The fixed sample and raw records are local-only and excluded from publication. Prepare a permitted sample before running the command below in a fresh clone.
Input JSON requires `total`, `sha256`, `git_blob`, `seed` and exactly ten `rows`; each row needs `financebench_id`, `company`, `doc_name` and `question`. Gold/evidence stays evaluator-side.
Do not modify questions/gold or send gold to the agent. Output directory must not exist. Runs create real threads/update caches.

```bash
uv run python eval/runners/financebench_pilot.py \
  --sample eval/dataset/financebench-pilot-10.json \
  --output eval/results/new-run --timeout 180 --concurrency 2
```

Run from the repository root after starting the service. Default base URL is http://127.0.0.1:8000 ; override with --base-url.
No historical evaluation-report Markdown is retained; metadata, JSONL, case JSON and review.json remain as raw acceptance evidence.
`financebench-pilot-20261012-v2` is invalid startup evidence with no model calls, excluded from scores.
