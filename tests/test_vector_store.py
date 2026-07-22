import pytest

from app.core.config import Settings
from app.core.errors import VectorStoreError
from app.schemas.contracts import Clause
from app.storage.vector_store import ContractVectorRepository, LocalHashEmbeddings


def test_vector_store_preserves_missing_openai_key_error(tmp_path):
    settings = Settings(
        chroma_persist_directory=tmp_path / "chroma",
        openai_api_key=None,
        embedding_provider="openai",
    )
    repository = ContractVectorRepository(settings)
    clause = Clause(
        id="clause-1",
        contract_id="contract-1",
        title="Payment",
        text="Customer shall pay all undisputed invoices within thirty days.",
        start_char=0,
        end_char=62,
    )

    with pytest.raises(VectorStoreError) as exc_info:
        repository.upsert_clauses([clause])

    assert "OPENAI_API_KEY is required" in exc_info.value.message


def test_local_hash_embeddings_are_deterministic_and_normalized():
    embeddings = LocalHashEmbeddings(dimensions=128)

    first = embeddings.embed_query("Payment is due within thirty days.")
    second = embeddings.embed_query("Payment is due within thirty days.")

    assert first == second
    assert len(first) == 128
    assert sum(value * value for value in first) == pytest.approx(1.0)


def test_vector_store_defaults_to_local_collection(tmp_path):
    settings = Settings(chroma_persist_directory=tmp_path / "chroma")
    repository = ContractVectorRepository(settings)

    assert settings.embedding_provider == "local"
    assert repository.collection_name == "contract_clauses_local"
