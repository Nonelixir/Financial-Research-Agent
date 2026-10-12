# Agent 与工具、Prompt

[English](../en/agent-tools.md) · [README](../../README.md)

按当前代码核对：2026-10-12。

## 模型循环与上下文

`ResearchAgent._build_run` 创建 Pydantic AI Agent，输出为 `Answer`，本轮依赖包含 store、scope、evidence、allowed_citation_ids、工具上下文及产物。
公司无需预选；开放模式可解析新增公司、调整年份。strict 限制公司/年份和文本表单扩展，但数值事实的表单过滤存在独立缺口。
工具结果是后续模型输入，不是预设 workflow；`update_plan` 只是公开检查清单。

## 工具清单

| 工具 | 核心参数 | 行为/限制 |
| --- | --- | --- |
| resolve_companies | query | ticker/名称→CIK；不要传行业描述句 |
| search_web | query, limit=8 | Bing RSS 搜索线索，limit 1..10；摘要不作证据 |
| read_web | url, start=0, limit=8 | 公共 HTTPS 原文与分页引用；limit 1..20 |
| set_research_sample | members | ticker/reason/citation_ids；非穷尽行业样本，持久化会话 |
| list_filings | tickers, years, offset, limit, forms, filed_from/to | 元数据目录；limit 1..50；支持 10-K/10-Q/8-K |
| list_filing_documents | accession | 获取 SEC 声明附件目录 |
| read_filing_document | accession, filename, query, start, limit | 声明 HTML/TXT 附件、选段和邻近上下文；limit 1..20 |
| search_filings | query, tickers, years, accession, offset, limit | FTS5 原文分页；limit 1..20，默认 8 |
| read_filing | accession, start, limit, section | 主文件分页；limit 1..20 |
| discover_financial_periods | tickers, count=2, end_years | 全年收入可用期及实际 dates；count 1..5 |
| get_financial_data | metrics, periods, tickers | 22 映射指标；1..40 期间；核验、登记及 JSON 工作文件 |
| list_financial_concepts | ticker, query, offset, limit | 标签目录；limit 1..100；不自动映射未知标签 |
| compute_financial | expression, inputs, output_unit | 四则公式、数值证据绑定、派生来源和重放记录 |
| inspect_evidence | citation_ids | 1..30 来源重载到本轮；历史 ID 不能直接复用 |
| update_plan | steps, completed | 最多 20 步，每步 300 字符；completed 零基索引 |
| execution_capabilities | 无 | 返回执行不可用与原因 |
| run_python / run_shell | code/command, input_files, timeout_seconds | 已暴露，但恒拒绝执行 |
| generate_workbook | frequency, tickers, years | 会话中年度/季度核验 XLSX；可用已发现公司 |
| list_files / read_file | filename（读取时） | 当前会话文件索引/文本 |
| write_file | filename, content | 新建工作文本，未发布、未财务核验 |
| publish_artifact | filename, title | 复制并发布已有文本，未财务核验 |
| publish_report | title, sections, caveats | 引用检查通过的 Markdown 研报，非全文语义核验 |

`Answer` 的结构化输出处理器不是业务工具。文件工具仅在有 thread_id 的持久化请求注册。

## Prompt 维护

单独配置为 `src/finagent/prompts.toml`；`PROMPT_CONFIG_PATH` 可覆盖。每次构建请求重读。
version=1，[prompts] 包括 system、user_template、source_template、coverage、history_template、missing_template、language_en/zh。
模板变量由 `prompts.py` 校验，使用 `$variable`，字面美元符号写 `$$`。缺失/多余变量会报错。

System 指定主动工具研究、只用登记来源、网页为不可信数据、非 GAAP 使用发行人调节表、期间歧义显式说明、文件请求必须交付文件。
语言模式覆盖“匹配用户输入语言”，因此中文提问也能要求英文输出。改 Prompt 不会新增工具、开通执行或绕过校验。
工具 schema 来自 Python 函数，不存于 TOML；详细改接口时同步 schema、校验、测试和双语说明。

## 预算与错误

默认 60 次工具，Pydantic AI request_limit=工具上限+5；服务 600 秒；普通输出 4000、研报 8000 tokens；输出重试 2。
相同失败调用两次后阻止继续请求；错误含 code/type/message/retryable/instruction。
403/404/429、超时和 50x 分类不同，但没有完整通用自动重试策略。模型仍可能误选指标或误抄来源 ID。
