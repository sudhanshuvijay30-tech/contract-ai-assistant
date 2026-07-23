import base64
import logging
from typing import Any

from fastapi import BackgroundTasks

from app.core.config import Settings
from app.core.errors import JobQueueError
from app.schemas.contracts import (
    AIProvider,
    AuditEvent,
    ContractMetadata,
    JobRecord,
    JobStatus,
    JobType,
)
from app.services.contracts import ContractService
from app.storage.contract_store import ContractStore

logger = logging.getLogger(__name__)


class JobService:
    def __init__(
        self,
        settings: Settings,
        store: ContractStore,
        contract_service: ContractService,
    ):
        self.settings = settings
        self.store = store
        self.contract_service = contract_service

    def enqueue_contract_ingestion(
        self,
        background_tasks: BackgroundTasks,
        filename: str,
        content_type: str,
        content: bytes,
        use_ai: bool,
        llm_provider: AIProvider | None,
        llm_model: str | None,
        metadata: ContractMetadata | None,
        actor: str,
    ) -> JobRecord:
        job = JobRecord(type=JobType.CONTRACT_INGESTION)
        self.store.save_job(job)
        payload = {
            "filename": filename,
            "content_type": content_type,
            "content_b64": base64.b64encode(content).decode("ascii"),
            "use_ai": use_ai,
            "llm_provider": llm_provider.value if llm_provider else None,
            "llm_model": llm_model,
            "metadata": metadata.model_dump(mode="json") if metadata else {},
            "actor": actor,
        }
        self._audit(
            "job.queued",
            actor=actor,
            job_id=job.id,
            metadata={"type": job.type.value, "backend": self.settings.job_backend},
        )
        if self.settings.job_backend == "rq":
            self._enqueue_rq(job.id, payload)
        else:
            background_tasks.add_task(self.run_contract_ingestion, job.id, payload)
        return job

    async def run_contract_ingestion(self, job_id: str, payload: dict[str, Any]) -> None:
        self.store.update_job(job_id, JobStatus.RUNNING)
        self._audit("job.running", actor=payload.get("actor", "system"), job_id=job_id)
        try:
            response = await self.contract_service.ingest_pdf(
                filename=str(payload["filename"]),
                content_type=str(payload["content_type"]),
                content=base64.b64decode(str(payload["content_b64"])),
                use_ai=bool(payload["use_ai"]),
                llm_provider=payload.get("llm_provider"),
                llm_model=payload.get("llm_model"),
                metadata=ContractMetadata.model_validate(payload.get("metadata") or {}),
                actor=str(payload.get("actor") or "system"),
            )
        except Exception as exc:
            logger.exception("contract_ingestion_job_failed job_id=%s", job_id)
            self.store.update_job(job_id, JobStatus.FAILED, error=str(exc))
            self._audit(
                "job.failed",
                actor=payload.get("actor", "system"),
                job_id=job_id,
                metadata={"error": str(exc)},
            )
            return

        self.store.update_job(
            job_id,
            JobStatus.SUCCEEDED,
            contract_id=response.contract.id,
            result=response.model_dump(mode="json"),
        )
        self._audit(
            "job.succeeded",
            actor=payload.get("actor", "system"),
            contract_id=response.contract.id,
            job_id=job_id,
        )

    def get_job(self, job_id: str) -> JobRecord:
        return self.store.get_job(job_id)

    def _enqueue_rq(self, job_id: str, payload: dict[str, Any]) -> None:
        try:
            from redis import Redis
            from rq import Queue
        except ImportError as exc:
            raise JobQueueError("redis and rq are required when JOB_BACKEND=rq.") from exc

        try:
            redis_conn = Redis.from_url(self.settings.redis_url)
            queue = Queue(self.settings.rq_queue_name, connection=redis_conn)
            queue.enqueue("app.workers.tasks.run_contract_ingestion_job", job_id, payload)
        except Exception as exc:
            self.store.update_job(job_id, JobStatus.FAILED, error=str(exc))
            raise JobQueueError(
                "Unable to enqueue the contract ingestion job in Redis/RQ."
            ) from exc

    def _audit(
        self,
        action: str,
        actor: str = "system",
        contract_id: str | None = None,
        job_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self.store.save_audit_event(
            AuditEvent(
                action=action,
                actor=actor,
                contract_id=contract_id,
                job_id=job_id,
                metadata=metadata or {},
            )
        )
