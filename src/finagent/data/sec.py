from __future__ import annotations

import asyncio
import json
import re
import time
from datetime import date
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

import httpx

from finagent.config import Settings
from finagent.schemas import Company, FactRecord, Filing, ResearchScope

if TYPE_CHECKING:
    from finagent.storage import SQLiteStore

SEC_HOSTS = {"www.sec.gov", "data.sec.gov"}
TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"


class SecClient:
    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        store: SQLiteStore | None = None,
    ) -> None:
        self.settings = settings
        self.client = httpx.AsyncClient(
            timeout=settings.request_timeout_seconds,
            transport=transport,
            headers={
                "User-Agent": settings.sec_identity,
                "Accept-Encoding": "gzip, deflate",
                "Accept": "application/json,text/html;q=0.9,*/*;q=0.8",
            },
            follow_redirects=False,
        )
        self._rate_lock = asyncio.Lock()
        self._last_request = 0.0
        self.store = store

    async def close(self) -> None:
        await self.client.aclose()

    async def _get(self, url: str) -> httpx.Response:
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.hostname not in SEC_HOSTS:
            raise ValueError("Only known HTTPS SEC hosts are allowed")
        async with self._rate_lock:
            interval = 1 / self.settings.sec_requests_per_second
            delay = interval - (time.monotonic() - self._last_request)
            if delay > 0:
                await asyncio.sleep(delay)
            response = await self.client.get(url)
            self._last_request = time.monotonic()
        response.raise_for_status()
        return response

    async def _get_json(self, url: str, max_age_seconds: int) -> dict[str, Any]:
        if self.store and (cached := self.store.get_source_cache(url, max_age_seconds)):
            value = json.loads(cached)
            if isinstance(value, dict):
                return value
        response = await self._get(url)
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("SEC JSON response must be an object")
        if self.store:
            self.store.put_source_cache(url, response.text, "application/json")
        return payload

    async def search_companies(self, query: str, limit: int = 10) -> list[Company]:
        payload = await self._get_json(TICKERS_URL, max_age_seconds=86_400)
        ticker_terms = re.findall(r"[A-Za-z][A-Za-z0-9.-]*", query.upper())
        terms = ticker_terms or [term for term in query.upper().replace("/", " ").split() if term]
        companies: list[Company] = []
        for item in payload.values():
            ticker = str(item.get("ticker", "")).upper()
            name = str(item.get("title", ""))
            haystack = f"{ticker} {name.upper()}"
            if terms and not all(term in haystack for term in terms):
                continue
            companies.append(Company(cik=str(item["cik_str"]), ticker=ticker, name=name))
        companies.sort(key=lambda company: (company.ticker != query.upper(), company.ticker))
        return companies[:limit]

    async def list_filings(self, company: Company, scope: ResearchScope) -> list[Filing]:
        payload = await self._get_json(
            SUBMISSIONS_URL.format(cik=company.cik), max_age_seconds=3_600
        )
        recent = payload.get("filings", {}).get("recent", {})
        batches = [recent]
        # Historical directory shards are fetched only when a requested year overlaps.
        # This discovers metadata, never downloads all historical filing bodies.
        for shard in payload.get("filings", {}).get("files", []):
            if not scope.fiscal_years:
                continue
            lower = int(str(shard.get("filingFrom", "1900"))[:4])
            upper = int(str(shard.get("filingTo", "2100"))[:4])
            if not any(lower - 1 <= y <= upper for y in scope.fiscal_years):
                continue
            name = str(shard.get("name", ""))
            if not re.fullmatch(r"CIK\d+-submissions-\d+\.json", name):
                continue
            batches.append(await self._get_json("https://data.sec.gov/submissions/" + name, 86400))
        result = {}
        for batch in batches:
            for filing in self._parse_filings(company, scope, batch):
                result[filing.accession_no] = filing
        return sorted(result.values(), key=lambda f: f.filing_date, reverse=True)

    @staticmethod
    def _parse_filings(company: Company, scope: ResearchScope, recent: dict) -> list[Filing]:
        allowed_forms = set(scope.forms)
        filings: list[Filing] = []
        for index, accession in enumerate(recent.get("accessionNumber", [])):
            form = str(recent.get("form", [""])[index]).upper()
            base_form = form.removesuffix("/A")
            if base_form not in allowed_forms:
                continue
            filing_date = date.fromisoformat(recent["filingDate"][index])
            report_value = recent.get("reportDate", [""] * (index + 1))[index]
            report_date = date.fromisoformat(report_value) if report_value else None
            period_date = filing_date if base_form == "8-K" else report_date
            if scope.fiscal_years and (
                not period_date or period_date.year not in scope.fiscal_years
            ):
                continue
            primary_document = recent.get("primaryDocument", [None] * (index + 1))[index]
            accession_compact = accession.replace("-", "")
            sec_url = (
                f"https://www.sec.gov/Archives/edgar/data/{int(company.cik)}/"
                f"{accession_compact}/{primary_document}"
            )
            filings.append(
                Filing(
                    cik=company.cik,
                    accession_no=accession,
                    form=form,
                    filing_date=filing_date,
                    report_date=report_date,
                    primary_document=primary_document,
                    sec_url=sec_url,
                )
            )
        return filings

    async def list_documents(self, filing: Filing) -> list[dict]:
        """Read the SEC filing index to discover declared attachments, not guessed URLs."""
        base = (
            f"https://www.sec.gov/Archives/edgar/data/{int(filing.cik)}/"
            f"{filing.accession_no.replace('-', '')}/"
        )
        url = base + filing.accession_no + "-index.html"
        cached = self.store.get_source_cache(url, 86400) if self.store else None
        response = None if cached else await self._get(url)
        body = cached or response.text
        parser = FilingIndexParser()
        parser.feed(body)
        if self.store and response is not None:
            self.store.put_source_cache(str(response.url), response.text, "text/html")
        return [{**row, "url": base + row["filename"]} for row in parser.documents]

    async def fetch_document(self, filing: Filing, filename: str) -> str:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*\.(?:htm|html|txt)", filename, re.I):
            raise ValueError("Only declared HTML/text attachments are supported; PDF is not parsed")
        documents = await self.list_documents(filing)
        document = next((d for d in documents if d["filename"] == filename), None)
        if not document:
            raise ValueError("Attachment is not declared in this SEC filing index")
        if self.store and (cached := self.store.get_source_cache(document["url"], 86400)):
            return cached
        response = await self._get(document["url"])
        if self.store:
            self.store.put_source_cache(document["url"], response.text, "text/html")
        return response.text

    async def fetch_filing_html(self, filing: Filing) -> str:
        if self.store and (body := self.store.get_source_cache(str(filing.sec_url), 86400)):
            return body
        response = await self._get(str(filing.sec_url))
        if self.store:
            self.store.put_source_cache(str(filing.sec_url), response.text, "text/html")
        return response.text

    async def fetch_facts(self, company: Company) -> list[FactRecord]:
        payload = await self._get_json(FACTS_URL.format(cik=company.cik), max_age_seconds=21_600)
        records: list[FactRecord] = []
        for taxonomy, concepts in payload.get("facts", {}).items():
            for concept, definition in concepts.items():
                for unit, facts in definition.get("units", {}).items():
                    for item in facts:
                        record = self._fact_record(company, taxonomy, concept, unit, item)
                        if record is not None:
                            records.append(record)
        return records

    @staticmethod
    def _fact_record(
        company: Company,
        taxonomy: str,
        concept: str,
        unit: str,
        item: dict[str, Any],
    ) -> FactRecord | None:
        required = {"val", "end", "accn", "filed", "form"}
        if not required.issubset(item):
            return None
        try:
            value = Decimal(str(item["val"]))
            if not value.is_finite():
                return None
        except (InvalidOperation, ValueError):
            return None
        form = str(item["form"]).upper()
        if form.removesuffix("/A") not in {"10-K", "10-Q"}:
            return None
        return FactRecord(
            cik=company.cik,
            ticker=company.ticker,
            taxonomy=taxonomy,
            concept=concept,
            unit=unit,
            value=value,
            start=date.fromisoformat(item["start"]) if item.get("start") else None,
            end=date.fromisoformat(item["end"]),
            fiscal_year=item.get("fy"),
            fiscal_period=item.get("fp"),
            form=form,
            accession_no=str(item["accn"]),
            filed=date.fromisoformat(item["filed"]),
            frame=item.get("frame"),
            dimensions={},
        )


class FilingIndexParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.documents = []
        self.cells = None
        self.current = None
        self.filename = ""

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self.cells, self.filename = [], ""
        elif tag == "td" and self.cells is not None:
            self.current = []
        elif tag == "a" and self.cells is not None:
            href = dict(attrs).get("href", "")
            name = href.rsplit("/", 1)[-1]
            if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*\.(?:htm|html|txt|pdf)", name, re.I):
                self.filename = name

    def handle_data(self, data):
        if self.current is not None:
            self.current.append(data)

    def handle_endtag(self, tag):
        if tag == "td" and self.cells is not None and self.current is not None:
            self.cells.append(" ".join("".join(self.current).split()))
            self.current = None
        elif tag == "tr" and self.cells is not None:
            if len(self.cells) >= 4 and self.filename:
                self.documents.append(
                    {
                        "filename": self.filename,
                        "description": self.cells[1],
                        "type": self.cells[3],
                        "sequence": self.cells[0],
                    }
                )
            self.cells, self.current = None, None
