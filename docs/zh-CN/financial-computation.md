# 财务数据与计算

[English](../en/financial-computation.md) · [README](../../README.md)

按当前代码核对：2026-10-12。

## 指标与口径

代码：`data/facts.py`，22 个映射 key（不是全部财报指标）：

```text
revenue net_income operating_income gross_profit cost_of_revenue
research_and_development selling_general_admin interest_expense income_tax
operating_cash_flow investing_cash_flow financing_cash_flow capital_expenditure
assets current_assets liabilities current_liabilities equity
accounts_receivable inventory accounts_payable cash
```

每 key 使用按优先顺序的 US-GAAP concept；未知扩展可发现，但不会自动并入可比表格。
常见别名如 cogs/inventories/capex 被映射。维度事实通常不进入当前合并报表 resolver。
金额使用 Decimal；`None`/missing 不是零。表格核验通过也可包含缺失格。

## 期间选择

输入 `YYYY-FY` 或 `YYYY-Q1..Q4`。候选按提交 fy/fp 筛选，全年持续期≥300 天，取最新实际 end。
季度优先 60..120 天独立季度，否则累计值减前期累计；Q4=全年−Q3 累计。
差分要求相同概念、单位、维度和 start、合法 end 顺序。余额取期末 instant，Q4 按 FY。
同一 end 的候选按 filed/accession 排序：as_reported 最早、latest_restated 最新。

Company Facts fy/fp 是提交上下文，可含前期比较数；尚无统一财年 PeriodRef。
`discover_financial_periods(end_years)` 以实际 dates 找全年收入观察值（300..400 天），并提示返回 period 标签并非推导的发行人财年。
年度收入存在不代表所有指标齐全。文本 Scope.forms 与数值 resolver 不一致：数值不进一步按请求表单过滤。
非日历财年、52/53 周、公告年标和发行人财年仍需核实，不可默认同一年标签可比。

## 两种计算机制

1. 表格 Formula：direct/subtract/divide/growth/cagr/share，source_citation_ids 关联原 XBRL，verify/numbers.py 回查再算。
2. Agent `compute_financial`：有界 AST 四则运算，inputs 变量→本轮数值 citation；生成 D 开头的派生引用和 SQLite computations 记录。

表达式最多 1000 字符、80 AST 节点、1..20 输入；只允许数字常数、变量、单目符号、+−*/。
常数绝对值≤1000000；所有提供的输入必须使用；不支持 import、函数调用或宿主机代码。
Decimal 精度 34；零分母报错。加减单位一致；乘法仅一边可有量纲；同单位相除得到无量纲。
输出 USD/ratio/percent/percentage_points/days；百分率展示值按无量纲参与下一步运算，但不自动进行 ratio↔percent 的数值缩放。

## 示例与来源链

```text
growth: (current/prior-1)*100 → percent
margin: profit/revenue*100 → percent
margin delta: current_margin-prior_margin → percentage_points
DPO: 365*((ap_prior+ap_current)/2)/(cogs+inventory_current-inventory_prior) → days
```

这些是方法示例，不证明特定行业口径正确。输入必须是原 XBRL 数值或已注册派生值；原文摘录不能直接推断 ValueRef。
记录保存表达式、输入 ID/值/单位、结果、精度、verification；发布前递归回查/replay，检测输入/结果变更。
执行与重放使用同一引擎，不是第二实现；常数或错误金融公式仍可算出来源真实但结论错误的值。
