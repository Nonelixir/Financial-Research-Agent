# 会话、存储与产物

[English](../en/sessions-artifacts.md) · [README](../../README.md)

按当前代码核对：2026-10-14。

## 持久化与上下文

SQLite 核心：companies、filings、facts、chunks/chunks_fts、citations、profiles、ingestion_runs、source_cache/source_snapshots。
会话 schema：threads、messages、artifacts；研究工具按需创建 web_pages、research_samples；计算按需创建 computations。
SQLite WAL、事务与进程内锁，不是分布式数据库。运行中会话锁 active_threads 仅当前进程共享，因此不适合直接启动多 worker。

会话消息存 role/content/answer_json/events_json/status；Scope 保存在 thread。
提交下一轮只使用最后 20 条 complete 历史，单条最多 8000 字符；历史来源提示来自最近 10 条 assistant 事件、最多 300 ID，复用需 inspect_evidence。
最多 3 个完全匹配 Scope 的历史 table_context 进入请求；默认 Agent 不直接全文预注入表格，而给可用标记、最近 10 个产物摘要、保存样本，要求工具读取。
这不是无限上下文，也不自动学习 profile；profile API 目前不等于长期记忆注入。

## 编辑、取消与重启

同会话并发发送返回 409。编辑 replace_from 必须指向同会话用户消息，删除该点之后消息，再生成；文件产物仍保留。
SSE 结束/取消时保存最后已核验回答、事件与状态。断流不代表自动继续，未结束任务不跨进程恢复。
读取会话时发现 running 但不在 active_threads，则展示 incomplete。
删除会话不允许正在生成；删除数据库会话与关联记录，但磁盘文件保留作可恢复归档，已删除会话 API 不再访问。

## 文件系统边界

默认 `DATABASE_PATH` 所在目录的 `workspaces/<thread_id>/`，可配置 WORKSPACE_ROOT。
线程 ID 为 32 位小写 hex；平面文件名≤200 字节，禁止绝对/子目录/隐藏/分隔符/NUL/控制字符。
模型文本工具仅 .md/.txt/.csv/.json；文件层另接受 .xlsx/.png/.jpg/.webp，不代表 Agent 能生成所有格式。
目录和文件使用 dir_fd/O_NOFOLLOW，创建 O_EXCL 不覆盖，写权限 0600、目录 0700；读取要求普通文件、单链接，禁止软链接绕过。

默认每文件 10 MiB、每会话 100 MiB、200 文件、文本读写 256 KiB。配额是应用级检查，不是 OS 硬配额。
无目录、覆盖、任意删除工具；所有 Agent 工作文件和发布文件在该会话目录，SEC 共享缓存则在 SQLite 而不是复制全量到目录。
受限文件工具不是 Python/shell 沙盒。执行后端不可用，禁止退回宿主机。

## Artifacts 定义与发布

Artifact 是真实、登记、有下载路径的交付文件；普通回复不算。工作文件→显式发布→artifact metadata + file hash。
write_file 不发布，get_financial_data 可生成 JSON 工作文件但不自动 artifact。
publish_artifact 新建 published- 文件，标为 model_generated_not_financially_verified。
publish_report 生成带引用与来源定位的 Markdown，登记 report=true；generate_workbook 由确定性数据构建核验 XLSX。
季度分损益/现金流/资产负债表/数据与计算/Provenance/说明；年度 Data/Provenance。
表格 period 先看至少一公司 revenue 可用，不保证每公司每指标都有值，缺失保留。

## 下载与维护

下载按 artifact_id 查 metadata，读取文件、核对 SHA256，表格再验证原数据；缺失/变更返回 409。
通用文本发布没有财务核验。工作文件不自动成为下载产物，页面只展示有 file metadata 的产物。
备份必须同时包含 SQLite 一致快照和整个工作目录；删除会话不等于清理磁盘，归档/清理需运维显式处理。

会话回答的普通对话 message 也进入 messages.content；它不创建研究来源或交付文件。

## 报告交付与展示

综合分析完成前要求本轮保存 Markdown 报告和核验 XLSX。发布报告与回答遵循相同数字展示及绑定规则：默认两位小数、最多四位，USD 采用易读的金额比例。展示函数不对保存的来源值或工作簿数据做舍入。工作簿保留支持的核验指标和 provenance，但可能不含原文中的全部数字或报告的全部派生比率。
