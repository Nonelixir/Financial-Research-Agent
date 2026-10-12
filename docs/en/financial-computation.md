# Financial data and computation

[中文](../zh-CN/financial-computation.md) · [README](../../README.en.md)

Verified against current implementation: 2026-10-12.

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

```text
growth: (current/prior-1)*100 → percent
margin: profit/revenue*100 → percent
margin delta: current_margin-prior_margin → percentage_points
DPO: 365*((ap_prior+ap_current)/2)/(cogs+inventory_current-inventory_prior) → days
```

These illustrate methods, not universally correct accounting definitions. Inputs must be original XBRL or registered derived values; narrative quotes are not inferred ValueRefs.
Records retain expression, input IDs/values/units, result, precision and verification. Recursive source lookup/replay detects changed inputs/results before publication.
Execution/replay share one engine, not independent implementations; incorrect constants/formulas can still produce grounded but wrong financial conclusions.
