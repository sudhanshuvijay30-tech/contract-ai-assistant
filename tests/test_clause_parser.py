from app.schemas.contracts import ClauseType, ExtractedPage
from app.services.clause_parser import ClauseParser


def test_clause_parser_extracts_and_classifies_common_clauses():
    pages = [
        ExtractedPage(
            page_number=1,
            text="""
            1. Confidentiality
            Each party shall keep confidential information secret for five years.

            2. Indemnification
            Supplier shall indemnify customer from any and all third party losses.

            3. Governing Law
            This agreement is governed by the laws of New York.
            """,
        )
    ]

    clauses = ClauseParser().extract("contract-1", pages)

    assert len(clauses) == 3
    assert clauses[0].type == ClauseType.CONFIDENTIALITY
    assert clauses[1].type == ClauseType.INDEMNITY
    assert clauses[2].type == ClauseType.GOVERNING_LAW
    assert clauses[0].page_start == 1

