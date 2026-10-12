from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from hashlib import sha256
from html.parser import HTMLParser

from finagent.data.base import DataSource
from finagent.schemas import Filing, FilingChunk, ResearchScope
from finagent.storage import SQLiteStore

ProgressCallback = Callable[[str], Awaitable[None]]
BLOCK_TAGS = {"p", "div", "li", "h1", "h2", "h3", "h4", "h5", "h6"}
HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
IGNORED_TAGS = {"script", "style", "noscript", "ix:header"}
VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source"}


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.replace("\xa0", " ")).strip()


class _BlockParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.path: list[str] = []
        self.blocks: list[dict[str, object]] = []
        self.completed: list[tuple[str, str, str]] = []
        self.ignored_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag not in VOID_TAGS:
            self.path.append(tag)
        if tag in IGNORED_TAGS:
            self.ignored_depth += 1
            return
        if self.ignored_depth:
            return
        if tag in BLOCK_TAGS:
            if self.blocks:
                self.blocks[-1]["has_block_child"] = True
            self.blocks.append(
                {
                    "tag": tag,
                    "text": [],
                    "path": "/".join(self.path[-6:]),
                    "has_block_child": False,
                }
            )

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in IGNORED_TAGS and self.ignored_depth:
            self.ignored_depth -= 1
        elif not self.ignored_depth and tag in BLOCK_TAGS and self.blocks:
            block = self.blocks.pop()
            if block["tag"] == tag:
                text = normalize_text(" ".join(block["text"]))  # type: ignore[arg-type]
                is_leaf = not bool(block["has_block_child"])
                if tag != "div" or is_leaf:
                    self.completed.append((tag, text, str(block["path"])))
        if tag in self.path:
            reverse_index = self.path[::-1].index(tag)
            del self.path[len(self.path) - reverse_index - 1 :]

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        return

    def handle_data(self, data: str) -> None:
        if self.ignored_depth:
            return
        for block in self.blocks:
            text = block["text"]
            assert isinstance(text, list)
            text.append(data)


def chunk_filing(filing: Filing, ticker: str, html: str) -> list[FilingChunk]:
    parser = _BlockParser()
    parser.feed(html)
    section = "Filing"
    chunks: list[FilingChunk] = []
    paragraph_index = 0
    for tag, text, dom_path in parser.completed:
        if tag in HEADING_TAGS and 2 <= len(text) <= 180:
            section = text
            continue
        if len(text) < 60:
            continue
        for offset in range(0, len(text), 1_600):
            fragment = text[offset : offset + 1_800]
            if len(fragment) < 60:
                continue
            material = f"{filing.accession_no}|{paragraph_index}|{fragment}"
            chunk_id = sha256(material.encode()).hexdigest()
            chunks.append(
                FilingChunk(
                    chunk_id=chunk_id,
                    cik=filing.cik,
                    ticker=ticker,
                    accession_no=filing.accession_no,
                    form=filing.form,
                    filing_date=filing.filing_date,
                    section=section,
                    paragraph_index=paragraph_index,
                    text=fragment,
                    dom_path=dom_path,
                    sec_url=filing.sec_url,
                )
            )
            paragraph_index += 1
    return chunks


class IngestionService:
    def __init__(self, store: SQLiteStore, source: DataSource) -> None:
        self.store = store
        self.source = source

    async def ingest_scope(
        self,
        scope: ResearchScope,
        progress: ProgressCallback | None = None,
    ) -> dict[str, int]:
        totals = {"companies": 0, "filings": 0, "chunks": 0, "facts": 0}
        for company in scope.companies:
            self.store.upsert_company(company)
            totals["companies"] += 1
            if progress:
                await progress(f"正在读取 {company.ticker} 的 SEC 数据")
            facts = await self.source.fetch_facts(company)
            totals["facts"] += self.store.upsert_facts(facts)
            filings = await self.source.list_filings(company, scope)
            for filing in filings:
                if self.store.has_filing_content(filing.accession_no):
                    continue
                html = await self.source.fetch_filing_html(filing)
                filing.content_sha256 = sha256(html.encode()).hexdigest()
                self.store.upsert_filing(filing, raw_html=html)
                chunks = chunk_filing(filing, company.ticker, html)
                totals["filings"] += 1
                totals["chunks"] += self.store.upsert_chunks(chunks)
                if progress:
                    await progress(f"已索引 {company.ticker} {filing.form} {filing.filing_date}")
        return totals
