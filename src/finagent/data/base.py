from collections.abc import Awaitable, Callable
from typing import Protocol

from finagent.schemas import Company, FactRecord, Filing, ResearchScope

ProgressCallback = Callable[[str], Awaitable[None]]


class DataSource(Protocol):
    async def search_companies(self, query: str, limit: int = 10) -> list[Company]: ...

    async def list_filings(self, company: Company, scope: ResearchScope) -> list[Filing]: ...

    async def fetch_filing_html(self, filing: Filing) -> str: ...

    async def fetch_facts(self, company: Company) -> list[FactRecord]: ...
