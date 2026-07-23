import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from app.core.errors import NotFoundError
from app.schemas.contracts import (
    AuditEvent,
    Clause,
    ContractRecord,
    ContractStatus,
    JobRecord,
    JobStatus,
)


class ContractStore(Protocol):
    def save_contract(self, contract: ContractRecord, clauses: list[Clause], raw_text: str) -> None:
        ...

    def get_contract(self, contract_id: str) -> ContractRecord:
        ...

    def get_clauses(self, contract_id: str) -> list[Clause]:
        ...

    def get_contract_text(self, contract_id: str) -> str:
        ...

    def update_status(self, contract_id: str, status: str) -> None:
        ...

    def save_job(self, job: JobRecord) -> None:
        ...

    def get_job(self, job_id: str) -> JobRecord:
        ...

    def update_job(
        self,
        job_id: str,
        status: JobStatus,
        contract_id: str | None = None,
        result: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> JobRecord:
        ...

    def save_audit_event(self, event: AuditEvent) -> None:
        ...


class JsonContractStore:
    def __init__(self, directory: Path):
        self.directory = directory
        self.directory.mkdir(parents=True, exist_ok=True)
        self.jobs_directory = self.directory / "_jobs"
        self.jobs_directory.mkdir(parents=True, exist_ok=True)
        self.audit_path = self.directory / "_audit_events.jsonl"

    def save_contract(self, contract: ContractRecord, clauses: list[Clause], raw_text: str) -> None:
        payload = {
            "contract": contract.model_dump(mode="json"),
            "clauses": [clause.model_dump(mode="json") for clause in clauses],
            "raw_text": raw_text,
        }
        self._write_json(self._path(contract.id), payload)

    def get_contract(self, contract_id: str) -> ContractRecord:
        payload = self._read_json(contract_id)
        return ContractRecord.model_validate(payload["contract"])

    def get_clauses(self, contract_id: str) -> list[Clause]:
        payload = self._read_json(contract_id)
        return [Clause.model_validate(item) for item in payload["clauses"]]

    def get_contract_text(self, contract_id: str) -> str:
        payload = self._read_json(contract_id)
        return str(payload.get("raw_text", ""))

    def update_status(self, contract_id: str, status: str) -> None:
        payload = self._read_json(contract_id)
        contract = ContractRecord.model_validate(payload["contract"])
        contract.status = ContractStatus(status)
        payload["contract"] = contract.model_dump(mode="json")
        self._write_json(self._path(contract_id), payload)

    def save_job(self, job: JobRecord) -> None:
        self._write_json(self._job_path(job.id), job.model_dump(mode="json"))

    def get_job(self, job_id: str) -> JobRecord:
        path = self._job_path(job_id)
        if not path.exists():
            raise NotFoundError(f"Job '{job_id}' was not found.")
        return JobRecord.model_validate(json.loads(path.read_text(encoding="utf-8")))

    def update_job(
        self,
        job_id: str,
        status: JobStatus,
        contract_id: str | None = None,
        result: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> JobRecord:
        job = self.get_job(job_id)
        job.status = status
        job.updated_at = datetime.now(UTC)
        if contract_id is not None:
            job.contract_id = contract_id
        if result is not None:
            job.result = result
        if error is not None:
            job.error = error
        self.save_job(job)
        return job

    def save_audit_event(self, event: AuditEvent) -> None:
        self.audit_path.parent.mkdir(parents=True, exist_ok=True)
        with self.audit_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event.model_dump(mode="json"), ensure_ascii=False) + "\n")

    def _read_json(self, contract_id: str) -> dict:
        path = self._path(contract_id)
        if not path.exists():
            raise NotFoundError(f"Contract '{contract_id}' was not found.")
        return json.loads(path.read_text(encoding="utf-8"))

    def _write_json(self, path: Path, payload: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = path.with_suffix(".tmp")
        temp_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        temp_path.replace(path)

    def _path(self, contract_id: str) -> Path:
        safe_id = "".join(ch for ch in contract_id if ch.isalnum() or ch in {"-", "_"})
        return self.directory / f"{safe_id}.json"

    def _job_path(self, job_id: str) -> Path:
        safe_id = "".join(ch for ch in job_id if ch.isalnum() or ch in {"-", "_"})
        return self.jobs_directory / f"{safe_id}.json"
