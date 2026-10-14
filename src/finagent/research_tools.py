"""On-demand research capabilities; the model, not the API, selects the steps."""

from __future__ import annotations

import functools
import json
import re
from datetime import date
from hashlib import sha256
from typing import Annotated, Any
from uuid import uuid4

from pydantic import Field

from finagent.data.facts import METRIC_CONCEPTS, build_comparison
from finagent.data.sec import SecClient
from finagent.retrieval.ingest import chunk_filing
from finagent.retrieval.query import FilingRetriever
from finagent.schemas import Citation, Company, ResearchScope, SourceRef, TextLocator
from finagent.verify.numbers import verify_table


class ResearchTools:
    def __init__(self, deps, settings, emit):
        self.deps, self.settings, self.emit = deps, settings, emit
        self.client = SecClient(settings, store=deps.store)
        self.calls = 0
        self.failures = {}
        self.document_registry = {}
        self.strict_scope = deps.scope.model_copy(deep=True)
        self.companies = {c.ticker: c for c in deps.scope.companies}
        from finagent.web import PublicWeb

        self.web = PublicWeb(deps.store, settings)
        thread_id = deps.tool_context.get("thread_id")
        if thread_id:
            from finagent.workspace import thread_data

            sample = thread_data(thread_id).get("research_sample")
            if sample:
                for member in sample["members"]:
                    company = Company.model_validate(member["company"])
                    if not deps.scope.strict or company.ticker in self.companies:
                        self.companies[company.ticker] = company

    def scope(self, tickers: list[str] | None = None, years: list[int] | None = None):
        selected = {ticker.upper() for ticker in (tickers or [])}
        companies = [c for c in self.companies.values() if not selected or c.ticker in selected]
        if not selected and self.deps.scope.companies:
            companies = list(self.deps.scope.companies)
        if not companies or selected - {c.ticker for c in companies}:
            raise ValueError(
                "Resolve company tickers first with resolve_companies; no implicit guesses"
            )
        if self.deps.scope.strict and {c.ticker for c in companies} - {
            c.ticker for c in self.strict_scope.companies
        }:
            raise ValueError("Company is outside the user-requested strict scope")
        requested = years or self.deps.scope.fiscal_years
        if self.deps.scope.strict and set(requested) - set(self.strict_scope.fiscal_years):
            raise ValueError("Year is outside the selected research scope")
        return self.deps.scope.model_copy(
            update={"companies": companies, "fiscal_years": requested}
        )

    def evidence(self, citations: list[Citation]):
        for citation in citations:
            self.deps.allowed_citation_ids.add(citation.citation_id)
            self.deps.store.register_citation(citation)
            self.deps.evidence[citation.citation_id] = citation
        if citations:
            self.emit(
                "sources",
                {
                    "count": len(self.deps.evidence),
                    "narrative_count": sum(c.value is None for c in self.deps.evidence.values()),
                    "xbrl_count": sum(c.value is not None for c in self.deps.evidence.values()),
                    "sources": [c.model_dump(mode="json") for c in citations],
                    "citation_ids": [c.citation_id for c in citations],
                },
            )

    async def indexed(self, scope: ResearchScope):
        filings = []
        for company in scope.companies:
            self.deps.store.upsert_company(company)
            try:
                candidates = await self.client.list_filings(company, scope)
                for filing in candidates:
                    self.deps.store.upsert_filing(filing)
            except Exception:
                candidates = self.cached_filings(scope, company.cik)
                if not candidates:
                    raise
            candidates.sort(key=lambda f: f.filing_date, reverse=True)
            for filing in candidates[:12]:
                if not self.deps.store.has_filing_content(filing.accession_no):
                    html = await self.client.fetch_filing_html(filing)
                    filing.content_sha256 = sha256(html.encode()).hexdigest()
                    self.deps.store.upsert_filing(filing, raw_html=html)
                    self.deps.store.upsert_chunks(chunk_filing(filing, company.ticker, html))
                filings.append(filing)
        return filings

    def cached_filings(self, scope, cik=None):
        with self.deps.store.connect() as connection:
            rows = connection.execute("SELECT * FROM filings ORDER BY report_date DESC").fetchall()
        return [
            self.deps.store.get_filing(row["accession_no"])
            for row in rows
            if row["cik"] in {c.cik for c in scope.companies}
            and (not cik or row["cik"] == cik)
            and row["form"].removesuffix("/A") in scope.forms
            and (
                not scope.fiscal_years
                or int(
                    (
                        row["filing_date"]
                        if row["form"].startswith("8-K")
                        else row["report_date"] or row["filing_date"]
                    )[:4]
                )
                in scope.fiscal_years
            )
        ]

    def filing_scope(self, accession: str):
        filing = self.deps.store.get_filing(accession)
        if not filing or not any(c.cik == filing.cik for c in self.companies.values()):
            raise ValueError("Filing not found in selected companies; call list_filings first")
        if (
            (self.deps.scope.strict and filing.form.removesuffix("/A") not in self.deps.scope.forms)
            or (
                self.deps.scope.strict
                and filing.cik not in {c.cik for c in self.strict_scope.companies}
            )
            or (
                self.deps.scope.strict
                and (filing.report_date or filing.filing_date).year
                not in self.strict_scope.fiscal_years
            )
        ):
            raise ValueError("Filing is outside the selected form/year scope")
        return filing

    def error_record(self, exc):
        message = str(exc)
        code = "invalid_arguments"
        if "403" in message:
            code = "access_denied"
        elif "404" in message:
            code = "not_found"
        elif "429" in message:
            code = "rate_limited"
        elif re.search(r"\b50[0234]\b", message):
            code = "upstream_unavailable"
        elif "timeout" in message.lower() or isinstance(exc, TimeoutError):
            code = "timeout"
        return {
            "type": type(exc).__name__,
            "message": message[:1000],
            "code": code,
            "retryable": code in {"rate_limited", "timeout", "upstream_unavailable"},
            "instruction": "Do not repeat identical failed calls; "
            "change resource or return supported partial findings.",
        }

    def register(self, agent, run_context, deps_type):
        def traced(func):
            @functools.wraps(func)
            async def wrapped(ctx, *args, **kwargs):
                self.calls += 1
                self.deps.tool_context["research_calls"] = self.calls
                call_id = uuid4().hex
                name = func.__name__
                fingerprint = name + json.dumps([args, kwargs], sort_keys=True, default=str)
                self.emit(
                    "status",
                    {
                        "phase": name,
                        "tool_call_id": call_id,
                        "state": "active",
                        "message": f"正在调用 {name}",
                        "detail": kwargs,
                    },
                )
                try:
                    if self.failures.get(fingerprint, 0) >= 2:
                        raise ValueError(
                            "Repeated failing call blocked; change resource "
                            "or report the coverage gap"
                        )
                    if (
                        self.calls + self.deps.tool_context.get("file_calls", 0)
                        > self.settings.agent_max_tool_calls
                    ):
                        raise ValueError(
                            "Research tool-call budget exhausted; return partial findings"
                        )
                    result = await func(ctx, *args, **kwargs)
                    if not isinstance(result, dict):
                        result = {"result": result}
                    failed = result.get("status") in {"rejected", "failed"}
                    self.emit(
                        "status",
                        {
                            "phase": name,
                            "tool_call_id": call_id,
                            "state": "warning" if failed else "complete",
                            "message": result.get("error", f"{name} 已完成"),
                            "detail": self.summary(result),
                        },
                    )
                    return {"tool_call_id": call_id, "status": "succeeded", **result}
                except Exception as exc:
                    self.failures[fingerprint] = self.failures.get(fingerprint, 0) + 1
                    error = self.error_record(exc)
                    self.emit(
                        "status",
                        {
                            "phase": name,
                            "tool_call_id": call_id,
                            "state": "warning",
                            "message": error["message"],
                            "detail": error,
                        },
                    )
                    return {"tool_call_id": call_id, "status": "failed", "error": error}

            wrapped.__annotations__["ctx"] = run_context[deps_type]
            agent.tool(wrapped)
            return wrapped

        @traced
        async def resolve_companies(ctx: Any, query: str) -> dict:
            """Resolve by ticker or company name ONLY, e.g. NVDA; not a descriptive sentence."""
            if not query.strip() or len(query) > 200:
                raise ValueError("Provide a company name or ticker")
            companies = self.deps.store.search_companies(query)
            if not companies:
                companies = await self.client.search_companies(query)
            for company in companies:
                if self.deps.scope.strict and company.ticker not in {
                    c.ticker for c in self.strict_scope.companies
                }:
                    continue
                self.deps.store.upsert_company(company)
                self.companies[company.ticker] = company
            candidates = [
                c.model_dump(mode="json") for c in companies if c.ticker in self.companies
            ]
            return {
                "companies": candidates,
                "ambiguity": len(candidates) > 1,
                "instruction": "Choose exact ticker; resolution does not prove sector membership",
                "empty_reason": "No match: retry with ticker only or exact company name"
                if not candidates
                else None,
            }

        @traced
        async def search_web(ctx: Any, query: str, limit: int = 8) -> dict:
            """Discover industry definitions and issuer leads. Read pages before citing snippets."""
            return await self.web.search(query, limit)

        @traced
        async def read_web(ctx: Any, url: str, start: int = 0, limit: int = 8) -> dict:
            """Read public HTTPS and register snapshot-backed citations. Private URLs forbidden."""
            if start < 0 or not 1 <= limit <= 20:
                raise ValueError("start >= 0, limit 1..20 required")
            if self.failures.get("url:" + url, 0):
                raise ValueError(
                    "Previously inaccessible URL blocked in this run; use another declared source"
                )
            try:
                page = await self.web.read(url)
            except Exception as exc:
                if self.error_record(exc)["code"] in {"access_denied", "not_found"}:
                    self.failures["url:" + url] = 1
                raise
            from datetime import datetime

            source = SourceRef(
                source_type="web",
                cik="",
                ticker="",
                form="web",
                accession_no="",
                filing_date=datetime.fromisoformat(page["fetched_at"]).date(),
                sec_url=page["url"],
                content_sha256=page["content_sha256"],
                title=page["title"],
            )
            citations = []
            for index in range(start, min(start + limit, len(page["paragraphs"]))):
                text = page["paragraphs"][index]
                locator = TextLocator(
                    section=page["title"] or "Web page",
                    paragraph_index=index,
                    exact_quote=text,
                    quote_sha256=sha256(text.encode()).hexdigest(),
                )
                citations.append(
                    Citation(
                        citation_id=Citation.stable_id(source, locator),
                        source=source,
                        locator=locator,
                    )
                )
            self.evidence(citations)
            return {
                "url": page["url"],
                "title": page["title"],
                "evidence": [c.model_dump(mode="json") for c in citations],
                "snapshot_sha256": page["content_sha256"],
                "next_start": start + limit if start + limit < len(page["paragraphs"]) else None,
                "empty_reason": "no_readable_paragraphs" if not citations else None,
            }

        @traced
        async def set_research_sample(ctx: Any, members: list[dict[str, Any]]) -> dict:
            """Record non-exhaustive sample members with ticker, reason and citation_ids."""
            if not 1 <= len(members) <= 30:
                raise ValueError("Choose 1..30 sample members")
            sample = []
            for member in members:
                ticker = str(member.get("ticker", "")).upper()
                ids = member.get("citation_ids", [])
                reason = member.get("reason", "")
                if ticker not in self.companies or not reason or not ids:
                    raise ValueError("Each member needs a resolved ticker, reason and citations")
                if set(ids) - self.deps.allowed_citation_ids:
                    raise ValueError("Sample citations must be registered in this run")
                if self.deps.scope.strict and ticker not in {
                    c.ticker for c in self.strict_scope.companies
                }:
                    raise ValueError("Sample exceeds explicitly strict scope")
                sample.append(
                    {
                        "company": self.companies[ticker].model_dump(mode="json"),
                        "reason": reason,
                        "citation_ids": ids,
                    }
                )
            self.deps.scope = self.deps.scope.model_copy(
                update={
                    "companies": [Company.model_validate(item["company"]) for item in sample],
                }
            )
            result = {
                "members": sample,
                "exhaustive": False,
                "verification": "registered_sources_not_semantic_membership_proof",
            }
            thread_id = self.deps.tool_context.get("thread_id")
            if thread_id:
                from finagent.workspace import db

                with db().transaction() as connection:
                    connection.execute(
                        "INSERT INTO research_samples(id,thread_id,data_json) VALUES (?,?,?)",
                        (uuid4().hex, thread_id, json.dumps(result, ensure_ascii=False)),
                    )
            self.emit("sample", result)
            return result

        @traced
        async def list_filings(
            ctx: Any,
            tickers: list[str] | None = None,
            years: list[int] | None = None,
            offset: int = 0,
            limit: Annotated[int, Field(ge=1, le=50)] = 20,
            forms: list[str] | None = None,
            filed_from: str = "",
            filed_to: str = "",
        ) -> dict:
            """Find SEC filing accessions in scope. Does not download all filing text."""
            if years is None:
                years = []
            if tickers is None:
                tickers = []
            scope = self.scope(tickers, years)
            if forms:
                supported = {"10-K", "10-Q", "8-K"}
                requested_forms = {f.upper().removesuffix("/A") for f in forms}
                if requested_forms - supported:
                    raise ValueError("Supported forms: 10-K, 10-Q, 8-K")
                if scope.strict and requested_forms - set(scope.forms):
                    raise ValueError("Forms exceed explicitly strict scope")
                scope = scope.model_copy(update={"forms": sorted(requested_forms)})
            lower = date.fromisoformat(filed_from) if filed_from else None
            upper = date.fromisoformat(filed_to) if filed_to else None
            if offset < 0 or not 1 <= limit <= 50:
                raise ValueError("offset >= 0 and limit 1..50 required")
            warnings = []
            for company in scope.companies:
                try:
                    for filing in await self.client.list_filings(company, scope):
                        self.deps.store.upsert_filing(filing)
                except Exception as exc:
                    warnings.append(f"{company.ticker}: cached directory fallback: {exc}")
            filings = self.cached_filings(scope)
            filings = [
                f
                for f in filings
                if (not lower or f.filing_date >= lower) and (not upper or f.filing_date <= upper)
            ]
            return {
                "filings": [f.model_dump(mode="json") for f in filings[offset : offset + limit]],
                "next_offset": offset + limit if offset + limit < len(filings) else None,
                "warnings": warnings,
                "period_policy": "reportDate calendar year; non-calendar FY may differ",
                "coverage": "directory_metadata_only; 8-K years use filing dates; "
                "historical shards loaded only for requested years",
            }

        @traced
        async def list_filing_documents(ctx: Any, accession: str) -> dict:
            """Discover SEC primary document and declared exhibits (including earnings releases)."""
            filing = self.filing_scope(accession)
            return {"documents": await self.client.list_documents(filing), "accession": accession}

        @traced
        async def read_filing_document(
            ctx: Any, accession: str, filename: str, query: str = "", start: int = 0, limit: int = 8
        ) -> dict:
            """Read declared HTML/text SEC exhibit, with parent accession, original URL and hash."""
            filing = self.filing_scope(accession)
            if start < 0 or not 1 <= limit <= 20:
                raise ValueError("start >= 0; limit 1..20")
            key = accession + ":" + filename
            if key not in self.document_registry:
                body = await self.client.fetch_document(filing, filename)
                company = next(c for c in self.companies.values() if c.cik == filing.cik)
                url = str(filing.sec_url).rsplit("/", 1)[0] + "/" + filename
                selected = filing.model_copy(
                    update={
                        "sec_url": url,
                        "primary_document": filename,
                        "content_sha256": sha256(body.encode()).hexdigest(),
                    }
                )
                chunks = chunk_filing(selected, company.ticker, body)
                self.document_registry[key] = selected, company, chunks
            selected, company, chunks = self.document_registry[key]
            terms = [t.lower() for t in re.findall(r"[A-Za-z]{2,}", query)]
            if terms:
                matching = {
                    i for i, c in enumerate(chunks) if any(t in c.text.lower() for t in terms)
                }
                # Include following explanatory list/footnote context, not snippets alone.
                indices = sorted(
                    {j for i in matching for j in range(max(0, i - 1), min(len(chunks), i + 3))}
                )
                chunks = [chunks[i] for i in indices]
            citations = []
            for chunk in chunks[start : start + limit]:
                source = SourceRef(
                    source_type="filing_text",
                    cik=company.cik,
                    ticker=company.ticker,
                    form=filing.form,
                    accession_no=accession,
                    filing_date=filing.filing_date,
                    primary_document=filename,
                    sec_url=selected.sec_url,
                    content_sha256=selected.content_sha256,
                    title=filename,
                )
                locator = TextLocator(
                    section=chunk.section,
                    paragraph_index=chunk.paragraph_index,
                    dom_path=chunk.dom_path,
                    exact_quote=chunk.text,
                    quote_sha256=sha256(chunk.text.encode()).hexdigest(),
                )
                citations.append(
                    Citation(
                        citation_id=Citation.stable_id(source, locator),
                        source=source,
                        locator=locator,
                    )
                )
            self.evidence(citations)
            return {
                "evidence": [c.model_dump(mode="json") for c in citations],
                "next_start": start + limit if len(chunks) > start + limit else None,
                "document": selected.model_dump(mode="json"),
            }

        @traced
        async def compute_financial(
            ctx: Any,
            expression: str,
            inputs: dict[str, str],
            output_unit: str = "ratio",
            decimal_places: Annotated[int, Field(ge=0, le=4)] = 2,
        ) -> dict:
            """Calculate + - * / over named numeric citation IDs. Constants are method parameters.

            For growth use (current/prior-1)*100, unit percent; DPO may use 365.
            Use output_unit='USD' for currency sums/differences, 'percentage_points' for
            subtracting percentage margins. Inputs must have value fields, not just text quotes.
            Returns a registered derived citation and replayable input/formula record, not shell.
            display.text is rounded for prose (default 2 decimals, maximum 4); USD uses
            million/billion when appropriate. Bind the display span to this citation ID.
            Further calculations use citation IDs, never rounded display values.
            """
            from finagent.compute.display import display_result
            from finagent.compute.evidence import compute_evidence

            if type(decimal_places) is not int or not 0 <= decimal_places <= 4:
                raise ValueError("Display decimal places must be an integer between 0 and 4")
            citation, record = compute_evidence(self.deps, expression, inputs, output_unit)
            self.evidence([citation])
            return {
                "display": display_result(citation.value.amount, output_unit, decimal_places),
                "citation": citation.model_dump(mode="json"),
                "computation": record,
            }

        @traced
        async def search_filings(
            ctx: Any,
            query: str,
            tickers: list[str] | None = None,
            years: list[int] | None = None,
            accession: str = "",
            offset: int = 0,
            limit: Annotated[int, Field(ge=1, le=20)] = 8,
        ) -> dict:
            """Search filing text repeatedly by topic/company/year. Page through evidence."""
            if years is None:
                years = []
            if tickers is None:
                tickers = []
            scope = self.scope(tickers, years)
            if not query.strip() or offset < 0 or not 1 <= limit <= 20:
                raise ValueError("Nonempty query, offset >= 0, limit 1..20 required")
            if offset + limit > 500:
                raise ValueError("Refine query rather than paging beyond 500 candidates")
            if accession:
                filing = self.filing_scope(accession)
                if filing.cik not in {c.cik for c in scope.companies}:
                    raise ValueError("Accession does not match requested company filter")
                if not self.deps.store.has_filing_content(accession):
                    company = next(c for c in scope.companies if c.cik == filing.cik)
                    html = await self.client.fetch_filing_html(filing)
                    self.deps.store.upsert_filing(filing, raw_html=html)
                    self.deps.store.upsert_chunks(chunk_filing(filing, company.ticker, html))
            else:
                await self.indexed(scope)
            retriever = FilingRetriever(self.deps.store)
            # Fetch an extra candidate to make pagination truthful, not a global research cap.
            from finagent.retrieval.query import OVERVIEW_TERMS, expand_query

            terms = expand_query(query) or OVERVIEW_TERMS
            expression = " OR ".join(f'"{t.replace(chr(34), "")}"' for t in terms)
            hits = []
            for company in scope.companies:
                hits.extend(
                    retriever._search_company(
                        expression,
                        company.cik,
                        scope,
                        offset + limit + 1,
                        accession=accession,
                    )
                )
            hits.sort(key=lambda h: h.score, reverse=True)
            page = hits[offset : offset + limit]
            self.evidence([h.citation for h in page])
            return {
                "evidence": [h.model_dump(mode="json") for h in page],
                "next_offset": offset + limit if len(hits) > offset + limit else None,
                "empty_reason": "no_keyword_match" if not page else None,
                "coverage": "Broad search indexes at most 12 filing bodies per company per call; "
                "use list_filings and an exact accession for remaining documents. Not exhaustive.",
            }

        @traced
        async def read_filing(
            ctx: Any, accession: str, start: int = 0, limit: int = 8, section: str = ""
        ) -> dict:
            """Read actual consecutive filing paragraphs, optionally filtered by section."""
            filing = self.filing_scope(accession)
            if start < 0 or not 1 <= limit <= 20:
                raise ValueError("start >= 0 and limit 1..20 required")
            company = next(c for c in self.companies.values() if c.cik == filing.cik)
            if not self.deps.store.has_filing_content(accession):
                html = await self.client.fetch_filing_html(filing)
                self.deps.store.upsert_filing(filing, raw_html=html)
                self.deps.store.upsert_chunks(chunk_filing(filing, company.ticker, html))
            with self.deps.store.connect() as connection:
                rows = connection.execute(
                    "SELECT * FROM chunks WHERE accession_no=? AND paragraph_index>=? "
                    "AND (?='' OR instr(lower(section),lower(?))>0) "
                    "ORDER BY paragraph_index LIMIT ?",
                    (accession, start, section, section, limit + 1),
                ).fetchall()
            citations = []
            for row in rows[:limit]:
                source = SourceRef(
                    source_type="filing_text",
                    cik=company.cik,
                    ticker=company.ticker,
                    form=filing.form,
                    accession_no=accession,
                    filing_date=filing.filing_date,
                    primary_document=filing.primary_document,
                    sec_url=filing.sec_url,
                )
                locator = TextLocator(
                    section=row["section"],
                    paragraph_index=row["paragraph_index"],
                    dom_path=row["dom_path"],
                    exact_quote=row["text"],
                    quote_sha256=sha256(row["text"].encode()).hexdigest(),
                )
                citations.append(
                    Citation(
                        citation_id=Citation.stable_id(source, locator),
                        source=source,
                        locator=locator,
                    )
                )
            self.evidence(citations)
            return {
                "evidence": [c.model_dump(mode="json") for c in citations],
                "next_start": rows[limit]["paragraph_index"] if len(rows) > limit else None,
            }

        @traced
        async def discover_financial_periods(
            ctx: Any, tickers: list[str], count: int = 2, end_years: list[int] | None = None
        ) -> dict:
            """Discover latest complete FY revenue periods with actual dates, not default years."""
            from finagent.data.facts import FactResolver

            if not 1 <= count <= 5:
                raise ValueError("count must be 1..5")
            scope = self.scope(tickers)
            resolver = FactResolver(self.deps.store)
            result = []
            for company in scope.companies:
                warning = None
                try:
                    self.deps.store.upsert_facts(await self.client.fetch_facts(company))
                except Exception as exc:
                    warning = f"Cached data only: {exc}"
                years = sorted(
                    {
                        f.fiscal_year
                        for f in self.deps.store.list_facts(company.cik)
                        if f.fiscal_year is not None
                    },
                    reverse=True,
                )
                if scope.strict:
                    years = [y for y in years if y in scope.fiscal_years]
                periods = []
                if end_years:
                    if scope.strict and set(end_years) - set(scope.fiscal_years):
                        raise ValueError("End years exceed explicitly strict scope")
                    # Explicit end-year lookup is separate from issuer FY labels.
                    observations = [
                        f
                        for f in self.deps.store.list_facts(company.cik)
                        if f.concept in METRIC_CONCEPTS["revenue"]
                        and f.start
                        and 300 <= (f.end - f.start).days <= 400
                        and f.end.year in end_years
                        and not f.dimensions
                    ]
                    grouped = {}
                    for f in observations:
                        key = (f.start, f.end)
                        grouped.setdefault(key, []).append(f)
                    for (start_date, end_date), candidates in sorted(grouped.items(), reverse=True):
                        candidates.sort(key=lambda f: (f.filed, f.accession_no))
                        f = (
                            candidates[0]
                            if scope.restatement_policy == "as_reported"
                            else candidates[-1]
                        )
                        citation = resolver._citation(company, f)
                        self.evidence([citation])
                        periods.append(
                            {
                                "period": f"{f.fiscal_year}-FY",
                                "start": str(start_date),
                                "end": str(end_date),
                                "filed": str(f.filed),
                                "citation_ids": [citation.citation_id],
                                "warning": "period field is submitting FY label; "
                                "not inferred issuer FY; "
                                "actual dates authoritative",
                            }
                        )
                    result.append(
                        {"ticker": company.ticker, "periods": periods[:count], "warning": warning}
                    )
                    continue
                for year in years:
                    value = resolver.resolve(company, "revenue", f"{year}-FY")
                    if value is None:
                        continue
                    self.evidence(value.citations)
                    locator = value.citations[0].locator
                    periods.append(
                        {
                            "period": f"{year}-FY",
                            "start": str(locator.start),
                            "end": str(locator.end),
                            "filed": str(value.citations[0].source.filing_date),
                            "citation_ids": [c.citation_id for c in value.citations],
                        }
                    )
                    if len(periods) == count:
                        break
                result.append({"ticker": company.ticker, "periods": periods, "warning": warning})
            return {
                "companies": result,
                "policy": (
                    "Complete annual revenue observations using current FY resolver; "
                    "verify actual dates. Not all metrics guaranteed."
                ),
            }

        @traced
        async def get_financial_data(
            ctx: Any, metrics: list[str], periods: list[str], tickers: list[str] | None = None
        ) -> dict:
            """Get only requested mapped financial metrics/periods, independently verified.

            Use YYYY-FY or YYYY-Q1..Q4. Missing is not zero. Returns numeric citation IDs.
            """
            if tickers is None:
                tickers = []
            scope = self.scope(tickers)
            metrics = [
                {
                    "capital_expenditures": "capital_expenditure",
                    "capex": "capital_expenditure",
                    "cogs": "cost_of_revenue",
                    "cost_of_goods_sold": "cost_of_revenue",
                    "inventories": "inventory",
                    "net_cash_operating": "operating_cash_flow",
                    "net_cash_investing": "investing_cash_flow",
                    "net_cash_financing": "financing_cash_flow",
                }.get(m, m)
                for m in metrics
            ]
            if (
                not metrics
                or set(metrics) - set(METRIC_CONCEPTS)
                or len(periods) > 40
                or not periods
            ):
                raise ValueError(f"Choose mapped metrics {list(METRIC_CONCEPTS)} and 1..40 periods")
            years = []
            for period in periods:
                from finagent.data.facts import parse_period

                years.append(parse_period(period)[0])
                if scope.strict and parse_period(period)[0] not in scope.fiscal_years:
                    raise ValueError("Financial period is outside selected years")
            scope = scope.model_copy(update={"fiscal_years": sorted(set(years))})
            warnings = []
            for company in scope.companies:
                try:
                    facts = await self.client.fetch_facts(company)
                    self.deps.store.upsert_facts(facts)
                except Exception as exc:
                    warnings.append(f"{company.ticker}: cached facts fallback: {exc}")
            table = verify_table(
                build_comparison(self.deps.store, scope, metrics, periods), self.deps.store
            )
            ids = {
                i
                for row in table.rows
                if row.cell.verification.status.value == "verified"
                for i in row.cell.source_citation_ids
            }
            citations = list(self.deps.store.get_citations(list(ids)).values())
            self.evidence(citations)
            result = table.model_dump(mode="json")
            result["warnings"].extend(warnings)
            result["metric_catalog"] = list(METRIC_CONCEPTS)
            result["form_policy"] = "facts include 10-K/10-Q; numeric resolver is not form-filtered"
            if self.deps.tool_context.get("thread_id"):
                from finagent.workspace import session_files

                name = f"financial-data-{uuid4().hex[:12]}.json"
                metadata = session_files(self.deps.tool_context["thread_id"]).write(
                    name,
                    json.dumps(result, ensure_ascii=False).encode(),
                    text_only=True,
                )
                result["data_file"] = metadata
            return result

        @traced
        async def list_financial_concepts(
            ctx: Any, ticker: str, query: str = "", offset: int = 0, limit: int = 30
        ) -> dict:
            """Discover concepts. Unknown issuer-specific tags are not comparable metrics."""
            scope = self.scope([ticker])
            if offset < 0 or not 1 <= limit <= 100:
                raise ValueError("offset >= 0, limit 1..100 required")
            try:
                self.deps.store.upsert_facts(await self.client.fetch_facts(scope.companies[0]))
            except Exception:
                if not self.deps.store.list_facts(scope.companies[0].cik):
                    raise
            with self.deps.store.connect() as connection:
                rows = connection.execute(
                    "SELECT DISTINCT taxonomy,concept,unit FROM facts WHERE cik=? "
                    "AND instr(lower(concept),lower(?))>0 "
                    "ORDER BY taxonomy,concept,unit LIMIT ? OFFSET ?",
                    (scope.companies[0].cik, query, limit + 1, offset),
                ).fetchall()
            return {
                "concepts": [dict(row) for row in rows[:limit]],
                "mapped_metrics": METRIC_CONCEPTS,
                "next_offset": offset + limit if len(rows) > limit else None,
            }

        @traced
        async def inspect_evidence(ctx: Any, citation_ids: list[str]) -> dict:
            """Load current-scope registered evidence, including a citation from prior turns."""
            if not 1 <= len(citation_ids) <= 30:
                raise ValueError("Request 1..30 citations")
            citations = self.deps.store.get_citations(citation_ids)
            if len(citations) != len(set(citation_ids)):
                raise ValueError("Unknown citation ID")
            for citation in citations.values():
                if citation.source.source_type == "web":
                    continue
                if not self.deps.scope.strict:
                    for company in self.deps.store.search_companies(citation.source.ticker):
                        self.companies[company.ticker] = company
                if citation.source.cik not in {c.cik for c in self.companies.values()}:
                    raise ValueError("Evidence company is outside scope")
                year = (
                    citation.locator.end.year
                    if hasattr(citation.locator, "end")
                    else (
                        self.filing_scope(citation.source.accession_no).report_date
                        or self.filing_scope(citation.source.accession_no).filing_date
                    ).year
                )
                if self.deps.scope.strict and year not in self.strict_scope.fiscal_years:
                    raise ValueError("Evidence period is outside scope")
            self.evidence(list(citations.values()))
            return {"evidence": [c.model_dump(mode="json") for c in citations.values()]}

        @traced
        async def update_plan(
            ctx: Any, steps: list[str], completed: list[int] | None = None
        ) -> dict:
            """Save a short public research checklist, not private chain-of-thought."""
            if completed is None:
                completed = []
            if len(steps) > 20 or any(len(step) > 300 for step in steps):
                raise ValueError("At most 20 short plan steps")
            if any(i < 0 or i >= len(steps) for i in completed):
                raise ValueError("completed uses ZERO-based indices 0..len(steps)-1")
            if (
                self.deps.tool_context.get("requires_report")
                and len(completed) == len(steps)
                and not any(a["data"].get("report") for a in self.deps.generated_artifacts)
            ):
                raise ValueError("Cannot mark report plan complete before publish_report succeeds")
            result = {"steps": steps, "completed": completed}
            self.emit("plan", result)
            return result

        @traced
        async def execution_capabilities(ctx: Any) -> dict:
            """Check whether safely isolated Python/shell execution is available."""
            from finagent.execution import capabilities

            return capabilities()

        @traced
        async def run_python(
            ctx: Any, code: str, input_files: list[str] | None = None, timeout_seconds: int = 30
        ) -> dict:
            """Execute Python only when a safe backend is ready. Never runs on the host."""
            from finagent.execution import rejected_execution

            if input_files is None:
                input_files = []
            return rejected_execution("python")

        @traced
        async def run_shell(
            ctx: Any, command: str, input_files: list[str] | None = None, timeout_seconds: int = 30
        ) -> dict:
            """Execute shell only when a safe backend is ready. Never runs on the host."""
            from finagent.execution import rejected_execution

            if input_files is None:
                input_files = []
            return rejected_execution("shell")

    @staticmethod
    def summary(result):
        # Persistent tool cards retain useful metadata, not the entire large data payload.
        return {
            key: value
            for key, value in result.items()
            if key
            in {
                "next_offset",
                "next_start",
                "warnings",
                "data_file",
                "steps",
                "completed",
                "error",
                "available",
                "reason",
                "status",
                "provider",
                "warning",
                "snapshot_sha256",
                "search_snapshot_sha256",
                "empty_reason",
            }
        } | {
            "evidence_count": len(result.get("evidence", [])),
            "rows": len(result.get("rows", [])),
            "filings": len(result.get("filings", [])),
            "results": len(result.get("results", [])),
            "companies": len(result.get("companies", [])),
            "members": len(result.get("members", [])),
        }
