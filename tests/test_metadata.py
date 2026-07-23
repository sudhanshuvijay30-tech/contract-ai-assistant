from app.services.metadata import ContractMetadataExtractor


def test_metadata_extractor_combines_overrides_and_heuristics():
    text = """
    This Master Services Agreement is effective as of July 22, 2026.
    Customer: Acme Corp
    Supplier: Example Services Inc.
    This agreement is governed by the laws of New York.
    """

    metadata = ContractMetadataExtractor().extract("msa.pdf", text)

    assert metadata.contract_type == "MSA"
    assert metadata.customer == "Acme Corp"
    assert metadata.supplier == "Example Services Inc"
    assert metadata.governing_law == "New York"
    assert metadata.effective_date == "July 22, 2026"
