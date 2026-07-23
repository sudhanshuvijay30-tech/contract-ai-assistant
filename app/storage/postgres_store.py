from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import sessionmaker

from app.core.errors import NotFoundError, StorageError
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
from app.storage.database import (
    AuditEventRow,
    Base,
    ClauseRow,
    ContractRow,
    JobRow,
    make_engine,
    make_session_factory,
)


class PostgresContractStore:
    def __init__(self, database_url: str, auto_create: bool = True):
        self.engine = make_engine(database_url)
        if auto_create:
            Base.metadata.create_all(self.engine)
        self.session_factory: sessionmaker = make_session_factory(self.engine)

    def save_contract(self, contract: ContractRecord, clauses: list[Clause], raw_text: str) -> None:
        try:
            with self.session_factory.begin() as session:
                session.merge(
                    ContractRow(
                        id=contract.id,
                        filename=contract.filename,
                        content_type=contract.content_type,
                        sha256=contract.sha256,
                        size_bytes=contract.size_bytes,
                        page_count=contract.page_count,
                        status=contract.status.value,
                        raw_text=raw_text,
                        metadata_json=contract.metadata.model_dump(mode="json"),
                        created_at=contract.created_at,
                    )
                )
                session.query(ClauseRow).filter_by(contract_id=contract.id).delete()
                session.add_all([self._clause_to_row(clause) for clause in clauses])
        except Exception as exc:
            raise StorageError("Unable to save contract metadata in PostgreSQL.") from exc

    def get_contract(self, contract_id: str) -> ContractRecord:
        row = self._get_contract_row(contract_id)
        return ContractRecord(
            id=row.id,
            filename=row.filename,
            content_type=row.content_type,
            sha256=row.sha256,
            size_bytes=row.size_bytes,
            page_count=row.page_count,
            created_at=row.created_at,
            status=ContractStatus(row.status),
            metadata=ContractMetadata.model_validate(row.metadata_json or {}),
        )

    def get_clauses(self, contract_id: str) -> list[Clause]:
        with self.session_factory() as session:
            rows = (
                session.query(ClauseRow)
                .filter_by(contract_id=contract_id)
                .order_by(ClauseRow.start_char)
                .all()
            )
        if not rows:
            self._get_contract_row(contract_id)
        return [self._row_to_clause(row) for row in rows]

    def get_contract_text(self, contract_id: str) -> str:
        return self._get_contract_row(contract_id).raw_text

    def update_status(self, contract_id: str, status: str) -> None:
        with self.session_factory.begin() as session:
            row = session.get(ContractRow, contract_id)
            if row is None:
                raise NotFoundError(f"Contract '{contract_id}' was not found.")
            row.status = ContractStatus(status).value

    def save_job(self, job: JobRecord) -> None:
        try:
            with self.session_factory.begin() as session:
                session.merge(self._job_to_row(job))
        except Exception as exc:
            raise StorageError("Unable to save job metadata in PostgreSQL.") from exc

    def get_job(self, job_id: str) -> JobRecord:
        row = self._get_job_row(job_id)
        return self._row_to_job(row)

    def update_job(
        self,
        job_id: str,
        status: JobStatus,
        contract_id: str | None = None,
        result: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> JobRecord:
        with self.session_factory.begin() as session:
            row = session.get(JobRow, job_id)
            if row is None:
                raise NotFoundError(f"Job '{job_id}' was not found.")
            row.status = status.value
            row.updated_at = datetime.now(UTC)
            if contract_id is not None:
                row.contract_id = contract_id
            if result is not None:
                row.result_json = result
            if error is not None:
                row.error = error
            job = self._row_to_job(row)
        return job

    def save_audit_event(self, event: AuditEvent) -> None:
        try:
            with self.session_factory.begin() as session:
                session.merge(
                    AuditEventRow(
                        id=event.id,
                        action=event.action,
                        actor=event.actor,
                        contract_id=event.contract_id,
                        job_id=event.job_id,
                        metadata_json=event.metadata,
                        created_at=event.created_at,
                    )
                )
        except Exception as exc:
            raise StorageError("Unable to save audit event in PostgreSQL.") from exc

    def _get_contract_row(self, contract_id: str) -> ContractRow:
        with self.session_factory() as session:
            row = session.get(ContractRow, contract_id)
            if row is None:
                raise NotFoundError(f"Contract '{contract_id}' was not found.")
            session.expunge(row)
            return row

    def _get_job_row(self, job_id: str) -> JobRow:
        with self.session_factory() as session:
            row = session.get(JobRow, job_id)
            if row is None:
                raise NotFoundError(f"Job '{job_id}' was not found.")
            session.expunge(row)
            return row

    def _clause_to_row(self, clause: Clause) -> ClauseRow:
        return ClauseRow(
            id=clause.id,
            contract_id=clause.contract_id,
            type=clause.type.value,
            title=clause.title,
            text=clause.text,
            page_start=clause.page_start,
            page_end=clause.page_end,
            start_char=clause.start_char,
            end_char=clause.end_char,
            confidence=clause.confidence,
            source=clause.source,
        )

    def _row_to_clause(self, row: ClauseRow) -> Clause:
        return Clause(
            id=row.id,
            contract_id=row.contract_id,
            type=row.type,
            title=row.title,
            text=row.text,
            page_start=row.page_start,
            page_end=row.page_end,
            start_char=row.start_char,
            end_char=row.end_char,
            confidence=row.confidence,
            source=row.source,
        )

    def _job_to_row(self, job: JobRecord) -> JobRow:
        return JobRow(
            id=job.id,
            type=job.type.value,
            status=job.status.value,
            contract_id=job.contract_id,
            error=job.error,
            result_json=job.result,
            created_at=job.created_at,
            updated_at=job.updated_at,
        )

    def _row_to_job(self, row: JobRow) -> JobRecord:
        return JobRecord(
            id=row.id,
            type=JobType(row.type),
            status=JobStatus(row.status),
            contract_id=row.contract_id,
            error=row.error,
            result=row.result_json or {},
            created_at=row.created_at,
            updated_at=row.updated_at,
        )
