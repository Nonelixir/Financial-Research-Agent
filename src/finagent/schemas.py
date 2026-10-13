from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from enum import StrEnum
from hashlib import sha256
from typing import Annotated, Literal

from pydantic import AnyHttpUrl, BaseModel, Field, model_validator


def utc_now() -> datetime:
    return datetime.now(UTC)


class Company(BaseModel):
    cik: str
    ticker: str
    name: str
    aliases: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def normalize(self) -> Company:
        self.cik = self.cik.removeprefix("CIK").zfill(10)
        self.ticker = self.ticker.upper().strip()
        return self


class ResearchScope(BaseModel):
    language: Literal["zh", "en"] = "zh"
    companies: list[Company] = Field(default_factory=list, max_length=30)
    strict: bool = False
    forms: list[str] = Field(default_factory=lambda: ["10-K", "10-Q"])
    fiscal_years: list[int] = Field(default_factory=list)
    restatement_policy: Literal["as_reported", "latest_restated"] = "latest_restated"

    @model_validator(mode="after")
    def normalize(self) -> ResearchScope:
        self.forms = list(dict.fromkeys(form.upper() for form in self.forms))
        self.fiscal_years = sorted(set(self.fiscal_years), reverse=True)
        return self


class Filing(BaseModel):
    cik: str
    accession_no: str
    form: str
    filing_date: date
    report_date: date | None = None
    primary_document: str | None = None
    sec_url: AnyHttpUrl
    content_sha256: str | None = None


class SourceRef(BaseModel):
    source_type: Literal["xbrl", "filing_text", "derived", "web"]
    cik: str
    ticker: str
    form: str
    accession_no: str
    filing_date: date
    primary_document: str | None = None
    sec_url: AnyHttpUrl
    content_sha256: str | None = None
    title: str | None = None


class XbrlLocator(BaseModel):
    kind: Literal["xbrl"] = "xbrl"
    taxonomy: str = "us-gaap"
    concept: str
    unit: str
    start: date | None = None
    end: date
    fiscal_year: int | None = None
    fiscal_period: str | None = None
    frame: str | None = None
    dimensions: dict[str, str] = Field(default_factory=dict)


class TextLocator(BaseModel):
    kind: Literal["text"] = "text"
    section: str
    paragraph_index: int = Field(ge=0)
    dom_path: str | None = None
    exact_quote: str = Field(min_length=1)
    quote_sha256: str


class DerivedLocator(BaseModel):
    kind: Literal["derived"] = "derived"
    operation: str
    input_citation_ids: list[str] = Field(min_length=1)


Locator = Annotated[XbrlLocator | TextLocator | DerivedLocator, Field(discriminator="kind")]


class ValueRef(BaseModel):
    amount: Decimal
    unit: str
    as_reported: Decimal | None = None
    scale: Decimal = Decimal(1)


class Citation(BaseModel):
    citation_id: str
    source: SourceRef
    locator: Locator
    value: ValueRef | None = None
    retrieved_at: datetime = Field(default_factory=utc_now)

    @staticmethod
    def stable_id(source: SourceRef, locator: Locator) -> str:
        excluded = {"sec_url"}
        # Preserve historical SEC IDs when adding optional web metadata.
        if source.source_type != "web":
            excluded.update({"content_sha256", "title"})
        material = source.model_dump_json(exclude=excluded) + locator.model_dump_json()
        return "C" + sha256(material.encode()).hexdigest()[:16].upper()


class CompletionStatus(StrEnum):
    COMPLETE = "complete"
    INCOMPLETE = "incomplete"
    REFUSED = "refused"
    ERROR = "error"


class NumericBinding(BaseModel):
    """Exact displayed span bound to one registered numeric fact or computation."""

    text: str = Field(min_length=1)
    citation_id: str
    presentation: Literal["signed", "outflow", "loss"] = "signed"


class Claim(BaseModel):
    citation_ids: list[str] = Field(min_length=1)
    text: str = Field(min_length=1)
    numeric_bindings: list[NumericBinding] = Field(default_factory=list)


class Answer(BaseModel):
    claims: list[Claim]
    message: str = ""
    caveats: list[str] = Field(default_factory=list)
    status: CompletionStatus = CompletionStatus.COMPLETE
    status_reason: str | None = None


class FactRecord(BaseModel):
    cik: str
    ticker: str
    taxonomy: str = "us-gaap"
    concept: str
    unit: str
    value: Decimal
    start: date | None = None
    end: date
    fiscal_year: int | None = None
    fiscal_period: str | None = None
    form: str
    accession_no: str
    filed: date
    frame: str | None = None
    dimensions: dict[str, str] = Field(default_factory=dict)

    def identity(self) -> str:
        material = "|".join(
            [
                self.cik,
                self.taxonomy,
                self.concept,
                self.unit,
                self.start.isoformat() if self.start else "",
                self.end.isoformat(),
                str(sorted(self.dimensions.items())),
                self.accession_no,
            ]
        )
        return sha256(material.encode()).hexdigest()


class FilingChunk(BaseModel):
    chunk_id: str
    cik: str
    ticker: str
    accession_no: str
    form: str
    filing_date: date
    section: str
    paragraph_index: int
    text: str
    dom_path: str | None = None
    sec_url: AnyHttpUrl


class SearchHit(BaseModel):
    citation: Citation
    text: str
    score: float


class Formula(BaseModel):
    operation: Literal["direct", "subtract", "divide", "growth", "cagr", "share"]
    input_citation_ids: list[str] = Field(default_factory=list)
    expression: str


class VerificationStatus(StrEnum):
    VERIFIED = "verified"
    MISSING = "missing"
    MISMATCH = "mismatch"
    NOT_APPLICABLE = "not_applicable"


class VerificationResult(BaseModel):
    status: VerificationStatus
    checked_at: datetime = Field(default_factory=utc_now)
    message: str | None = None
    expected: Decimal | None = None
    actual: Decimal | None = None


class Cell(BaseModel):
    value: Decimal | None
    display_value: str
    unit: str | None = None
    source_citation_ids: list[str] = Field(default_factory=list)
    formula: Formula | None = None
    verification: VerificationResult
    warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def provenance_required(self) -> Cell:
        if self.value is not None and not self.source_citation_ids:
            raise ValueError("A numeric cell must have at least one source citation")
        if self.formula and self.formula.operation != "direct":
            missing = set(self.formula.input_citation_ids) - set(self.source_citation_ids)
            if missing:
                raise ValueError("Derived cell must expose every formula input citation")
        return self


class ComparisonRow(BaseModel):
    company: Company
    metric: str
    period: str
    cell: Cell


class ComparisonTable(BaseModel):
    title: str
    rows: list[ComparisonRow]
    generated_at: datetime = Field(default_factory=utc_now)
    verified: bool
    warnings: list[str] = Field(default_factory=list)


class AskRequest(BaseModel):
    question: str = Field(min_length=2, max_length=4_000)
    scope: ResearchScope
    history: list[dict[str, str]] = Field(default_factory=list, max_length=20)
    table_context: list[dict] = Field(default_factory=list, max_length=3)
    workspace_thread_id: str | None = None
    workspace_message_id: str | None = None


class TableRequest(BaseModel):
    scope: ResearchScope
    metrics: list[str] = Field(default_factory=lambda: ["revenue", "net_income"])
    periods: list[str] = Field(default_factory=list)


class UserProfile(BaseModel):
    profile_id: str = "default"
    sector: str | None = None
    preferred_tickers: list[str] = Field(default_factory=list)
    language: Literal["zh", "en"] = "zh"
    currency_scale: Literal["units", "thousands", "millions", "billions"] = "millions"
    restatement_policy: Literal["as_reported", "latest_restated"] = "latest_restated"
