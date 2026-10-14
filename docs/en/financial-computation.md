# Financial data and computation

[中文](../zh-CN/financial-computation.md) · [README](../../README.en.md)

Verified against current implementation: 2026-10-14.

## Metrics and accounting scope

`data/facts.py` defines 22 mapped keys, not every financial metric:

```text
revenue net_income operating_income gross_profit cost_of_revenue
research_and_development selling_general_admin interest_expense income_tax
operating_cash_flow investing_cash_flow financing_cash_flow capital_expenditure
assets current_assets liabilities current_liabilities equity
accounts_receivable inventory accounts_payable cash
```

Each key prioritizes US-GAAP concepts. Unknown extensions can be discovered but do not automatically enter comparable tables.
Common aliases include cogs/inventories/capex. Dimensional facts are generally excluded by the consolidated resolver.
Values use Decimal. Missing/None is not zero; a verified table can include missing cells.

## Period selection

Inputs are `YYYY-FY` or `YYYY-Q1..Q4`. Candidates use submitting fy/fp; annual duration is at least 300 days with latest actual end.
Quarterly flows prefer standalone 60..120-day facts, otherwise cumulative differences; Q4=annual−Q3 cumulative.
Differences require compatible concept/unit/dimensions/start and ordered ends. Instant balances use period end; Q4 uses FY.
For a selected end, as_reported chooses earliest filed/accession, latest_restated chooses latest.

Company Facts fy/fp describes the filing context and may include prior-year comparisons. A unified PeriodRef is absent.
`discover_financial_periods(end_years)` finds actual annual revenue dates (300..400 days), warning that its period label is not an inferred issuer fiscal year.
Revenue availability does not guarantee all metrics. Numeric resolution is not further filtered by requested Scope.forms.
Non-calendar years, 52/53 weeks and announcement-year versus issuer-FY labels need explicit checking.

## Two computation mechanisms

1. Table Formula: direct/subtract/divide/growth/cagr/share binds original XBRL source IDs; verify/numbers.py looks up and recomputes.
2. Agent `compute_financial`: bounded AST arithmetic over variable→registered numeric citation mappings; generates D-prefixed citations and SQLite computations.

Limits: 1000 expression characters, 80 AST nodes, 1..20 inputs. Only numeric constants, names, unary signs and +−*/.
Constants have absolute value ≤1000000; every supplied input must be used. No import, function calls or host execution.
Decimal precision 34; zero denominator fails. Addition/subtraction require matching units; multiplication allows only one dimensional operand; matching division is dimensionless.
Output units are USD/ratio/percent/percentage_points/days. Display percentages participate in subsequent arithmetic as dimensionless values, without automatic ratio↔percent rescaling.

## Examples and lineage

### Display precision

`compute_financial` accepts `decimal_places` as an integer from 0 to 4 (default 2). Its `display` object contains `text`, `amount`, `unit`, `scale`, `decimal_places` and `rounded`; the citation and computation record still retain the original full-precision value. Presentation uses ROUND_HALF_UP and suppresses negative zero.

For example, a percent result of `7.67781155` displays as `7.68%`, and `751400000` USD displays as `USD 751.40 million`. USD switches to million at an absolute value of 1,000,000 and billion at 1,000,000,000. Bind the exact displayed span to the original citation ID; use that ID, rather than rounded strings, for subsequent arithmetic. Reports and answers normally use two places; financial claims with more than four decimal places are rejected. Saved source values and workbook data are not rounded by this display helper.

Cash-flow/revenue uses `cash/revenue*100` with `output_unit='percent'`. To format an existing currency value, use `expression='x'` with `output_unit='USD'`; display scaling is automatic and does not change the monetary value.

```text
growth: (current/prior-1)*100 → percent
margin: profit/revenue*100 → percent
margin delta: current_margin-prior_margin → percentage_points
DPO: 365*((ap_prior+ap_current)/2)/(cogs+inventory_current-inventory_prior) → days
```

Margin-change inputs must use previously returned percent citations, rather than subtracting USD gross-profit values and relabeling the result percentage_points. Answers can explain formulas using metric names; computations retain exact input IDs, values and units, reducing repeated transcription.

These illustrate methods, not universally correct accounting definitions. Inputs must be original XBRL or registered derived values; narrative quotes are not inferred ValueRefs.
Records retain expression, input IDs/values/units, result, precision and verification. Recursive source lookup/replay detects changed inputs/results before publication.
Execution/replay share one engine, not independent implementations; incorrect constants/formulas can still produce grounded but wrong financial conclusions.
