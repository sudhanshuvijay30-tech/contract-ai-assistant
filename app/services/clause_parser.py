import hashlib
import re

from app.schemas.contracts import Clause, ClauseType, ExtractedPage

CLAUSE_KEYWORDS: dict[ClauseType, tuple[str, ...]] = {
    ClauseType.CONFIDENTIALITY: ("confidential", "non-disclosure", "proprietary information"),
    ClauseType.INDEMNITY: ("indemnify", "indemnification", "hold harmless"),
    ClauseType.LIMITATION_OF_LIABILITY: (
        "limitation of liability",
        "liability cap",
        "consequential damages",
        "aggregate liability",
    ),
    ClauseType.TERMINATION: ("termination", "terminate", "survival"),
    ClauseType.PAYMENT: ("payment", "fees", "invoice", "taxes"),
    ClauseType.DATA_PROTECTION: ("data protection", "personal data", "privacy", "gdpr", "security"),
    ClauseType.INTELLECTUAL_PROPERTY: (
        "intellectual property",
        "work product",
        "license",
        "ownership",
    ),
    ClauseType.WARRANTIES: ("warranty", "representations", "as is"),
    ClauseType.GOVERNING_LAW: ("governing law", "jurisdiction", "venue"),
    ClauseType.DISPUTE_RESOLUTION: ("dispute", "arbitration", "mediation"),
    ClauseType.ASSIGNMENT: ("assignment", "assign"),
    ClauseType.AUDIT: ("audit", "inspection"),
    ClauseType.FORCE_MAJEURE: ("force majeure", "acts of god"),
    ClauseType.NON_COMPETE: ("non-compete", "non compete", "restrictive covenant"),
}

KNOWN_TITLES = sorted(
    {
        phrase.title()
        for keywords in CLAUSE_KEYWORDS.values()
        for phrase in keywords
        if len(phrase.split()) <= 4
    },
    key=len,
    reverse=True,
)

NUMBERED_HEADING_RE = re.compile(
    r"^\s*(?P<number>\d{1,2}(?:\.\d+)*|[A-Z])[\.)]?\s+"
    r"(?P<title>[A-Z][A-Za-z0-9 &,/()'\-]{2,90})(?::|\s+-|\n|$)"
)


class ClauseParser:
    def extract(self, contract_id: str, pages: list[ExtractedPage]) -> list[Clause]:
        full_text, page_ranges = self._join_pages(pages)
        if not full_text.strip():
            return []

        segments = self._segment_by_headings(full_text)
        if len(segments) <= 1:
            segments = self._segment_by_size(full_text)

        clauses: list[Clause] = []
        for index, (title, text, start, end) in enumerate(segments, start=1):
            clean_text = self._clean_clause_text(text)
            if len(clean_text) < 25:
                continue
            clause_type = self.classify(title, clean_text)
            page_start = self._page_for_offset(start, page_ranges)
            page_end = self._page_for_offset(max(start, end - 1), page_ranges)
            clauses.append(
                Clause(
                    id=self._clause_id(contract_id, index, clean_text),
                    contract_id=contract_id,
                    type=clause_type,
                    title=title or self._fallback_title(clean_text),
                    text=clean_text,
                    page_start=page_start,
                    page_end=page_end,
                    start_char=start,
                    end_char=end,
                    confidence=0.72 if title else 0.6,
                    source="heuristic",
                )
            )
        return clauses

    def classify(self, title: str | None, text: str) -> ClauseType:
        haystack = f"{title or ''}\n{text}".lower()
        scores = {
            clause_type: sum(1 for keyword in keywords if keyword in haystack)
            for clause_type, keywords in CLAUSE_KEYWORDS.items()
        }
        best_type, best_score = max(scores.items(), key=lambda item: item[1])
        return best_type if best_score else ClauseType.OTHER

    def _join_pages(self, pages: list[ExtractedPage]) -> tuple[str, list[tuple[int, int, int]]]:
        parts: list[str] = []
        ranges: list[tuple[int, int, int]] = []
        cursor = 0
        for page in pages:
            text = self._normalize_whitespace(page.text)
            if not text:
                continue
            start = cursor
            end = start + len(text)
            parts.append(text)
            ranges.append((start, end, page.page_number))
            cursor = end + 2
        return "\n\n".join(parts), ranges

    def _segment_by_headings(self, full_text: str) -> list[tuple[str, str, int, int]]:
        paragraphs = [
            (match.group(0).strip(), match.start(), match.end())
            for match in re.finditer(r"\S.*?(?=\n\s*\n|\Z)", full_text, flags=re.DOTALL)
        ]
        if not paragraphs:
            return []

        segments: list[tuple[str, list[str], int, int]] = []
        current_title: str | None = None
        current_parts: list[str] = []
        current_start = 0
        current_end = 0

        for paragraph, start, end in paragraphs:
            heading = self._extract_heading(paragraph)
            if heading and current_parts:
                segments.append((current_title or "", current_parts, current_start, current_end))
                current_title = heading
                current_parts = [paragraph]
                current_start = start
                current_end = end
                continue
            if heading and not current_parts:
                current_title = heading
                current_start = start
            if not current_parts:
                current_start = start
            current_parts.append(paragraph)
            current_end = end

        if current_parts:
            segments.append((current_title or "", current_parts, current_start, current_end))

        return [
            (title, "\n\n".join(parts), start, end)
            for title, parts, start, end in segments
            if len("\n\n".join(parts)) >= 25
        ]

    def _segment_by_size(
        self,
        full_text: str,
        max_chars: int = 1_800,
    ) -> list[tuple[str, str, int, int]]:
        paragraphs = [
            (match.group(0).strip(), match.start(), match.end())
            for match in re.finditer(r"\S.*?(?=\n\s*\n|\Z)", full_text, flags=re.DOTALL)
        ]
        segments: list[tuple[str, str, int, int]] = []
        current: list[str] = []
        start = 0
        end = 0
        for paragraph, paragraph_start, paragraph_end in paragraphs:
            if not current:
                start = paragraph_start
            candidate = "\n\n".join([*current, paragraph])
            if len(candidate) > max_chars and current:
                text = "\n\n".join(current)
                segments.append((self._fallback_title(text), text, start, end))
                current = [paragraph]
                start = paragraph_start
            else:
                current.append(paragraph)
            end = paragraph_end
        if current:
            text = "\n\n".join(current)
            segments.append((self._fallback_title(text), text, start, end))
        return segments

    def _extract_heading(self, paragraph: str) -> str | None:
        first_line = paragraph.splitlines()[0].strip()
        match = NUMBERED_HEADING_RE.match(first_line)
        if match:
            return match.group("title").strip(" .:-")

        normalized = first_line.lower().strip(" .:-")
        for title in KNOWN_TITLES:
            if normalized == title.lower():
                return title
        if len(first_line) <= 90:
            for title in KNOWN_TITLES:
                if normalized.startswith(title.lower()):
                    return title
        return None

    def _clean_clause_text(self, text: str) -> str:
        return re.sub(r"\n{3,}", "\n\n", text).strip()

    def _normalize_whitespace(self, text: str) -> str:
        lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines()]
        normalized = "\n".join(lines)
        return re.sub(r"\n{3,}", "\n\n", normalized).strip()

    def _page_for_offset(
        self,
        offset: int,
        page_ranges: list[tuple[int, int, int]],
    ) -> int | None:
        for start, end, page_number in page_ranges:
            if start <= offset <= end:
                return page_number
        return page_ranges[-1][2] if page_ranges else None

    def _fallback_title(self, text: str) -> str:
        first_sentence = re.split(r"(?<=[.!?])\s+", text.strip(), maxsplit=1)[0]
        return first_sentence[:80].strip(" .:-") or "Untitled clause"

    def _clause_id(self, contract_id: str, index: int, text: str) -> str:
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:10]
        return f"{contract_id}:clause:{index:04d}:{digest}"
