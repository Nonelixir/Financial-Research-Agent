# 配置、部署与运维

[English](../en/operations.md) · [README](../../README.md)

按当前代码核对：2026-10-12。

## 安装与启动

Python≥3.12、uv；前端构建使用 Node 22+、npm（跟随 package-lock）。在项目根目录：

```bash
uv sync --extra dev --extra agent
cp .env.example .env
npm --prefix frontend ci
npm --prefix frontend run build
uv run uvicorn finagent.api:app --host 127.0.0.1 --port 8000
```

已有 .env 不要复制覆盖。生产无需 Node，但必须构建前端；没构建会回退旧静态页面。
/api/health 是存活检查，/api/docs 是接口；配置模型后还需一次实际研究验证服务商协议。
不要把“启动成功”当作 SEC/模型/XLSX 都可用。仅受信内网部署，远程访问可绑定 0.0.0.0 并加网关鉴权/TLS。
本项目未内建鉴权，单进程单 worker 运行；多 worker 的 active_threads 不共享。

## 配置表

`config.py` 的 Settings 从环境/.env 读取（环境优先），get_settings 缓存；修改需重启。
Prompt TOML 每次请求重读，不同于环境配置。

| 配置 | 默认 | 作用 |
| --- | --- | --- |
| DATABASE_PATH | .data/finagent.sqlite3 | SQLite 与默认工作目录基准 |
| SEC_IDENTITY | Financial Research Agent analyst@example.com | 应改为真实联系身份 |
| SEC_REQUESTS_PER_SECOND | 5 | 每 client 限速，0.5..10 |
| REQUEST_TIMEOUT_SECONDS | 30 | SEC HTTP 超时，5..120 |
| LLM_BASE_URL | https://api.openai.com/v1 | 兼容提供商端点，不要求 OpenRouter |
| LLM_API_KEY / LLM_MODEL | 空 | 服务端密钥/模型；不回传前端 |
| LLM_API_MODE | responses | responses 或 chat_completions |
| LLM_MAX_OUTPUT_TOKENS | 4000 | 普通输出 256..16000 |
| LLM_REPORT_OUTPUT_TOKENS | 8000 | 被识别的研报请求预算 256..16000 |
| LLM_MAX_RETRIES | 2 | 输出重试 0..3 |
| AGENTIC_RESEARCH | true | 默认自主模式，false 保留 legacy |
| AGENT_MAX_TOOL_CALLS | 60 | 1..200，模型请求上限另为 +5 |
| AGENT_TIMEOUT_SECONDS | 600 | 10..1800，总研究时间 |
| WEB_MAX_BYTES | 2097152 | 公共网页上限，1024..10485760 |
| PROMPT_CONFIG_PATH | 默认 prompts.toml | 可指定独立模板 |
| MAX_RETRIEVAL_HITS | 12 | legacy 总检索 limit，3..30；不是 Agent 全轮上限 |
| MAX_COMPANIES | 3 | 历史配置，1..8；不是所有自主工具统一强制上限 |
| WORKSPACE_ROOT | DB 旁 workspaces | 会话根目录 |
| WORKSPACE_MAX_FILE_BYTES | 10485760 | 单文件 10 MiB |
| WORKSPACE_MAX_TOTAL_BYTES | 104857600 | 会话 100 MiB |
| WORKSPACE_MAX_FILES | 200 | 文件数 |
| WORKSPACE_MAX_TEXT_BYTES | 262144 | 文本 256 KiB |
| APP_NAME / ENVIRONMENT | Financial Research Agent / development | 元信息，不启用安全隔离 |

提供商必须支持选定协议、流式、工具调用及结构化输出。模型字符串不证明服务商实际底层模型身份。
密钥只写 .env/受保护环境；禁止进仓库、文档、请求日志或浏览器。示例不使用真实 key。
LLM_BASE_URL 由管理员信任配置，若使用 HTTP 端点无传输加密；正式环境使用 HTTPS。

## 故障检查

- 页面打不开：进程/端口、/api/health、反向代理、前端 assets 和首次构建后重启。
- 模型 4xx：API_MODE、端点、模型权限、schema/tool 支持；不自动换供应商。
- SEC 403/429/50x：身份、速率、原站限制、缓存警告；不等于财报数据不存在。
- 回答 incomplete：检查 generation/status_reason 与工具 detail，分别判断检索、数值、文件或重试失败。
- 文件 409：文件缺失/篡改/源值核验；不要手工改已登记产物。
- 线程看似 running：重启后加载会话会显示 incomplete，不存在自动恢复任务。

## 备份、安全与清理

用 SQLite online backup 或停服务后的一致备份；直接复制正在写的 sqlite 文件可能遗漏 WAL。
工作目录一并备份，恢复两者后核对产物 hash。运行数据、.env 和日志不提交。
文件配额和网络防护不构成整个应用安全沙盒；无容器执行、全局硬磁盘/CPU 限制、鉴权或完整审计管理。
线程删除保留磁盘文件，缓存/快照无自动保留策略。清理应显式检查依赖，不能清数据库引用仍存在的文件。
