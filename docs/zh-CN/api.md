# API 契约

[English](../en/api.md) · [README](../../README.md)

按当前代码核对：2026-10-13。

## 基础结构

入口 `api.py` + `workspace.py`；Swagger `/api/docs`，OpenAPI `/api/openapi.json` 为参数约束的权威机器定义。
当前没有鉴权/租户隔离/授权下载；ID 不等于权限。仅受信网络/单用户，不应直接暴露公网。
Scope 包含 language(zh/en)、companies[{cik,ticker,name,aliases}]、strict、forms、fiscal_years、restatement_policy。
默认 companies/years 空、strict=false、forms 10-K/10-Q、latest_restated；schema 公司最多 30。
Settings.max_companies 并非所有自主工具的统一公司上限，不能承诺每层严格限制为 3 家。

## 路由

| 方法/路径 | 输入/行为 |
| --- | --- |
| GET /api/health | 存活响应；不探测模型、SEC 或数据库全部能力 |
| GET /api/companies/search?q= | 本地优先，空则 SEC；query 1..100 字符 |
| POST /api/ingest | Scope；显式同步缓存，不是正常问答必须步骤 |
| POST /api/ask | AskRequest；同步 Answer，非会话文件工具不可用 |
| POST /api/ask/stream | AskRequest；SSE；不是持久化会话默认入口 |
| GET /api/execution/capabilities | execution.available=false |
| POST /api/tables | TableRequest；确定性 ComparisonTable |
| POST /api/exports/xlsx | TableRequest；直接下载，不登记会话 artifact |
| GET /api/sources/{citation_id} | 已登记 Citation；404 缺失 |
| GET/PUT/DELETE /api/profile | profile_id/default 与 UserProfile；未自动长期记忆注入 |
| GET/POST /api/threads | 列表/新建 |
| GET/PATCH/DELETE /api/threads/{id} | 获取/改标题/删除；活动会话删除 409 |
| GET /api/threads/{id}/files | 会话工作文件索引 |
| POST /api/threads/{id}/artifacts/table | TableRequest；保存会话表格 artifact |
| POST /api/threads/{id}/messages/stream | question、scope、可选 replace_from；持久化 SSE |
| GET /api/artifacts/{id}/download | 实际文件与 hash 检查；表格追加数据核验 |
| GET /api/artifacts/{id}/xlsx | 兼容下载别名，不意味着任意 artifact 都 XLSX |

会话 question 2..4000 字符，title 1..100；严格参数以 OpenAPI/schema 为准。
TableRequest 包括 scope、metrics、periods；frequency 是 Agent 工作簿工具参数，不是该请求字段。建议查 Swagger，不把工具名与 HTTP API 混同。

## 持久化请求例

```json
{
  "question": "Analyze AAOI's last two complete fiscal years.",
  "scope": {
    "language": "en", "companies": [], "fiscal_years": [],
    "strict": false, "forms": ["10-K", "10-Q"],
    "restatement_policy": "as_reported"
  }
}
```

先 POST /api/threads，取 id，再 POST /api/threads/{id}/messages/stream。
前端从 abort 取消 SSE，无独立持久化后台任务取消接口。

## 事件与状态

SSE 格式 event: name / data: JSON，连续事件含 message.created、status、sources、plan、sample、artifact、answer.snapshot、error、done；兼容路径还可能有其他事件。
answer.snapshot 含 claims[{text,citation_ids,numeric_bindings?}]、caveats、status、status_reason。
status 工具事件含 phase/state/tool_call_id/message/detail；前端不能按相同 phase 合并不同调用。
done 是终态运输标志，complete 仅表示通过当前门槛，不等于正确、全部数据完整或全部断言有证据。
错误/取消应保留 partial/incomplete，不把空回答当成功；来源查询 200 也不是语义评分。

## 常见失败

400/422 请求格式；404 不存在；409 活跃会话或文件变更/表格核验；502 显式 SEC ingest 失败。
SSE 内工具失败不一定用 HTTP 错误码，应读取 status.detail/error 与最终 status_reason。
中途断流不支持 event-id 自动重放/恢复，调用方需要重新读取会话状态。

普通对话使用 Answer.message（默认空字符串），claims=[]；研究结论仍使用带引用的 claims。纯问候直接回复，不调用模型或研究工具。
