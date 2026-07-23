from app.schemas.contracts import Clause, ClauseType, RiskAnalysisResponse, RiskItem, RiskLevel

RISK_ORDER = {
    RiskLevel.LOW: 1,
    RiskLevel.MEDIUM: 2,
    RiskLevel.HIGH: 3,
    RiskLevel.CRITICAL: 4,
}


class RiskRuleEngine:
    def analyze(self, contract_id: str, clauses: list[Clause]) -> RiskAnalysisResponse:
        risks: list[RiskItem] = []
        for clause in clauses:
            lowered = clause.text.lower()
            risk = self._risk_for_clause(clause, lowered)
            if risk is not None:
                risks.append(risk)

        overall = max(
            (risk.level for risk in risks),
            key=lambda level: RISK_ORDER[level],
            default=RiskLevel.LOW,
        )
        summary = (
            "No material rule-based risks were detected."
            if not risks
            else (
                f"{len(risks)} rule-based risk finding(s) detected. "
                "Review high and critical items first."
            )
        )
        return RiskAnalysisResponse(
            contract_id=contract_id,
            overall_risk_level=overall,
            executive_summary=summary,
            risks=risks,
            compliance_findings=self._compliance_findings(clauses),
            negotiation_recommendations=self._negotiation_recommendations(risks),
        )

    def _compliance_findings(self, clauses: list[Clause]) -> list[str]:
        clause_types = {clause.type for clause in clauses}
        findings: list[str] = []
        if ClauseType.GOVERNING_LAW not in clause_types:
            findings.append("No governing law clause was detected.")
        if ClauseType.DATA_PROTECTION not in clause_types:
            findings.append("No dedicated data protection clause was detected.")
        if ClauseType.DISPUTE_RESOLUTION not in clause_types:
            findings.append("No dispute resolution clause was detected.")
        return findings

    def _negotiation_recommendations(self, risks: list[RiskItem]) -> list[str]:
        if not risks:
            return ["Keep current drafting under legal review and confirm business fit."]
        recommendations = []
        high_risks = [risk for risk in risks if risk.level in {RiskLevel.HIGH, RiskLevel.CRITICAL}]
        if high_risks:
            recommendations.append(
                "Resolve high-risk liability, indemnity, or uncapped exposure first."
            )
        recommendations.append("Use the risk evidence snippets as negotiation anchors.")
        recommendations.append("Document any accepted deviations in the contract approval record.")
        return recommendations

    def _risk_for_clause(self, clause: Clause, lowered: str) -> RiskItem | None:
        if clause.type == ClauseType.INDEMNITY and any(
            phrase in lowered for phrase in ("unlimited", "all losses", "any and all")
        ):
            return RiskItem(
                clause_id=clause.id,
                clause_type=clause.type,
                title=clause.title,
                level=RiskLevel.HIGH,
                summary="The indemnity may be broader than a balanced market position.",
                rationale=(
                    "Broad indemnity wording can shift uncapped third-party and direct losses."
                ),
                recommendation=(
                    "Limit indemnity to third-party claims, exclude indirect losses, and add a cap."
                ),
                evidence=[self._excerpt(clause.text, ("unlimited", "all losses", "any and all"))],
            )

        if clause.type == ClauseType.LIMITATION_OF_LIABILITY:
            if "unlimited" in lowered and "liability" in lowered:
                level = RiskLevel.HIGH
                summary = "The limitation clause appears to preserve unlimited liability."
            elif "cap" not in lowered and "aggregate" not in lowered:
                level = RiskLevel.MEDIUM
                summary = "No clear aggregate liability cap was detected."
            else:
                return None
            return RiskItem(
                clause_id=clause.id,
                clause_type=clause.type,
                title=clause.title,
                level=level,
                summary=summary,
                rationale="Liability exposure should be quantified and tied to commercial value.",
                recommendation=(
                    "Add a mutual aggregate cap and carve-outs that match the deal risk."
                ),
                evidence=[self._excerpt(clause.text, ("unlimited", "liability", "aggregate"))],
            )

        if clause.type == ClauseType.TERMINATION and "immediate" in lowered and "breach" in lowered:
            return RiskItem(
                clause_id=clause.id,
                clause_type=clause.type,
                title=clause.title,
                level=RiskLevel.MEDIUM,
                summary="Immediate termination for breach may omit a cure period.",
                rationale=(
                    "A cure period helps avoid termination for remediable operational issues."
                ),
                recommendation=(
                    "Add a 15-30 day cure period for non-payment and non-material breaches."
                ),
                evidence=[self._excerpt(clause.text, ("immediate", "breach"))],
            )

        if clause.type == ClauseType.CONFIDENTIALITY and "perpetual" in lowered:
            return RiskItem(
                clause_id=clause.id,
                clause_type=clause.type,
                title=clause.title,
                level=RiskLevel.MEDIUM,
                summary="Confidentiality obligations may be perpetual.",
                rationale=(
                    "Perpetual obligations can be appropriate for trade secrets but overbroad "
                    "for routine data."
                ),
                recommendation=(
                    "Use a fixed term for ordinary confidential information and preserve "
                    "trade secrets."
                ),
                evidence=[self._excerpt(clause.text, ("perpetual",))],
            )

        if clause.type == ClauseType.GOVERNING_LAW and "exclusive" not in lowered:
            return RiskItem(
                clause_id=clause.id,
                clause_type=clause.type,
                title=clause.title,
                level=RiskLevel.LOW,
                summary="Venue or jurisdiction exclusivity is not explicit.",
                rationale="Ambiguous forum language can increase dispute cost.",
                recommendation=(
                    "Specify governing law and exclusive venue if that matches the preferred "
                    "position."
                ),
                evidence=[self._excerpt(clause.text, ("governing law", "jurisdiction", "venue"))],
            )

        return None

    def _excerpt(self, text: str, phrases: tuple[str, ...]) -> str:
        lowered = text.lower()
        position = min((lowered.find(phrase) for phrase in phrases if phrase in lowered), default=0)
        start = max(position - 80, 0)
        end = min(position + 180, len(text))
        return text[start:end].strip()
