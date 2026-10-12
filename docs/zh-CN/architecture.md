# 整体架构

[English](../en/architecture.md) · [README](../../README.md)

按当前代码核对：2026-10-12。

## 运行形态

单个 FastAPI/Uvicorn Python 服务提供 API、SSE、React 静态界面。生产不需要 Node 服务。
SQLite WAL/FTS5 保存结构化数据、引用、来源快照、会话和产物索引；本地会话目录保存文件。
没有 Redis、向量数据库、独立队列、Worker 或已验收的代码执行器。这是单用户研究原型，不是多租户金融终端。

## 组件责任

| 组件 | 代码 | 责任 |
| --- | --- | --- |
| 工作台 | `frontend/src/main.tsx` | 对话、Scope、计划、调用状态、来源和产物展示 |
| HTTP 与事件 | `src/finagent/api.py` | 路由、模型调度、事件队列、超时、静态资源 |
| 会话 | `src/finagent/workspace.py` | 历史、运行锁、消息编辑、文件索引和下载 |
| Agent | `src/finagent/agent.py` | 模型配置、工具注册、动态证据、结构化输出及重试 |
| 研究工具 | `src/finagent/research_tools.py` | 公司/行业发现、SEC/网页/指标读取、公式、计划 |
| 数据 | `src/finagent/data/`、`retrieval/` | SEC 接入、事实选择、文本分块、FTS5 |
| 校验 | `src/finagent/verify/`、`compute/evidence.py` | 引用检查、数字比较、源值回查及表达式重放 |
| 文件 | `filesystem.py`、`tools.py`、`export/xlsx.py` | 限目录读写、显式发布、核验工作簿 |

## 默认请求链路

1. 浏览器发送问题、可选 Scope 和语言；持久化入口写入用户消息与 running 占位。
2. 会话构建有限历史、历史来源 ID、既有产物摘要与研究样本。
3. Agent 按需选择工具，工具登记新证据到本轮集合；模型继续多轮研究，不强制预取所有指标。
4. 输出解析为 Answer/Claim，完整段落通过校验后才形成正文快照。
5. 文件显式生成/发布，与普通回答分离；SSE 返回状态、来源、计划、样本、产物、回答和终态。
6. 会话在流结束/取消时保存最后回答和事件。服务重启不恢复未结束的模型任务。

## 图与边界

[中文图](../diagrams/architecture.zh-CN.html) · [英文图](../diagrams/architecture.en.html)。
图中的发布校验包含回答与文件门槛，不代表所有下载都执行文本语义核验；SQLite 和目录访问关系是简化的。
模型调用与工具结果形成闭环，图的模型边仅概括该通信，不是单向固定步骤。

`AGENTIC_RESEARCH=false` 或模型未配置时仍有 legacy 路径：预取范围内资料、生成固定上下文、再解释或抽取降级。
所以“固定流程已彻底删除”不准确，默认入口与兼容路径必须分开理解。
