from datetime import UTC, datetime

import pytest

from app.schemas.contracts import (
    AuditEvent,
    Clause,
    ContractMetadata,
    ContractRecord,
    ContractStatus,
    JobRecord,
    JobStatus,
    JobType,
)

pytest.importorskip("sqlalchemy")

from app.storage.postgres_store import PostgresContractStore  # noqa: E402


def test_postgres_store_persists_contract_clauses_jobs_and_audit(tmp_path):
    store = PostgresContractStore(f"sqlite:///{tmp_path / 'contracts.db'}")
    contract = ContractRecord(
        id="contract-1",
        filename="agreement.pdf",
        content_type="application/pdf",
        sha256="a" * 64,
        size_bytes=100,
        page_count=1,
        created_at=datetime.now(UTC),
        status=ContractStatus.INGESTED,
        metadata=ContractMetadata(contract_type="MSA", jurisdiction="New York"),
    )
    clause = Clause(
        id="clause-1",
        contract_id=contract.id,
        title="Governing Law",
        text="This agreement is governed by the laws of New York.",
        start_char=0,
        end_char=52,
    )

    store.save_contract(contract, [clause], "raw contract text")
    saved = store.get_contract(contract.id)
    clauses = store.get_clauses(contract.id)

    assert saved.metadata.contract_type == "MSA"
    assert clauses[0].title == "Governing Law"
    assert store.get_contract_text(contract.id) == "raw contract text"

    job = JobRecord(id="job-1", type=JobType.CONTRACT_INGESTION)
    store.save_job(job)
    updated = store.update_job(
        "job-1",
        JobStatus.SUCCEEDED,
        contract_id=contract.id,
        result={"contract": {"id": contract.id}},
    )
    assert updated.status == JobStatus.SUCCEEDED
    assert store.get_job("job-1").contract_id == contract.id

    store.save_audit_event(
        AuditEvent(action="contract.uploaded", actor="test", contract_id=contract.id)
    )
