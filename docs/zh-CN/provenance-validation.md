# Provenance 与校验

[English](../en/provenance-validation.md) · [README](../../README.md)

按当前代码核对：2026-10-14。

## 数据模型与保证等级

代码：`schemas.py`、`storage.py`、`verify/citations.py`、`verify/numbers.py`。

Citation = citation_id + SourceRef + Locator + 可选 ValueRef + retrieved_at。
SourceRef 保留类型（xbrl/filing_text/derived/web）、CIK/ticker、form/accession、filing_date、URL、文件名及可选 hash/title。
Locator 为 XBRL concept/unit/start/end/fy/fp/frame/dimensions，或原文 section/index/DOM path/exact_quote/quote hash，或派生 operation/input IDs。

| 等级 | 当前实际检查 | 不代表 |
| --- | --- | --- |
| 注册来源 | ID 属于本轮、SQLite 记录存在 | 引用内容支持每个断言 |
| 原文数字支持 | 文字数字能在摘录找到，逗号标准化 | 正确表格列、单位、期间、指标或因果 |
| 绑定数值 | exact span→单一 ValueRef，金额/精度/符号比较 | 所有数字已强制绑定 |
| 表格核验 | 源 XBRL 回查、Formula 复算 | 全部格非缺失、财年口径可靠 |
| 派生重放 | 输入及公式记录存在、递归回查、结果一致 | 金融公式语义正确、第二实现独立审计 |
| 文件完整性 | 实际文件存在、hash 一致，表格再核验 | 任意文档内容已经财务审核 |

## 回答发布步骤

1. Pydantic 解析 Answer，Claim 至少一个引用；numeric_bindings 可缺省。
2. 所有引用属于本轮允许集合且存在，不自动修正接近的 ID；错误只给候选。
3. derived 引用递归 replay；原输入数值和计算记录一致，否则拒绝。
4. 绑定的 text 必须原样出现在 Claim，citation 必须在该 Claim。
5. 数值绑定按金额缩放/舍入比较；signed 保留符号。正数表示 outflow/loss 要求负来源和明确附近措辞。
6. 原文绑定检查字面数字；outflow/loss 另要求同一摘录中的负数字面形式（负号或会计括号）和回答附近的流出/亏损措辞，不生成 ValueRef。此检查不证明表格行列归属。
7. 段落金额继续做集合校验；已验证单源绑定不再被模糊词改符号。混合原文/派生段落允许原文数字与 scale 支持。
8. 百分率/天数要求原文数字或对应单位派生来源；不能把 percentage_points 当 percent。
9. 无数值来源时其余实质数字需原文支持；日期、登记公司名、交易符号、表单和列表号有有限排除。

MONEY 支持 USD/$/美元及中英文 scale 和 m/b/k/bn 简写；只有括号内包含完整单一金额时才按会计负数解释，公式分组括号不改金额符号。
模型改写绑定片段、误用 presentation、引用错位都可能耗尽 2 次重试。校验完整段落≠全面语义核验。

## 表格与文件

`verify_cell` 回查每个 source_citation_id 到原 XBRL，比较 value、执行支持的公式。
至少一个格 verified，全部格为 verified/missing 才 table.verified；否则 XLSX 导出拒绝。
`publish_report` 对 sections 跑回答引用规则；`publish_artifact` 通用文本不跑财务核验。
普通回答不落 artifact。下载检查文件 hash，表格文件另回查数值；报告下载不重新证明文本语义。

## 快照和残余风险

source_snapshots 按 URL+正文 hash 保存，但 Citation 尚无完整不可变版本外键。非网页稳定 ID 排除 title/content_sha256 等字段，citation 注册可更新。
派生 SourceRef 继承首输入，完整血缘看 DerivedLocator 输入列表和 computations，UI 不是完整交互血缘浏览器。
当前没有统一目标期间 gate、行列数值提取、逐句蕴含核验、覆盖率证明；真实引用可支持错误期间。
人工必须核对发行人、实际 start/end、量纲、指标定义、非 GAAP 调节和因果出处。

Answer.message 用于问候、能力说明、澄清或无关请求的范围说明，不需要来源；不可与 claims 混用，显式金融金额和百分率被拒绝。它不是研究事实的替代通道，尚无全面语义校验。

回答校验同时收集各段首个错误，数值绑定错误反馈显示 citation、期望值、单位、展示值及原始 locator，便于一次修正多个公司/期间。百分比紧邻“下降/减少”等措辞时按负增长幅度比较；不把其他段落的下降方向应用到毛利率。显式负数使用 signed。

回答正文在整份校验通过后发布，工具/status 进度仍实时展示；重试可改写未发布草稿，失败恢复只保留最新候选。普通行业回答保持简洁以适配普通输出预算。此前 10 题成绩早于这次发布流程变更。

## 展示检查

财务 claims 中超过四位小数会在发布前被拒绝。Prompt 默认要求两位，`compute_financial.display.text` 提供有界展示值；数值绑定仍按展示精度和金额比例对照原始登记值，不改变证据和计算记录。USD 展示把币种放在金额之前（`USD 751.40 million`），以匹配金额解析器。此检查保障展示规则，不证明金融语义。
