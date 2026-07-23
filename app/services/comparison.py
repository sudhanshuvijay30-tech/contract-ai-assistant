import re

from app.schemas.contracts import ClauseComparisonRequest, ClauseComparisonResponse, RiskLevel

MATERIAL_TERMS = (
    "cap",
    "indemnity",
    "indemnification",
    "confidential",
    "termination",
    "cure period",
    "governing law",
    "exclusive",
    "consequential damages",
    "personal data",
    "audit",
    "assignment",
)


class ClauseComparator:
    def compare(self, request: ClauseComparisonRequest) -> ClauseComparisonResponse:
        source_tokens = self._tokens(request.source_clause.text)
        counterparty_tokens = self._tokens(request.counterparty_clause.text)
        if not source_tokens or not counterparty_tokens:
            score = 0.0
        else:
            score = len(source_tokens & counterparty_tokens) / len(
                source_tokens | counterparty_tokens
            )

        missing_terms = [
            term
            for term in MATERIAL_TERMS
            if term in request.source_clause.text.lower()
            and term not in request.counterparty_clause.text.lower()
        ]
        deviations = self._deviations(request)
        risk = self._risk_level(score, missing_terms, deviations)

        summary = (
            "The clauses are closely aligned."
            if score >= 0.75 and not missing_terms
            else "The counterparty clause materially differs from the source clause."
        )
        negotiation_points = [
            "Restore missing commercial protections from the source clause.",
            "Confirm carve-outs, caps, survival, and remedies match the intended risk allocation.",
        ]
        if request.preferred_position:
            negotiation_points.insert(
                0,
                f"Check against preferred position: {request.preferred_position}",
            )

        return ClauseComparisonResponse(
            alignment_score=round(score, 3),
            risk_delta=risk,
            summary=summary,
            missing_terms=missing_terms,
            material_deviations=deviations,
            negotiation_points=negotiation_points,
            recommended_clause=(
                request.source_clause.text if missing_terms or score < 0.55 else None
            ),
            compliance_notes=self._compliance_notes(request),
            negotiation_strategy=[
                "Prioritize high-exposure deviations before style or drafting preferences.",
                "Ask the counterparty to explain any missing mutuality, cap, or remedy language.",
            ],
        )

    def _tokens(self, text: str) -> set[str]:
        return {token for token in re.findall(r"[a-zA-Z][a-zA-Z\-]{2,}", text.lower())}

    def _deviations(self, request: ClauseComparisonRequest) -> list[str]:
        source = request.source_clause.text.lower()
        counterparty = request.counterparty_clause.text.lower()
        deviations: list[str] = []
        if "unlimited" not in source and "unlimited" in counterparty:
            deviations.append("Counterparty wording introduces unlimited exposure.")
        if "mutual" in source and "mutual" not in counterparty:
            deviations.append("Mutuality present in the source clause is missing.")
        if "cure period" in source and "cure period" not in counterparty:
            deviations.append("Cure period protection appears to be missing.")
        if "consequential damages" in source and "consequential damages" not in counterparty:
            deviations.append("Consequential damages treatment differs or is absent.")
        return deviations

    def _compliance_notes(self, request: ClauseComparisonRequest) -> list[str]:
        combined = f"{request.source_clause.text}\n{request.counterparty_clause.text}".lower()
        notes: list[str] = []
        if "personal data" in combined and "gdpr" not in combined and "privacy" not in combined:
            notes.append("Data protection wording should be checked against privacy obligations.")
        if "governing law" in combined and "jurisdiction" not in combined:
            notes.append("Governing law appears without a matching jurisdiction/forum term.")
        if "audit" in combined and "notice" not in combined:
            notes.append("Audit rights should specify notice, scope, and confidentiality controls.")
        return notes

    def _risk_level(
        self,
        score: float,
        missing_terms: list[str],
        deviations: list[str],
    ) -> RiskLevel:
        if score < 0.35 or len(deviations) >= 2:
            return RiskLevel.HIGH
        if score < 0.6 or missing_terms or deviations:
            return RiskLevel.MEDIUM
        return RiskLevel.LOW
