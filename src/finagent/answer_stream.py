"""Commit closed, citation-checked claims, never partial JSON or retry drafts."""

import json

from pydantic import ValidationError

from finagent.schemas import Answer, Claim
from finagent.verify.citations import CitationVerificationError, verify_answer_citations


def closed_claims(raw: str) -> list[Claim]:
    decoder = json.JSONDecoder()
    text = raw.lstrip()
    if not text.startswith("{"):
        return []
    pos = 1
    try:
        while True:
            while pos < len(text) and text[pos].isspace():
                pos += 1
            key, pos = decoder.raw_decode(text, pos)
            while pos < len(text) and text[pos].isspace():
                pos += 1
            if text[pos] != ":":
                return []
            pos += 1
            while pos < len(text) and text[pos].isspace():
                pos += 1
            if key == "claims":
                if text[pos] != "[":
                    return []
                pos += 1
                result = []
                while True:
                    while pos < len(text) and text[pos].isspace():
                        pos += 1
                    if pos >= len(text) or text[pos] == "]":
                        return result
                    try:
                        value, end = decoder.raw_decode(text, pos)
                    except ValueError:
                        return result
                    result.append(Claim.model_validate(value))
                    pos = end
                    while pos < len(text) and text[pos].isspace():
                        pos += 1
                    if pos >= len(text) or text[pos] == "]":
                        return result
                    if text[pos] != ",":
                        return []
                    pos += 1
            _, pos = decoder.raw_decode(text, pos)
            while pos < len(text) and text[pos].isspace():
                pos += 1
            if text[pos] != ",":
                return []
            pos += 1
    except (ValueError, IndexError, ValidationError):
        return []


class CommittedAnswer:
    def __init__(self):
        self.claims: list[Claim] = []
        self.recoverable: list[Claim] = []

    def extends(self, claims: list[Claim]) -> bool:
        return claims[: len(self.claims)] == self.claims

    def update(self, raw: str, allowed: set[str], store) -> Answer | None:
        candidates = closed_claims(raw)
        for claim in candidates:
            try:
                verify_answer_citations(Answer(claims=[claim]), allowed, store)
            except CitationVerificationError:
                continue
            if claim not in self.recoverable:
                self.recoverable.append(claim)
        if not self.extends(candidates):
            return None
        previous = len(self.claims)
        for claim in candidates[previous:]:
            try:
                verify_answer_citations(Answer(claims=[claim]), allowed, store)
            except CitationVerificationError:
                break
            self.claims.append(claim)
        if len(self.claims) == previous:
            return None
        return Answer(claims=list(self.claims), status="incomplete", status_reason="streaming")
