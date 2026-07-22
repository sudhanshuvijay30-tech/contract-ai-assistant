from app.schemas.contracts import Clause, ClauseType, RiskLevel
from app.services.risk_rules import RiskRuleEngine


def test_risk_rules_flag_broad_indemnity():
    clause = Clause(
        id="c1",
        contract_id="contract-1",
        type=ClauseType.INDEMNITY,
        title="Indemnification",
        text="Supplier shall indemnify customer from any and all losses on an unlimited basis.",
        start_char=0,
        end_char=80,
    )

    result = RiskRuleEngine().analyze("contract-1", [clause])

    assert result.overall_risk_level == RiskLevel.HIGH
    assert result.risks[0].clause_id == "c1"
    assert "indemnity" in result.risks[0].summary.lower()

