from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal

from finagent.schemas import (
    Cell,
    Citation,
    Company,
    ComparisonRow,
    ComparisonTable,
    FactRecord,
    Formula,
    ResearchScope,
    SourceRef,
    ValueRef,
    VerificationResult,
    VerificationStatus,
    XbrlLocator,
)
from finagent.storage import SQLiteStore

METRIC_CONCEPTS: dict[str, tuple[str, ...]] = {
    "revenue": (
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "SalesRevenueNet",
        "Revenues",
    ),
    "net_income": ("NetIncomeLoss", "ProfitLoss"),
    "operating_income": ("OperatingIncomeLoss",),
    "gross_profit": ("GrossProfit",),
    "cost_of_revenue": ("CostOfRevenue", "CostOfGoodsAndServicesSold", "CostOfGoodsSold"),
    "research_and_development": ("ResearchAndDevelopmentExpense",),
    "selling_general_admin": ("SellingGeneralAndAdministrativeExpense",),
    "interest_expense": ("InterestExpenseNonOperating", "InterestAndDebtExpense"),
    "income_tax": ("IncomeTaxExpenseBenefit",),
    "operating_cash_flow": ("NetCashProvidedByUsedInOperatingActivities",),
    "investing_cash_flow": ("NetCashProvidedByUsedInInvestingActivities",),
    "financing_cash_flow": ("NetCashProvidedByUsedInFinancingActivities",),
    "capital_expenditure": ("PaymentsToAcquirePropertyPlantAndEquipment",),
    "assets": ("Assets",),
    "current_assets": ("AssetsCurrent",),
    "liabilities": ("Liabilities",),
    "current_liabilities": ("LiabilitiesCurrent",),
    "equity": (
        "StockholdersEquity",
        "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
    ),
    "accounts_receivable": ("AccountsReceivableNetCurrent",),
    "inventory": ("InventoryNet",),
    "accounts_payable": ("AccountsPayableCurrent",),
    "cash": (
        "CashAndCashEquivalentsAtCarryingValue",
        "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
    ),
}
INSTANT_METRICS = {
    "assets",
    "cash",
    "current_assets",
    "liabilities",
    "current_liabilities",
    "equity",
    "accounts_receivable",
    "inventory",
    "accounts_payable",
}


@dataclass(frozen=True)
class ResolvedFact:
    value: Decimal
    citations: list[Citation]
    formula: Formula
    warnings: list[str]


def parse_period(period: str) -> tuple[int, str]:
    match = re.fullmatch(r"(\d{4})-(FY|Q[1-4])", period.upper())
    if not match:
        raise ValueError(f"Unsupported period: {period}; use YYYY-FY or YYYY-Q1..Q4")
    return int(match.group(1)), match.group(2)


class FactResolver:
    def __init__(self, store: SQLiteStore) -> None:
        self.store = store

    def resolve(
        self,
        company: Company,
        metric: str,
        period: str,
        policy: str = "latest_restated",
    ) -> ResolvedFact | None:
        concepts = METRIC_CONCEPTS.get(metric)
        if not concepts:
            raise ValueError(f"Unsupported metric: {metric}")
        fiscal_year, fiscal_period = parse_period(period)
        facts = self.store.list_facts(company.cik, concepts, [fiscal_year])
        for concept in concepts:
            concept_facts = [fact for fact in facts if fact.concept == concept]
            resolved = self._resolve_concept(
                company,
                concept_facts,
                fiscal_year,
                fiscal_period,
                policy,
                instant=metric in INSTANT_METRICS,
            )
            if resolved is not None:
                return resolved
        return None

    def _resolve_concept(
        self,
        company: Company,
        facts: list[FactRecord],
        fiscal_year: int,
        fiscal_period: str,
        policy: str,
        *,
        instant: bool,
    ) -> ResolvedFact | None:
        candidates = [
            fact
            for fact in facts
            if fact.fiscal_year == fiscal_year
            and fact.fiscal_period == fiscal_period
            and not fact.dimensions
        ]
        if instant:
            target_period = "FY" if fiscal_period == "Q4" else fiscal_period
            instant_candidates = [
                fact
                for fact in facts
                if fact.start is None
                and fact.fiscal_year == fiscal_year
                and fact.fiscal_period == target_period
                and not fact.dimensions
            ]
            return self._direct(company, self._latest_period_end(instant_candidates), policy)
        if fiscal_period == "FY":
            annual = [fact for fact in candidates if self._duration_days(fact) >= 300]
            return self._direct(company, self._latest_period_end(annual), policy)
        if fiscal_period in {"Q1", "Q2", "Q3"}:
            standalone = [fact for fact in candidates if 60 <= self._duration_days(fact) <= 120]
            direct = self._direct(company, self._latest_period_end(standalone), policy)
            if direct is not None:
                return direct
            cumulative = [fact for fact in candidates if self._duration_days(fact) > 120]
            current = self._select(self._latest_period_end(cumulative), policy)
            if current is None:
                return None
            previous_period = f"Q{int(fiscal_period[-1]) - 1}"
            previous = self._select(
                [
                    fact
                    for fact in facts
                    if fact.fiscal_period == previous_period
                    and fact.unit == current.unit
                    and fact.dimensions == current.dimensions
                    and fact.start == current.start
                    and fact.end < current.end
                ],
                policy,
            )
            if previous is None:
                return None
            return self._subtract(company, current, previous, "YTD subtraction")
        if fiscal_period == "Q4":
            annual = self._select(
                self._latest_period_end(
                    [
                        fact
                        for fact in facts
                        if fact.fiscal_period == "FY" and self._duration_days(fact) >= 300
                    ]
                ),
                policy,
            )
            q3_ytd = self._select(
                self._latest_period_end(
                    [
                        fact
                        for fact in facts
                        if fact.fiscal_period == "Q3" and self._duration_days(fact) > 180
                    ]
                ),
                policy,
            )
            if annual is None or q3_ytd is None:
                return None
            if not self._compatible(annual, q3_ytd):
                return None
            return self._subtract(company, annual, q3_ytd, "FY minus Q3 YTD")
        return None

    def _direct(
        self, company: Company, facts: list[FactRecord], policy: str
    ) -> ResolvedFact | None:
        selected = self._select(facts, policy)
        if selected is None:
            return None
        citation = self._citation(company, selected)
        warnings = self._restatement_warnings(facts, selected)
        return ResolvedFact(
            value=selected.value,
            citations=[citation],
            formula=Formula(
                operation="direct",
                input_citation_ids=[citation.citation_id],
                expression="reported value",
            ),
            warnings=warnings,
        )

    def _subtract(
        self,
        company: Company,
        current: FactRecord,
        previous: FactRecord,
        label: str,
    ) -> ResolvedFact:
        current_citation = self._citation(company, current)
        previous_citation = self._citation(company, previous)
        ids = [current_citation.citation_id, previous_citation.citation_id]
        return ResolvedFact(
            value=current.value - previous.value,
            citations=[current_citation, previous_citation],
            formula=Formula(
                operation="subtract",
                input_citation_ids=ids,
                expression=f"{ids[0]} - {ids[1]} ({label})",
            ),
            warnings=[],
        )

    def _citation(self, company: Company, fact: FactRecord) -> Citation:
        filing = self.store.get_filing(fact.accession_no)
        accession_compact = fact.accession_no.replace("-", "")
        fallback_url = (
            f"https://www.sec.gov/Archives/edgar/data/{int(company.cik)}/{accession_compact}/"
        )
        source = SourceRef(
            source_type="xbrl",
            cik=company.cik,
            ticker=company.ticker,
            form=fact.form,
            accession_no=fact.accession_no,
            filing_date=fact.filed,
            primary_document=filing.primary_document if filing else None,
            sec_url=filing.sec_url if filing else fallback_url,
        )
        locator = XbrlLocator(
            taxonomy=fact.taxonomy,
            concept=fact.concept,
            unit=fact.unit,
            start=fact.start,
            end=fact.end,
            fiscal_year=fact.fiscal_year,
            fiscal_period=fact.fiscal_period,
            frame=fact.frame,
            dimensions=fact.dimensions,
        )
        citation = Citation(
            citation_id=Citation.stable_id(source, locator),
            source=source,
            locator=locator,
            value=ValueRef(amount=fact.value, unit=fact.unit, as_reported=fact.value),
        )
        return self.store.register_citation(citation)

    @staticmethod
    def _latest_period_end(facts: list[FactRecord]) -> list[FactRecord]:
        # Company Facts fy/fp label the submitting filing. The same filing
        # includes prior-period comparisons; never treat them as current data.
        if not facts:
            return []
        end = max(fact.end for fact in facts)
        return [fact for fact in facts if fact.end == end]

    @staticmethod
    def _select(facts: list[FactRecord], policy: str) -> FactRecord | None:
        if not facts:
            return None
        ordered = sorted(facts, key=lambda fact: (fact.filed, fact.accession_no))
        return ordered[0] if policy == "as_reported" else ordered[-1]

    @staticmethod
    def _duration_days(fact: FactRecord) -> int:
        return (fact.end - fact.start).days if fact.start else 0

    @staticmethod
    def _compatible(left: FactRecord, right: FactRecord) -> bool:
        return (
            left.concept == right.concept
            and left.unit == right.unit
            and left.dimensions == right.dimensions
            and left.start == right.start
            and left.end >= right.end
        )

    @staticmethod
    def _restatement_warnings(facts: list[FactRecord], selected: FactRecord) -> list[str]:
        comparable = [
            fact
            for fact in facts
            if fact.start == selected.start
            and fact.end == selected.end
            and fact.unit == selected.unit
            and fact.dimensions == selected.dimensions
        ]
        values = {fact.value for fact in comparable}
        if len(values) > 1:
            return ["同一期间存在多个披露值；已按所选重述口径取值"]
        return []


def build_comparison(
    store: SQLiteStore,
    request_scope: ResearchScope,
    metrics: list[str],
    periods: list[str],
) -> ComparisonTable:
    resolver = FactResolver(store)
    rows: list[ComparisonRow] = []
    warnings: list[str] = []
    for company in request_scope.companies:
        for metric in metrics:
            for period in periods:
                resolved = resolver.resolve(
                    company, metric, period, request_scope.restatement_policy
                )
                if resolved is None:
                    warnings.append(f"{company.ticker} {metric} {period}: no compatible fact")
                    cell = Cell(
                        value=None,
                        display_value="—",
                        verification=VerificationResult(
                            status=VerificationStatus.MISSING,
                            message="No compatible SEC fact was found",
                        ),
                    )
                else:
                    citation_ids = [citation.citation_id for citation in resolved.citations]
                    cell = Cell(
                        value=resolved.value,
                        display_value=f"{resolved.value:,.0f}",
                        unit=(
                            resolved.citations[0].value.unit
                            if resolved.citations[0].value
                            else None
                        ),
                        source_citation_ids=citation_ids,
                        formula=resolved.formula,
                        verification=VerificationResult(
                            status=VerificationStatus.NOT_APPLICABLE,
                            message="Pending independent verification",
                        ),
                        warnings=[
                            "Multiple disclosed values for the same period; "
                            "selected restatement policy applied"
                            if request_scope.language == "en"
                            and warning == "同一期间存在多个披露值；已按所选重述口径取值"
                            else warning
                            for warning in resolved.warnings
                        ],
                    )
                    warnings.extend(cell.warnings)
                rows.append(ComparisonRow(company=company, metric=metric, period=period, cell=cell))
    return ComparisonTable(
        title="SEC financial comparison",
        rows=rows,
        verified=False,
        warnings=list(dict.fromkeys(warnings)),
    )
