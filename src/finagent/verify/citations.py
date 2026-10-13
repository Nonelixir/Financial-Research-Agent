from __future__ import annotations

import re
from decimal import Decimal
from difflib import get_close_matches

from finagent.schemas import Answer
from finagent.storage import SQLiteStore


class CitationVerificationError(ValueError):
    pass


def substantive_numbers(text: str) -> list[str]:
    """Exclude scope/labels, not money, percentages or operating quantities."""
    # URL/ID digits describe locations, not financial amounts. Visible link labels remain.
    text = re.sub(r"https?://[^\s<>）)]+|/api/artifacts/[A-Za-z0-9_-]+/(?:download|xlsx)", "", text)
    text = re.sub(r"(?<!\d)(?:19|20)\d{2}[-/]\d{1,2}[-/]\d{1,2}(?!\d)", "", text)
    text = re.sub(
        r"\b(?:January|February|March|April|May|June|July|August|September|October|November|December)"
        r"\s+\d{1,2}(?:,?\s+\d{4})?\b",
        "",
        text,
        flags=re.I,
    )
    text = re.sub(r"\bFY\s*\d{2,4}\b", "", text)
    text = re.sub(r"\bSection\s+\d+\([a-z]\)", "", text, flags=re.I)
    text = re.sub(
        r"(?<!\d)(?:19|20)\d{2}(?!\d)|(?<![A-Za-z0-9])(?:FY|Q[1-4])(?![A-Za-z0-9])", "", text
    )
    text = re.sub(
        r"(?<![A-Za-z0-9])(?:10-[KQ]|20-F|[68]-K)(?:/A)?(?![A-Za-z0-9])|(?<![A-Za-z0-9])[23]D(?![A-Za-z0-9])",
        "",
        text,
        flags=re.I,
    )
    text = re.sub(r"(?m)^\s*(?:#{1,6}\s*)?\d+[.、)]\s*", "", text)
    # Inline list labels (1) item; (2) item are formatting, not financial values.
    text = re.sub(r"(?:^|(?<=[:;；：]))\s*\(\d{1,2}\)\s+(?=\S)", "", text)
    text = re.sub(r"\band\s+\(\d{1,2}\)\s+(?=\S)", "and ", text, flags=re.I)
    text = re.sub(r"\b(?:EX-|Exhibit\s+)\d+(?:\.\d+)?\b", "", text, flags=re.I)
    text = re.sub(
        r"(?:近|最近|过去)\s*\d+\s*年|\d+\s*家(?:公司|企业)|第\d+(?:章|节|季度)", "", text
    )
    text = re.sub(
        r"\b(?:last|latest|past|next)\s+\d+\s+(?:fiscal\s+)?years\b|\b\d+\s+(?:companies|firms)\b",
        "",
        text,
        flags=re.I,
    )
    return re.findall(r"\d+(?:[.,]\d+)*", text)


MONEY = re.compile(
    r"(?P<prefix_sign>[-−]?)\s*(?P<accounting>\(\s*(?=(?:USD|US\$|\$)\s*"
    r"[-−]?\d[\d,]*(?:\.\d+)?\s*(?:billion|million|thousand|bn|[bmk])?\s*\)))?"
    r"(?:\bUSD\s*|US\$\s*|\$\s*)"
    r"(?P<amount>[-−]?\d[\d,]*(?:\.\d+)?)\s*"
    r"(?P<scale>billion\b|million\b|thousand\b|bn\b|[bmk]\b)?\)?"
    r"|(?P<suffix_amount>[-−]?\d[\d,]*(?:\.\d+)?)\s*"
    r"(?P<suffix_scale>十亿|亿|百万|万|千|billion|million|thousand)?\s*"
    r"(?:美元|USD\b|US dollars\b)",
    re.I,
)
FACTORS = {
    "十亿": "1000000000",
    "亿": "100000000",
    "百万": "1000000",
    "万": "10000",
    "千": "1000",
    "billion": "1000000000",
    "million": "1000000",
    "thousand": "1000",
    "bn": "1000000000",
    "b": "1000000000",
    "m": "1000000",
    "k": "1000",
}


def money_value(match):
    groups = match.groupdict()
    raw = (groups.get("amount") or groups["suffix_amount"]).replace(",", "").replace("−", "-")
    factor = Decimal(
        FACTORS.get((groups.get("scale") or groups.get("suffix_scale") or "").lower(), "1")
    )
    amount = Decimal(raw) * factor
    if groups.get("prefix_sign") in {"-", "−"} or groups.get("accounting"):
        amount = -abs(amount)
    places = len(raw.split(".")[1]) if "." in raw else 0
    return amount, factor * Decimal(10) ** -places / 2


def local_direction(text, start, end):
    # Limit interpretation to the current clause; never abs-match every amount in a paragraph.
    before = re.split(r"[;；。]|(?<!\d)[.](?!\d)|,\s+(?:while|whereas)|\bwhile\b", text[:start])[
        -1
    ][-80:]
    after = text[end : end + 28]
    before = re.sub(r"\bused\s+as\b", "treated as", before, flags=re.I)
    directions = list(
        re.finditer(
            r"\bused\b|\boutflow|\bnegative|\bloss\b|流出|亏损|"
            r"\binflow|\bprovided|\bgenerated|\bincome\b|\bprofit\b|流入",
            before,
            re.I,
        )
    )
    if directions:
        return (
            "negative"
            if re.search(r"used|outflow|negative|loss|流出|亏损", directions[-1].group(), re.I)
            else "positive"
        )
    if re.search(r"\bloss\b|亏损|流出", after, re.I):
        return "negative"
    return None


def literal_numbers_supported(text: str, quote: str) -> bool:
    """Text-level support only: not a claim of table, unit or metric semantics verification."""
    # Bindings may select dates or a note maturity. These are literal source checks,
    # whereas substantive_numbers intentionally removes them for paragraph validation.
    numbers = re.findall(r"\d+(?:[.,]\d+)*", text)
    available = {n.replace(",", "") for n in re.findall(r"\d+(?:[.,]\d+)*", quote)}
    return bool(numbers) and all(n.replace(",", "") in available for n in numbers)


def percentage_value(text: str, start: int, end: int, raw: str) -> Decimal:
    value = Decimal(raw)
    # A positive magnitude in "declined 0.5%" expresses signed negative growth.
    # Restrict direction to the immediate clause; never flip unrelated margins.
    before = re.split(r"[;；。,:，：]|(?<!\d)\.(?!\d)", text[:start])[-1][-35:]
    if value >= 0 and re.search(
        r"(?:下降|下滑|减少|降低|declin\w*|decreas\w*|fell|fall\w*|reduc\w*)"
        r"(?:\s|约|了|by|about|approximately|roughly|of)*$",
        before,
        re.I,
    ):
        return -value
    return value


def verify_answer_citations(
    answer: Answer,
    allowed_citation_ids: set[str],
    store: SQLiteStore,
) -> Answer:
    """Report failures across paragraphs together so one retry can repair all of them."""
    if answer.message:
        _verify_answer_citations(answer, allowed_citation_ids, store)
        return answer
    errors = []
    for index, claim in enumerate(answer.claims, 1):
        try:
            _verify_answer_citations(Answer(claims=[claim]), allowed_citation_ids, store)
        except CitationVerificationError as exc:
            errors.append(str(exc).replace("Claim 1", f"Claim {index}", 1))
    if errors:
        raise CitationVerificationError(" | ".join(errors))
    return answer


def _verify_answer_citations(
    answer: Answer,
    allowed_citation_ids: set[str],
    store: SQLiteStore,
) -> Answer:
    if answer.message and (
        answer.claims
        or MONEY.search(answer.message)
        or re.search(r"\d\s*(?:%|percent\b|美元|亿元|万元)", answer.message, re.I)
    ):
        raise CitationVerificationError(
            "Conversational message cannot contain cited research claims or financial "
            "amounts; use claims with registered evidence for financial findings"
        )
    for index, claim in enumerate(answer.claims, 1):
        unknown = set(claim.citation_ids) - allowed_citation_ids
        if unknown:
            suggestions = {
                cid: get_close_matches(cid, sorted(allowed_citation_ids), n=3, cutoff=0.85)
                for cid in sorted(unknown)
            }
            raise CitationVerificationError(
                f"Claim {index} references citations outside this run: {sorted(unknown)}; "
                f"possible IDs (inspect before using; never auto-substitute): {suggestions}"
            )
        missing = [
            citation_id for citation_id in claim.citation_ids if not store.get_citation(citation_id)
        ]
        if missing:
            raise CitationVerificationError(f"Citation registry is missing: {missing}")
        citations = store.get_citations(claim.citation_ids)
        for c in citations.values():
            if c.source.source_type == "derived":
                from finagent.compute.evidence import replay_computation

                try:
                    replay_computation(store, c.citation_id)
                except Exception as exc:
                    raise CitationVerificationError(
                        f"Claim {index}: computation verification failed: {exc}"
                    ) from exc
        for binding in claim.numeric_bindings:
            if binding.text not in claim.text or binding.citation_id not in citations:
                raise CitationVerificationError(
                    f"Claim {index}: invalid numeric span/source binding: "
                    f"span={binding.text!r}, citation={binding.citation_id}, "
                    f"span_present={binding.text in claim.text}, "
                    f"citation_in_claim={binding.citation_id in citations}. "
                    "Copy the exact displayed span and include its evidence ID in this claim."
                )
            bound = citations[binding.citation_id]
            if bound.value is None:
                quote = getattr(bound.locator, "exact_quote", "")
                if not literal_numbers_supported(binding.text, quote):
                    raise CitationVerificationError(
                        f"Claim {index}: original text binding lacks literal support"
                    )
                if binding.presentation != "signed":
                    numbers = re.findall(r"\d[\d,]*(?:\.\d+)?", binding.text)
                    direction = local_direction(
                        claim.text,
                        claim.text.index(binding.text),
                        claim.text.index(binding.text) + len(binding.text),
                    )
                    negative_literal = len(numbers) == 1 and re.search(
                        r"(?:\(\s*|[-−]\s*)" + re.escape(numbers[0]) + r"\s*\)?(?!\d)",
                        quote,
                    )
                    if direction != "negative" or not negative_literal:
                        raise CitationVerificationError(
                            f"Claim {index}: original text magnitude needs a negative literal "
                            "and explicit outflow/loss wording"
                        )
                # Narrative support is not numerical replay; never manufacture a ValueRef.
                continue
            monetary = MONEY.search(binding.text)
            if monetary:
                amount, tolerance = money_value(monetary)
            else:
                tokens = re.findall(r"[-−]?\d[\d,]*(?:\.\d+)?", binding.text)
                if len(tokens) != 1:
                    raise CitationVerificationError(
                        f"Claim {index}: binding must select one numeric value"
                    )
                raw = tokens[0].replace(",", "").replace("−", "-")
                amount = Decimal(raw)
                tolerance = Decimal(10) ** -(len(raw.split(".")[1]) if "." in raw else 0) / 2
            expected = bound.value.amount
            percentage = re.fullmatch(r"(?P<value>-?\d+(?:\.\d+)?)\s*%", binding.text)
            if percentage:
                if bound.value.unit != "percent":
                    raise CitationVerificationError(
                        f"Claim {index}: percentage binding requires percent evidence; "
                        f"citation={binding.citation_id}, unit={bound.value.unit}"
                    )
                amount = percentage_value(
                    claim.text,
                    claim.text.index(binding.text),
                    claim.text.index(binding.text) + len(binding.text),
                    percentage.group("value"),
                )
            if binding.presentation != "signed":
                direction = local_direction(
                    claim.text,
                    claim.text.index(binding.text),
                    claim.text.index(binding.text) + len(binding.text),
                )
                if expected >= 0 or direction != "negative":
                    raise CitationVerificationError(
                        f"Claim {index}: magnitude requires a negative flow/loss; "
                        "use presentation='signed' for positive inflows/profit"
                    )
                expected = abs(expected)
            if abs(expected - amount) > tolerance:
                raise CitationVerificationError(
                    f"Claim {index}: bound numeric value mismatch for {binding.text!r}; "
                    f"citation={binding.citation_id}, expected={expected} {bound.value.unit}, "
                    f"displayed={amount}, locator={bound.locator.model_dump_json()}. "
                    "Use the matching company/metric/period citation; signed percentages "
                    "must retain minus signs. Do not remove bindings to hide a mismatch."
                )
        # Known source identifiers may start with digits. Remove exact issuer/ticker identifiers,
        # not an arbitrary class of digit-bearing financial quantities.
        numeric_text = claim.text
        for c in citations.values():
            company = store.get_company(c.source.cik)
            names = [company.name, *company.aliases] if company else []
            identifiers = [c.source.ticker, *names]
            identifiers.extend(
                token
                for name in names
                for token in re.findall(r"\b[A-Za-z0-9]+\b", name)
                if re.search(r"[A-Za-z]", token) and re.search(r"\d", token)
            )
            for identifier in identifiers:
                if identifier:
                    numeric_text = re.sub(
                        r"(?<!\w)" + re.escape(identifier) + r"(?!\w)",
                        "",
                        numeric_text,
                        flags=re.I,
                    )
            quote = getattr(c.locator, "exact_quote", "")
            for identifier in re.findall(r"\b(?:\d+[A-Za-z][A-Za-z0-9]*|[A-Za-z]+\d+)\b", quote):
                numeric_text = re.sub(r"\b" + re.escape(identifier) + r"\b", "", numeric_text)
        numbers = substantive_numbers(numeric_text)
        if numbers:
            values = [c.value.amount for c in citations.values() if c.value is not None]
            # Check explicit USD amounts, including Chinese unit conversion/rounding.
            quotes = " ".join(getattr(c.locator, "exact_quote", "") for c in citations.values())
            for match in MONEY.finditer(claim.text.replace("**", "")):
                amount, tolerance = money_value(match)
                direction = local_direction(
                    claim.text.replace("**", ""), match.start(), match.end()
                )
                explicit_numeric_binding = any(
                    citations[b.citation_id].value is not None
                    and match.group(0).strip() == b.text.replace("**", "").strip()
                    for b in claim.numeric_bindings
                )
                bound_outflow = any(
                    b.presentation in {"outflow", "loss"}
                    and match.group(0).strip() == b.text.replace("**", "").strip()
                    for b in claim.numeric_bindings
                )
                if (
                    amount >= 0
                    and direction == "negative"
                    and (not explicit_numeric_binding or bound_outflow)
                ):
                    amount = -amount
                # Original text can support a literal amount even in a mixed XBRL/text claim.
                raw_number = (
                    (match.groupdict().get("amount") or match.groupdict().get("suffix_amount"))
                    .lstrip("-−")
                    .replace(",", "")
                )
                scale = (
                    match.groupdict().get("scale") or match.groupdict().get("suffix_scale") or ""
                ).lower()
                # Reported figures can coexist with derived percentages in one claim.
                # Require both the literal number and the declared scale in ONE source quote.
                text_supported = any(
                    c.value is None
                    and raw_number
                    in {
                        n.replace(",", "")
                        for n in re.findall(
                            r"\d[\d,]*(?:\.\d+)?", getattr(c.locator, "exact_quote", "")
                        )
                    }
                    and (not scale or scale in getattr(c.locator, "exact_quote", "").lower())
                    for c in citations.values()
                )
                # A mixed claim may explicitly bind a reported table amount to text;
                # do not let unrelated XBRL values erase that lower-level literal support.
                text_supported = text_supported or any(
                    citations[b.citation_id].value is None
                    and match.group(0).strip() == b.text.replace("**", "").strip()
                    and literal_numbers_supported(
                        b.text, getattr(citations[b.citation_id].locator, "exact_quote", "")
                    )
                    for b in claim.numeric_bindings
                )
                if (
                    values
                    and not any(abs(value - amount) <= tolerance for value in values)
                    and not text_supported
                ):
                    raise CitationVerificationError(
                        f"Claim {index}: USD amount/unit mismatch {match.group(0)!r}; "
                        "check source value and currency scale before publishing"
                    )
            # Percentages/days require a reported literal or a registered computation, not any XBRL.
            for match in re.finditer(
                r"(?P<value>-?\d+(?:\.\d+)?)\s*(?P<unit>%|percent\b|days\b|percentage.points\b|个百分点)",
                claim.text,
                re.I,
            ):
                raw = match.group("value")
                if raw in re.findall(r"\d+(?:\.\d+)?", quotes):
                    continue
                unit_label = match.group("unit").lower()
                expected_unit = (
                    "days"
                    if unit_label == "days"
                    else "percentage_points"
                    if unit_label in {"percentage points", "percentage-points", "个百分点"}
                    else "percent"
                )
                displayed = (
                    percentage_value(claim.text, match.start(), match.end(), raw)
                    if expected_unit == "percent"
                    else Decimal(raw)
                )
                if not any(
                    c.value
                    and c.source.source_type == "derived"
                    and c.value.unit == expected_unit
                    and abs(c.value.amount - displayed)
                    <= Decimal("0.5")
                    * Decimal(10) ** -(len(raw.split(".")[1]) if "." in raw else 0)
                    for c in citations.values()
                ):
                    raise CitationVerificationError(
                        f"Claim {index}: use compute_financial for derived {match.group(0)!r}"
                    )
            if not any(citation.value is not None for citation in citations.values()):
                quotes = " ".join(
                    c.locator.exact_quote
                    for c in citations.values()
                    if hasattr(c.locator, "exact_quote")
                )
                quote_numbers = {n.replace(",", "") for n in re.findall(r"\d+(?:[.,]\d+)*", quotes)}
                if quotes and all(n.replace(",", "") in quote_numbers for n in numbers):
                    # Literal narrative numbers; not independent financial verification.
                    continue
                raise CitationVerificationError(
                    f"Claim {index}: A numeric claim must cite a registered XBRL value "
                    f"or literal numbers from cited original text; unsupported={numbers}; "
                    f"text={claim.text[:300]!r}; citation_ids={claim.citation_ids}"
                )
    return answer
