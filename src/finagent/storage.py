from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from threading import RLock
from typing import Any

from finagent.schemas import (
    Citation,
    Company,
    FactRecord,
    Filing,
    FilingChunk,
    UserProfile,
    XbrlLocator,
)

SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS companies (
    cik TEXT PRIMARY KEY,
    ticker TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    aliases_json TEXT NOT NULL DEFAULT '[]',
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS filings (
    accession_no TEXT PRIMARY KEY,
    cik TEXT NOT NULL REFERENCES companies(cik),
    form TEXT NOT NULL,
    filing_date TEXT NOT NULL,
    report_date TEXT,
    primary_document TEXT,
    sec_url TEXT NOT NULL,
    content_sha256 TEXT,
    raw_html TEXT,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_filings_scope
ON filings(cik, form, report_date, filing_date);

CREATE TABLE IF NOT EXISTS facts (
    fact_id TEXT PRIMARY KEY,
    cik TEXT NOT NULL REFERENCES companies(cik),
    ticker TEXT NOT NULL,
    taxonomy TEXT NOT NULL,
    concept TEXT NOT NULL,
    unit TEXT NOT NULL,
    value TEXT NOT NULL,
    start TEXT,
    end TEXT NOT NULL,
    fiscal_year INTEGER,
    fiscal_period TEXT,
    form TEXT NOT NULL,
    accession_no TEXT NOT NULL,
    filed TEXT NOT NULL,
    frame TEXT,
    dimensions_json TEXT NOT NULL DEFAULT '{}',
    UNIQUE(cik, taxonomy, concept, unit, start, end, dimensions_json, accession_no)
);

CREATE INDEX IF NOT EXISTS idx_facts_lookup
ON facts(cik, concept, end, filed);

CREATE TABLE IF NOT EXISTS chunks (
    rowid INTEGER PRIMARY KEY AUTOINCREMENT,
    chunk_id TEXT NOT NULL UNIQUE,
    cik TEXT NOT NULL REFERENCES companies(cik),
    ticker TEXT NOT NULL,
    accession_no TEXT NOT NULL REFERENCES filings(accession_no),
    form TEXT NOT NULL,
    filing_date TEXT NOT NULL,
    section TEXT NOT NULL,
    paragraph_index INTEGER NOT NULL,
    text TEXT NOT NULL,
    dom_path TEXT,
    sec_url TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_chunks_scope
ON chunks(cik, form, filing_date);

CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
    text,
    section,
    ticker,
    content='chunks',
    content_rowid='rowid',
    tokenize='unicode61 remove_diacritics 2'
);

CREATE TRIGGER IF NOT EXISTS chunks_ai AFTER INSERT ON chunks BEGIN
  INSERT INTO chunks_fts(rowid, text, section, ticker)
  VALUES (new.rowid, new.text, new.section, new.ticker);
END;

CREATE TRIGGER IF NOT EXISTS chunks_ad AFTER DELETE ON chunks BEGIN
  INSERT INTO chunks_fts(chunks_fts, rowid, text, section, ticker)
  VALUES('delete', old.rowid, old.text, old.section, old.ticker);
END;

CREATE TRIGGER IF NOT EXISTS chunks_au AFTER UPDATE ON chunks BEGIN
  INSERT INTO chunks_fts(chunks_fts, rowid, text, section, ticker)
  VALUES('delete', old.rowid, old.text, old.section, old.ticker);
  INSERT INTO chunks_fts(rowid, text, section, ticker)
  VALUES (new.rowid, new.text, new.section, new.ticker);
END;

CREATE TABLE IF NOT EXISTS citations (
    citation_id TEXT PRIMARY KEY,
    citation_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS profiles (
    profile_id TEXT PRIMARY KEY,
    profile_json TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS ingestion_runs (
    run_id TEXT PRIMARY KEY,
    scope_json TEXT NOT NULL,
    status TEXT NOT NULL,
    message TEXT,
    started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TEXT
);

CREATE TABLE IF NOT EXISTS source_cache (
    url TEXT PRIMARY KEY,
    body TEXT NOT NULL,
    content_type TEXT NOT NULL,
    content_sha256 TEXT NOT NULL,
    fetched_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS source_snapshots (
    url TEXT NOT NULL,
    content_sha256 TEXT NOT NULL,
    body TEXT NOT NULL,
    content_type TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    PRIMARY KEY(url, content_sha256)
);
"""


class SQLiteStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self.initialize()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = NORMAL")
        return connection

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self._lock, self.connect() as connection:
            try:
                yield connection
                connection.commit()
            except Exception:
                connection.rollback()
                raise

    def initialize(self) -> None:
        with self.transaction() as connection:
            connection.executescript(SCHEMA)

    def upsert_company(self, company: Company) -> None:
        with self.transaction() as connection:
            connection.execute(
                """
                INSERT INTO companies(cik, ticker, name, aliases_json)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(cik) DO UPDATE SET
                    ticker=excluded.ticker,
                    name=excluded.name,
                    aliases_json=excluded.aliases_json,
                    updated_at=CURRENT_TIMESTAMP
                """,
                (company.cik, company.ticker, company.name, json.dumps(company.aliases)),
            )

    def put_source_cache(self, url: str, body: str, content_type: str) -> None:
        from hashlib import sha256

        with self.transaction() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO source_snapshots "
                "(url,content_sha256,body,content_type,fetched_at) VALUES (?,?,?,?,?)",
                (
                    url,
                    sha256(body.encode()).hexdigest(),
                    body,
                    content_type,
                    datetime.now(UTC).isoformat(),
                ),
            )
            connection.execute(
                """
                INSERT INTO source_cache(url, body, content_type, content_sha256, fetched_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(url) DO UPDATE SET
                    body=excluded.body,
                    content_type=excluded.content_type,
                    content_sha256=excluded.content_sha256,
                    fetched_at=excluded.fetched_at
                """,
                (
                    url,
                    body,
                    content_type,
                    sha256(body.encode()).hexdigest(),
                    datetime.now(UTC).isoformat(),
                ),
            )

    def get_source_cache(self, url: str, max_age_seconds: int) -> str | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT body, fetched_at FROM source_cache WHERE url=?", (url,)
            ).fetchone()
        if row is None:
            return None
        fetched_at = datetime.fromisoformat(row["fetched_at"])
        age = (datetime.now(UTC) - fetched_at).total_seconds()
        return str(row["body"]) if age <= max_age_seconds else None

    def get_company(self, cik: str) -> Company | None:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM companies WHERE cik=?", (cik,)).fetchone()
        if row is None:
            return None
        return Company(
            cik=row["cik"],
            ticker=row["ticker"],
            name=row["name"],
            aliases=json.loads(row["aliases_json"]),
        )

    def search_companies(self, query: str, limit: int = 10) -> list[Company]:
        normalized = f"%{query.strip().upper()}%"
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM companies
                WHERE UPPER(ticker) LIKE ? OR UPPER(name) LIKE ? OR UPPER(aliases_json) LIKE ?
                ORDER BY CASE WHEN UPPER(ticker) = UPPER(?) THEN 0 ELSE 1 END, ticker
                LIMIT ?
                """,
                (normalized, normalized, normalized, query.strip(), limit),
            ).fetchall()
        return [
            Company(
                cik=row["cik"],
                ticker=row["ticker"],
                name=row["name"],
                aliases=json.loads(row["aliases_json"]),
            )
            for row in rows
        ]

    def upsert_filing(self, filing: Filing, raw_html: str | None = None) -> None:
        with self.transaction() as connection:
            connection.execute(
                """
                INSERT INTO filings(
                    accession_no, cik, form, filing_date, report_date,
                    primary_document, sec_url, content_sha256, raw_html
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(accession_no) DO UPDATE SET
                    content_sha256=COALESCE(excluded.content_sha256, filings.content_sha256),
                    raw_html=COALESCE(excluded.raw_html, filings.raw_html),
                    updated_at=CURRENT_TIMESTAMP
                """,
                (
                    filing.accession_no,
                    filing.cik,
                    filing.form,
                    filing.filing_date.isoformat(),
                    filing.report_date.isoformat() if filing.report_date else None,
                    filing.primary_document,
                    str(filing.sec_url),
                    filing.content_sha256,
                    raw_html,
                ),
            )

    def has_filing_content(self, accession_no: str) -> bool:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT raw_html IS NOT NULL AS available FROM filings WHERE accession_no=?",
                (accession_no,),
            ).fetchone()
        return bool(row and row["available"])

    def get_filing(self, accession_no: str) -> Filing | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM filings WHERE accession_no=?", (accession_no,)
            ).fetchone()
        if row is None:
            return None
        return Filing(
            cik=row["cik"],
            accession_no=row["accession_no"],
            form=row["form"],
            filing_date=date.fromisoformat(row["filing_date"]),
            report_date=date.fromisoformat(row["report_date"]) if row["report_date"] else None,
            primary_document=row["primary_document"],
            sec_url=row["sec_url"],
            content_sha256=row["content_sha256"],
        )

    def upsert_facts(self, facts: Sequence[FactRecord]) -> int:
        if not facts:
            return 0
        with self.transaction() as connection:
            connection.executemany(
                """
                INSERT INTO facts(
                    fact_id, cik, ticker, taxonomy, concept, unit, value, start, end,
                    fiscal_year, fiscal_period, form, accession_no, filed, frame, dimensions_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(fact_id) DO UPDATE SET value=excluded.value, filed=excluded.filed
                """,
                [
                    (
                        fact.identity(),
                        fact.cik,
                        fact.ticker,
                        fact.taxonomy,
                        fact.concept,
                        fact.unit,
                        str(fact.value),
                        fact.start.isoformat() if fact.start else None,
                        fact.end.isoformat(),
                        fact.fiscal_year,
                        fact.fiscal_period,
                        fact.form,
                        fact.accession_no,
                        fact.filed.isoformat(),
                        fact.frame,
                        json.dumps(fact.dimensions, sort_keys=True),
                    )
                    for fact in facts
                ],
            )
        return len(facts)

    def list_facts(
        self,
        cik: str,
        concepts: Sequence[str] | None = None,
        fiscal_years: Sequence[int] | None = None,
    ) -> list[FactRecord]:
        clauses = ["cik = ?"]
        parameters: list[Any] = [cik.zfill(10)]
        if concepts:
            clauses.append(f"concept IN ({','.join('?' for _ in concepts)})")
            parameters.extend(concepts)
        if fiscal_years:
            clauses.append(f"fiscal_year IN ({','.join('?' for _ in fiscal_years)})")
            parameters.extend(fiscal_years)
        query = f"SELECT * FROM facts WHERE {' AND '.join(clauses)} ORDER BY end, filed"
        with self.connect() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return [self._fact_from_row(row) for row in rows]

    def upsert_chunks(self, chunks: Sequence[FilingChunk]) -> int:
        if not chunks:
            return 0
        with self.transaction() as connection:
            connection.executemany(
                """
                INSERT INTO chunks(
                    chunk_id, cik, ticker, accession_no, form, filing_date,
                    section, paragraph_index, text, dom_path, sec_url
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(chunk_id) DO UPDATE SET
                    section=excluded.section, text=excluded.text, dom_path=excluded.dom_path
                """,
                [
                    (
                        chunk.chunk_id,
                        chunk.cik,
                        chunk.ticker,
                        chunk.accession_no,
                        chunk.form,
                        chunk.filing_date.isoformat(),
                        chunk.section,
                        chunk.paragraph_index,
                        chunk.text,
                        chunk.dom_path,
                        str(chunk.sec_url),
                    )
                    for chunk in chunks
                ],
            )
        return len(chunks)

    def register_citation(self, citation: Citation) -> Citation:
        with self.transaction() as connection:
            connection.execute(
                """
                INSERT INTO citations(citation_id, citation_json) VALUES (?, ?)
                ON CONFLICT(citation_id) DO UPDATE SET citation_json=excluded.citation_json
                """,
                (citation.citation_id, citation.model_dump_json()),
            )
        return citation

    def get_citation(self, citation_id: str) -> Citation | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT citation_json FROM citations WHERE citation_id=?", (citation_id,)
            ).fetchone()
        return Citation.model_validate_json(row["citation_json"]) if row else None

    def get_citations(self, citation_ids: Sequence[str]) -> dict[str, Citation]:
        return {
            citation_id: citation
            for citation_id in citation_ids
            if (citation := self.get_citation(citation_id)) is not None
        }

    def lookup_xbrl_value(self, citation: Citation) -> Decimal | None:
        locator = citation.locator
        if not isinstance(locator, XbrlLocator):
            return None
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT value FROM facts
                WHERE cik=? AND taxonomy=? AND concept=? AND unit=?
                  AND COALESCE(start, '')=? AND end=? AND accession_no=?
                  AND dimensions_json=?
                ORDER BY filed DESC LIMIT 1
                """,
                (
                    citation.source.cik,
                    locator.taxonomy,
                    locator.concept,
                    locator.unit,
                    locator.start.isoformat() if locator.start else "",
                    locator.end.isoformat(),
                    citation.source.accession_no,
                    json.dumps(locator.dimensions, sort_keys=True),
                ),
            ).fetchone()
        return Decimal(row["value"]) if row else None

    def put_profile(self, profile: UserProfile) -> UserProfile:
        with self.transaction() as connection:
            connection.execute(
                """
                INSERT INTO profiles(profile_id, profile_json) VALUES (?, ?)
                ON CONFLICT(profile_id) DO UPDATE SET
                    profile_json=excluded.profile_json, updated_at=CURRENT_TIMESTAMP
                """,
                (profile.profile_id, profile.model_dump_json()),
            )
        return profile

    def get_profile(self, profile_id: str = "default") -> UserProfile:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT profile_json FROM profiles WHERE profile_id=?", (profile_id,)
            ).fetchone()
        return UserProfile.model_validate_json(row["profile_json"]) if row else UserProfile()

    def delete_profile(self, profile_id: str = "default") -> None:
        with self.transaction() as connection:
            connection.execute("DELETE FROM profiles WHERE profile_id=?", (profile_id,))

    @staticmethod
    def _fact_from_row(row: sqlite3.Row) -> FactRecord:
        return FactRecord(
            cik=row["cik"],
            ticker=row["ticker"],
            taxonomy=row["taxonomy"],
            concept=row["concept"],
            unit=row["unit"],
            value=Decimal(row["value"]),
            start=date.fromisoformat(row["start"]) if row["start"] else None,
            end=date.fromisoformat(row["end"]),
            fiscal_year=row["fiscal_year"],
            fiscal_period=row["fiscal_period"],
            form=row["form"],
            accession_no=row["accession_no"],
            filed=date.fromisoformat(row["filed"]),
            frame=row["frame"],
            dimensions=json.loads(row["dimensions_json"]),
        )
