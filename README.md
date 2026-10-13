# 财报研究 Agent

[English](README.en.md)

轻量级、来源优先的金融研究工作台。模型自主多轮调用 SEC、公开网页、检索、财务数据和计算工具；公司与年份无需预选，strict 才限制范围。可交付带来源的 XLSX 和 Markdown，普通回答不是产物。

当前为单用户原型：FastAPI + Pydantic AI + SQLite WAL/FTS5 + 每会话文件目录，React 使用 assistant-ui 和 AI Elements。Python/shell 尚不可执行，财年语义、数字校验和重试恢复仍有已知缺陷。不能据此承诺无幻觉或超越 ChatGPT。

## 快速开始

Python≥3.12、uv；构建前端使用 Node 22+、npm。在本项目根目录：

```bash
uv sync --extra dev --extra agent
cp .env.example .env
npm --prefix frontend ci
npm --prefix frontend run build
uv run uvicorn finagent.api:app --host 127.0.0.1 --port 8000
```

已有 `.env` 时不要覆盖。至少设置真实 SEC 联系身份、模型端点、密钥和模型：

```env
SEC_IDENTITY=Financial Research Agent your-email@example.com
LLM_BASE_URL=https://provider.example/v1
LLM_API_KEY=your-server-side-key
LLM_MODEL=your-model
LLM_API_MODE=responses
```

兼容 `responses` / `chat_completions`，不要求 OpenRouter。密钥仅留服务端，不进仓库或浏览器。
未配置模型时有抽取/确定性表格降级，不提供自主深度研究。生产不需要 Node 服务，但需构建前端。
页面 http://127.0.0.1:8000/ ，接口 /api/docs，存活 /api/health；health 不证明模型与 SEC 就绪。
如需内网访问可改为 0.0.0.0；项目无内置鉴权，不应直接暴露公网。单进程运行，勿直接开多 worker。

## 当前文档目录

核对日期：2026-10-13。仅维护当前实现，每个模块独立中英文；不保留过渡方案、修复过程或评测报告 Markdown。
以下为统一入口，代码/机器 schema 与文档冲突时以代码为准，并同步修订双语版本。

| 模块 | 中文 | English |
| --- | --- | --- |
| 整体架构 | [阅读](docs/zh-CN/architecture.md) | [Architecture](docs/en/architecture.md) |
| Agent 与工具、Prompt | [阅读](docs/zh-CN/agent-tools.md) | [Agent, tools and prompts](docs/en/agent-tools.md) |
| SEC、网页与检索 | [阅读](docs/zh-CN/sources-retrieval.md) | [SEC, web and retrieval](docs/en/sources-retrieval.md) |
| 财务数据与计算 | [阅读](docs/zh-CN/financial-computation.md) | [Financial data and computation](docs/en/financial-computation.md) |
| Provenance 与校验 | [阅读](docs/zh-CN/provenance-validation.md) | [Provenance and validation](docs/en/provenance-validation.md) |
| 会话、存储与产物 | [阅读](docs/zh-CN/sessions-artifacts.md) | [Sessions, storage and artifacts](docs/en/sessions-artifacts.md) |
| 前端与语言交互 | [阅读](docs/zh-CN/frontend.md) | [Frontend and language interaction](docs/en/frontend.md) |
| API 契约 | [阅读](docs/zh-CN/api.md) | [API contracts](docs/en/api.md) |
| 配置、部署与运维 | [阅读](docs/zh-CN/operations.md) | [Configuration, deployment and operations](docs/en/operations.md) |
| 测试、能力与已知限制 | [阅读](docs/zh-CN/testing-capabilities.md) | [Testing, capabilities and known limits](docs/en/testing-capabilities.md) |
| 交互架构图 | [中文 HTML](docs/diagrams/architecture.zh-CN.html) | [English HTML](docs/diagrams/architecture.en.html) |
| 第三方组件 | [说明](frontend/THIRD_PARTY.md) | [Notice](frontend/THIRD_PARTY.en.md) |

架构图由 archify 重新生成，JSON 是图源；主题、缩放、搜索和导出均内置。维护方式及校验回执：
[中文](docs/zh-CN/diagrams.md) · [English](docs/en/diagrams.md)。

## 代码导航

```text
src/finagent/
  api.py                 HTTP、SSE 与默认/兼容入口
  agent.py               模型循环、工具注册、输出门槛
  research_tools.py      按需研究工具
  data/ retrieval/       SEC、事实选择、HTML 与 FTS5
  compute/ verify/       公式、原值回查、回答校验
  storage.py             SQLite 数据与来源缓存
  workspace.py           会话、历史、产物元数据
  filesystem.py tools.py 受限文件与显式交付
  export/                XLSX
  prompts.toml           可修改 Prompt 配置
frontend/                React 界面及第三方说明
docs/zh-CN/ docs/en/      当前模块文档
docs/diagrams/            当前架构图与图源
tests/ eval/              测试、自建示例与评测 runner
```

运行数据位于 `.data/`（可配置）；共享 SEC 缓存在 SQLite，会话文件在默认 `.data/workspaces/<thread_id>/`。
同级 `sec-filing-room` 是已废弃的旧项目，不是运行实现，也不属于这套文档。

## 验证与诚实边界

```bash
uv run pytest -q
uv run ruff check src tests eval/runners/financebench_pilot.py
npm --prefix frontend run build
```

当前 99 项测试通过，Ruff 通过。真实模型固定 FinanceBench 10 题，当前 verification-opt-v1 完整核心正确 9/10（90%），原版和旧 v4 为 6/10。
本轮一个迭代版本达到 80% 目标后停止；当前平均 36.448 秒、旧 v4 44.85 秒、原版 70.39 秒。
模型与预算、题目和金标不变；剩余错题为 Ulta 目标期间歧义。此为单次开发集回归，暖缓存和随机性影响结果，不代表未见题准确率。
原始 JSON、事件、来源与复核仅在本地 `eval/results/` 保留，不随公开仓库发布；FinanceBench 固定题集亦待再分发许可审查，不包含在本仓库。
公开 runner 需要另行准备符合其输入格式、获准使用的题集。上述分数是本地开发集结果，不是随仓库附带的独立可审计成绩。
无完整基线/ChatGPT 对照，未测全量基准和完整研报交付。
具体方法与限制见测试能力模块，测试通过不证明投资结论正确。

## 发布范围与许可

仓库包含有效源代码、测试、依赖锁文件、配置示例和当前中英文模块文档及架构图。
不包含密钥、真实 `.env`、数据库、会话与下载产物、日志、依赖目录、构建输出、独立产品调研和本地验收文件。
项目许可尚未确定；公开可见不等于已授予开源许可。第三方组件要求见对应说明。

## 文档维护约定

改工具/Prompt→Agent 文档；改来源/索引→检索文档；改指标/期间→财务文档；
改引用/核验→Provenance；改会话/目录→产物；改交互→前端；改路由→API；
改配置/部署→运维；改功能边界/测试→能力文档。架构变化同步两份图源并重新校验。
每次同时更新中英文、核对日期和 README，不再追加旧流程快照或过程性方案。
