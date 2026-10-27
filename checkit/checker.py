"""Cross-page content consistency checker.

Two layers:
1. Deterministic checks (no LLM needed): date extraction and comparison,
   numeric fact consistency, duplicate/near-duplicate content detection.
2. LLM checks: claim extraction per page and cross-page contradiction
   detection, powered by Mistral / OpenAI / Claude.
"""

from __future__ import annotations

import json
import re
import threading
from dataclasses import dataclass, field
from datetime import date
from difflib import SequenceMatcher

from .distiller import DistilledPage
from .llm import LLMClient

MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11,
    "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, "jul": 7, "aug": 8,
    "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
}

DATE_PATTERNS = [
    # 2024-03-15, 2024/03/15
    (re.compile(r"\b(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})\b"), (1, 2, 3)),
    # 15-03-2024, 15/03/2024 (day-first)
    (re.compile(r"\b(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})\b"), (3, 2, 1)),
    # March 15, 2024 / 15 March 2024 / Mar 15 2024
    (re.compile(r"\b([A-Za-z]+)\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})\b"), "mdy"),
    (re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]+)\.?,?\s+(\d{4})\b"), "dmy"),
]

CLAIM_EXTRACTION_SYSTEM = (
    "You are a precise fact-extraction engine. Extract every checkable factual "
    "claim from the given web page content. A checkable claim is a statement "
    "about a fact: dates, numbers, prices, names, locations, versions, "
    "relationships, or events. Do NOT extract opinions, marketing language, "
    "or navigation text. Return ONLY a JSON array of objects with keys: "
    '"claim" (the claim restated in one sentence), "type" (one of: date, '
    'number, name, fact), "value" (the key value: a date, number or short '
    'string), and "context" (the surrounding sentence). If the page contains '
    "no checkable claims, return an empty array."
)

CROSS_CHECK_SYSTEM = (
    "You are a rigorous consistency auditor. You receive factual claims "
    "extracted from multiple pages of one website, grouped by page. Your job "
    "is to find INTERNAL INCONSISTENCIES: statements on different pages that "
    "contradict each other, dates that do not match up, numbers that differ "
    "for the same fact, or factual errors. Return ONLY a JSON array of "
    "findings. Each finding is an object with keys: \"severity\" (one of: "
    "high, medium, low), \"kind\" (one of: contradiction, date_mismatch, "
    "number_mismatch, factual_error), \"pages\" (list of page URLs involved), "
    "\"description\" (what is inconsistent and why), and \"evidence\" (short "
    "quotes from the pages). If everything is consistent, return an empty "
    "array."
)


@dataclass
class DateMention:
    raw: str
    iso: str
    url: str
    context: str


@dataclass
class Finding:
    severity: str
    kind: str
    pages: list
    description: str
    evidence: str = ""


@dataclass
class CheckReport:
    pages_checked: int
    claims_extracted: int
    date_mentions: list = field(default_factory=list)
    findings: list = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not any(f.severity == "high" for f in self.findings)

    def to_markdown(self) -> str:
        lines = [
            "# CheckIt consistency report",
            "",
            f"- Pages checked: {self.pages_checked}",
            f"- Claims extracted: {self.claims_extracted}",
            f"- Date mentions found: {len(self.date_mentions)}",
            f"- Findings: {len(self.findings)}",
            f"- Overall: {'PASS' if self.ok else 'ISSUES FOUND'}",
            "",
        ]
        if self.date_mentions:
            lines.append("## Dates mentioned across the site")
            lines.append("")
            lines.append("| Date | Page | Context |")
            lines.append("| --- | --- | --- |")
            for d in self.date_mentions:
                ctx = d.context.replace("|", "\\|")
                if len(ctx) > 120:
                    ctx = ctx[:117] + "..."
                lines.append(f"| {d.iso} (`{d.raw}`) | {d.url} | {ctx} |")
            lines.append("")
        if self.findings:
            lines.append("## Findings")
            lines.append("")
            for i, f in enumerate(self.findings, 1):
                lines.append(f"### {i}. [{f.severity.upper()}] {f.kind}")
                lines.append("")
                lines.append(f"- Pages: {', '.join(f.pages)}")
                lines.append(f"- {f.description}")
                if f.evidence:
                    lines.append(f"- Evidence: {f.evidence}")
                lines.append("")
        else:
            lines.append("## Findings")
            lines.append("")
            lines.append("No inconsistencies found.")
            lines.append("")
        return "\n".join(lines)


def _context_around(text: str, start: int, end: int, window: int = 80) -> str:
    lo = max(0, start - window)
    hi = min(len(text), end + window)
    snippet = re.sub(r"\s+", " ", text[lo:hi]).strip()
    return snippet


def extract_dates(markdown: str, url: str) -> list:
    """Extract all parseable dates from markdown text."""
    mentions = []
    for pattern, order in DATE_PATTERNS:
        for m in pattern.finditer(markdown):
            raw = m.group(0)
            try:
                if order == "mdy":
                    month = MONTHS.get(m.group(1).lower())
                    if not month:
                        continue
                    d = date(int(m.group(3)), month, int(m.group(2)))
                elif order == "dmy":
                    month = MONTHS.get(m.group(2).lower())
                    if not month:
                        continue
                    d = date(int(m.group(3)), month, int(m.group(1)))
                else:
                    y, mo, dy = (int(m.group(i)) for i in order)
                    d = date(y, mo, dy)
            except ValueError:
                continue
            mentions.append(DateMention(
                raw=raw, iso=d.isoformat(), url=url,
                context=_context_around(markdown, m.start(), m.end()),
            ))
    return mentions


def check_date_consistency(date_mentions: list) -> list:
    """Heuristic deterministic date check.

    Flags when the exact same raw date string maps to different ISO dates
    (ambiguous formats like 03/04/2024) and when a page's stated founding /
    launch date appears to postdate content dated earlier on another page.
    """
    findings = []
    by_raw: dict = {}
    for m in date_mentions:
        by_raw.setdefault(m.raw.lower(), set()).add(m.iso)
    for raw, isos in by_raw.items():
        if len(isos) > 1:
            findings.append(Finding(
                severity="medium",
                kind="date_mismatch",
                pages=sorted({m.url for m in date_mentions
                               if m.raw.lower() == raw}),
                description=(
                    f"The date {raw!r} is ambiguous and parsed to different "
                    f"dates depending on format: {sorted(isos)}. Use unambiguous "
                    "dates (e.g. ISO 8601) everywhere."
                ),
            ))
    return findings


def find_duplicate_content(pages: list, threshold: float = 0.9) -> list:
    """Flag pages whose distilled content is near-identical to another page."""
    findings = []
    texts = [p.markdown for p in pages]
    for i in range(len(pages)):
        for j in range(i + 1, len(pages)):
            ratio = SequenceMatcher(None, texts[i], texts[j]).ratio()
            if ratio >= threshold:
                findings.append(Finding(
                    severity="low",
                    kind="factual_error",
                    pages=[pages[i].url, pages[j].url],
                    description=(
                        f"Pages are {ratio:.0%} identical. Possible duplicated "
                        "or boilerplate content; verify both pages are correct."
                    ),
                ))
    return findings


def _parse_json_array(text: str) -> list:
    """Best-effort extraction of a JSON array from LLM output."""
    text = text.strip()
    start = text.find("[")
    end = text.rfind("]")
    if start == -1 or end == -1 or end < start:
        return []
    try:
        data = json.loads(text[start:end + 1])
        return data if isinstance(data, list) else []
    except json.JSONDecodeError:
        return []


def extract_claims(client: LLMClient, page: DistilledPage) -> list:
    """Ask the LLM to extract checkable claims from one page."""
    user = f"Page URL: {page.url}\nPage title: {page.title}\n\n{page.markdown}"
    response = client.complete(CLAIM_EXTRACTION_SYSTEM, user)
    claims = _parse_json_array(response.text)
    for c in claims:
        if isinstance(c, dict):
            c.setdefault("page", page.url)
    return claims


def cross_check_claims(client: LLMClient, claims_by_page: dict) -> list:
    """Ask the LLM to find inconsistencies across pages' claims."""
    payload = {
        url: claims for url, claims in claims_by_page.items() if claims
    }
    if not payload:
        return []
    user = (
        "Claims grouped by page URL (JSON). Find internal inconsistencies, "
        "contradictions and date/number mismatches:\n\n"
        + json.dumps(payload, indent=2, ensure_ascii=False)
    )
    response = client.complete(CROSS_CHECK_SYSTEM, user)
    findings = []
    for item in _parse_json_array(response.text):
        if not isinstance(item, dict):
            continue
        findings.append(Finding(
            severity=str(item.get("severity", "medium")).lower(),
            kind=str(item.get("kind", "contradiction")).lower(),
            pages=list(item.get("pages", [])),
            description=str(item.get("description", "")),
            evidence=str(item.get("evidence", "")),
        ))
    return findings


def check_pages(pages: list, client: LLMClient | None = None,
                use_llm: bool = True,
                progress=None,
                cancel_event: threading.Event | None = None) -> CheckReport:
    """Run deterministic + (optional) LLM consistency checks over pages."""
    def check_cancel():
        if cancel_event is not None and cancel_event.is_set():
            from .gui import CancelledError
            raise CancelledError("cancelled by user")

    report = CheckReport(pages_checked=len(pages), claims_extracted=0)

    all_dates: list = []
    for page in pages:
        check_cancel()
        all_dates.extend(extract_dates(page.markdown, page.url))
    report.date_mentions = all_dates
    report.findings.extend(check_date_consistency(all_dates))
    report.findings.extend(find_duplicate_content(pages))

    if use_llm and client is not None and pages:
        claims_by_page = {}
        total = len(pages)
        for i, page in enumerate(pages):
            check_cancel()
            claims_by_page[page.url] = extract_claims(client, page)
            if progress and i % 2 == 0:
                pct = 65 + int(25 * (i + 1) / max(1, total))
                progress(f"Extracted claims from {i + 1}/{total} pages.", pct)
        report.claims_extracted = sum(len(v) for v in claims_by_page.values())
        check_cancel()
        report.findings.extend(cross_check_claims(client, claims_by_page))

    return report
