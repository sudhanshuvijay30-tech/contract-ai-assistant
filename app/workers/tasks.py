import asyncio
from typing import Any

from app.api.deps import get_contract_service, get_contract_store
from app.core.config import get_settings
from app.services.jobs import JobService


def run_contract_ingestion_job(job_id: str, payload: dict[str, Any]) -> None:
    settings = get_settings()
    service = JobService(
        settings=settings,
        store=get_contract_store(),
        contract_service=get_contract_service(),
    )
    asyncio.run(service.run_contract_ingestion(job_id, payload))
