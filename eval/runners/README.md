# 评测 Runner 入口

[English](README.en.md) · [项目 README](../../README.md)

当前方法、预算、正确性判定和限制统一维护于 [测试与能力](../../docs/zh-CN/testing-capabilities.md)。
源码 `financebench_pilot.py`，固定题集 `../dataset/financebench-pilot-10.json`，原始记录 `../results/`。
固定题集与原始记录仅本地保留、不公开；新克隆须先准备获准使用的题集才能执行下方命令。
输入 JSON 包含 `total`、`sha256`、`git_blob`、`seed` 和恰好 10 项 `rows`；每项需包含 `financebench_id`、`company`、`doc_name`、`question`。金标/evidence 仅评测侧使用。
题目/金标不修改，不向 Agent 注入金标；输出目录必须不存在。执行会创建真实会话并更新来源缓存。

```bash
uv run python eval/runners/financebench_pilot.py \
  --sample eval/dataset/financebench-pilot-10.json \
  --output eval/results/new-run --timeout 180 --concurrency 2
```

工作目录为项目根；先启动服务。runner 默认 http://127.0.0.1:8000 ，可用 --base-url 修改。
无独立评测报告 Markdown；元数据、JSONL、case JSON 与 review.json 保留作为原始验收数据。
`financebench-pilot-20261012-v2` 是服务尚未监听导致的无模型调用启动记录，已标注 invalid，不计成绩。

