# 测试、能力与已知限制

[English](../en/testing-capabilities.md) · [README](../../README.md)

按当前代码核对：2026-10-13。

## 当前能力分级

| 能力 | 当前状态 |
| --- | --- |
| 不预选公司，主动多轮检索 | 已实现；行业搜索实验性，样本非全行业 |
| SEC 历史目录、8-K、声明附件 | 已实现 HTML/TXT；网络/目录缺失仍影响 |
| 年度/季度 22 指标 | 部分支持，缺失保留；不等于全部指标 |
| 注册公式与输入血缘 | 已实现有界四则与重放；不验证方法语义 |
| 原文/数值引用、句末按钮 | 已实现；不是逐句/逐数字全面语义证明 |
| 会话持久化、有限历史 | 已实现；无自动任务恢复/无限记忆 |
| XLSX 和 Markdown 真实产物 | 已实现，核验等级不同；交付仍可能失败 |
| 中英文 UI/要求语言 | 已实现后续请求；历史/原文不翻译 |
| Python / shell | 未实现，工具恒拒绝 |
| PDF/OCR、向量 RAG、全球可比财务 | 未实现 |
| 鉴权、多租户、生产执行隔离 | 未实现 |

## 必须保留的缺陷说明

- 财年与目标公告年标存在歧义，缺少确定性的 target-period gate；可引用真实的错误年度。
- HTML 表格未结构化行列/单位提取，原文数字仅字面支持。
- 金额解析已区分公式与会计括号并支持 m/b/k/bn；原文流出绑定仍只检查负数字面和附近措辞，未证明行列/指标归属，叙述性亏损可能仍需重试。
- 模型误抄 ID/绑定片段、误选指标、错误单位仍可能造成重试耗尽。
- 已发布前缀冻结与重试改写冲突；recoverable 可恢复语义重复段落。
- 样本覆盖/行业成员语义、扩展断言因果未独立证明。
- 报告识别采用有限关键词正则，不是所有请求文件的自然语言都能稳定识别。
- 快照存在，但没有完整 Citation→不可变版本外键、全数值绑定或全文语义校验。
- 全局 SEC 限速、硬配额、持久任务和多进程协调未完成。

这些不是未来路线图，而是当前使用与维护边界。不把 complete/verified/200 当作投资结论正确。

## 本地测试

```bash
uv run pytest -q
uv run ruff check src tests eval/runners/financebench_pilot.py
npm --prefix frontend run build
```

当前 89 项 pytest；覆盖事实/差分/核验、引用、模拟流式/重试、文件限制、语言、SEC mock、公式不安全 AST、输入/结果篡改、scope 等。
测试数量随代码变化；记录实际运行，不以此代替真实模型效果。构建只证明编译，不证明浏览器操作正确。

## 现有评测方法

`eval/dataset/financebench-pilot-10.json`：FinanceBench 公开 150 题中 seed=42 固定抽取 10，英文原题。
该固定题集和 `eval/results/` 仅本地保存，未随公开仓库发布，需另行处理许可与隐私审查。
公开 runner 需要自行准备获准使用且符合输入格式的题集；默认 sample 路径在新克隆中不存在，下方命令须先准备题集。
真实 HTTP runner 创建会话，问题+目标文档名输入，金标/evidence 留在评测侧，不预注入正确数据。
每题 180 秒客户端预算、两题并行、开放公司/年份、as_reported、英文；服务总预算独立。
同模型 gpt-5.6-luna、Responses、普通 4000 tokens、60 工具、2 重试；线上来源与混合暖缓存。
输出 metadata（含题集文件与源代码 SHA256）、gold、逐题事件/回答/来源/持久化线程、results.jsonl；复核 review.json 保留。
当前 API 没有 token/cost 数据，不填写 0；judge 的数字/引用 accession 比较不能代替文本蕴含评审。

```bash
uv run python eval/runners/financebench_pilot.py \
  --sample eval/dataset/financebench-pilot-10.json \
  --output eval/results/new-run \
  --timeout 180 --concurrency 2
```

输出目录必须新建；runner 先探测 health，但 health 不验证模型就绪。运行会创建真实会话/缓存，不是完全无副作用测试。

## 当前可引用结论

已保留原始 baseline/v2/v3/v4 数据；失效启动记录另有 metadata 标志，不纳入准确率。
baseline 与旧 v4 完整核心正确均 6/10。当前 verification-opt-v1 完整核心正确为 9/10（90%），平均 36.448 秒；旧 v4 为 44.85 秒，baseline 为 70.39 秒。
当前 10/10 complete，但 Ulta 使用了错误目标期间，因此准确率为 9/10。全部最终回答重新通过引用检查，48/48 引用接口成功。
本轮仅完成一个迭代版本，因达到 80% 目标停止；模型与预算不变、题目与金标不变。原始过程、代码快照、复核和后续优化方向保留于本地 verification-opt-v1。
后续优先解决公告年与发行人财年歧义；再评估完整校验后发布、结构化表格与有限指标别名，并以未见题和重复运行核实效果。
这批题已用于开发排错，属于开发集回归而非独立留出；暖缓存/随机性/提前失败影响耗时。
没有同模型裸调用/ChatGPT 对照，没有全量 FinanceBench 或完整研报/XLSX 评测，不能声称超越 ChatGPT。
下一次正式评审必须固定预算/资料截止、保留原始过程、核对语义/期间/数值/交付并使用未见样本与重复运行。
