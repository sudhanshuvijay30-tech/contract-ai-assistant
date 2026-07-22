import json
from pathlib import Path

from app.core.errors import NotFoundError
from app.schemas.contracts import Clause, ContractRecord, ContractStatus


class JsonContractStore:
    def __init__(self, directory: Path):
        self.directory = directory
        self.directory.mkdir(parents=True, exist_ok=True)

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

