from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi import BackgroundTasks

from app.core.config import Settings
from app.schemas.contracts import ContractRecord, ContractStatus, ContractUploadResponse, JobStatus
from app.services.jobs import JobService
from app.storage.contract_store import JsonContractStore


class FakeContractService:
    async def ingest_pdf(self, **kwargs):
        contract = ContractRecord(
            id="contract-1",
            filename=kwargs["filename"],
            content_type=kwargs["content_type"],
            sha256="a" * 64,
            size_bytes=len(kwargs["content"]),
            page_count=1,
            created_at=datetime.now(UTC),
            status=ContractStatus.INGESTED,
        )
        return ContractUploadResponse(
            contract=contract,
            clauses_count=2,
            vector_collection="contract_clauses_local",
        )


@pytest.mark.asyncio
async def test_job_service_tracks_ingestion_job_success(tmp_path: Path):
    settings = Settings(contracts_directory=tmp_path / "contracts", job_backend="inline")
    store = JsonContractStore(settings.contracts_directory)
    service = JobService(settings, store, FakeContractService())

    job = service.enqueue_contract_ingestion(
        background_tasks=BackgroundTasks(),
        filename="contract.pdf",
        content_type="application/pdf",
        content=b"%PDF-1.7 sample",
        use_ai=False,
        llm_provider=None,
        llm_model=None,
        metadata=None,
        actor="test",
    )

    await service.run_contract_ingestion(job.id, {
        "filename": "contract.pdf",
        "content_type": "application/pdf",
        "content_b64": "JVBERi0xLjcgc2FtcGxl",
        "use_ai": False,
        "llm_provider": None,
        "llm_model": None,
        "metadata": {},
        "actor": "test",
    })

    saved = store.get_job(job.id)
    assert saved.status == JobStatus.SUCCEEDED
    assert saved.contract_id == "contract-1"
    assert saved.result["clauses_count"] == 2
