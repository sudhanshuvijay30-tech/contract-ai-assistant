import re
from pathlib import Path

from app.schemas.contracts import ContractMetadata


class ContractMetadataExtractor:
    def extract(
        self,
        filename: str,
        contract_text: str,
        overrides: ContractMetadata | None = None,
    ) -> ContractMetadata:
        overrides = overrides or ContractMetadata()
        inferred = ContractMetadata(
            contract_type=overrides.contract_type or self._contract_type(filename, contract_text),
            jurisdiction=overrides.jurisdiction or self._jurisdiction(contract_text),
            governing_law=overrides.governing_law or self._governing_law(contract_text),
            effective_date=overrides.effective_date or self._effective_date(contract_text),
            renewal_term=overrides.renewal_term or self._renewal_term(contract_text),
            customer=overrides.customer or self._party(contract_text, "customer"),
            supplier=overrides.supplier or self._party(contract_text, "supplier"),
        )
        return inferred

    def _contract_type(self, filename: str, text: str) -> str | None:
        haystack = f"{Path(filename).name} {text[:2000]}".lower()
        if "non-disclosure" in haystack or "nda" in haystack:
            return "NDA"
        if "master services" in haystack or "msa" in haystack:
            return "MSA"
        if "statement of work" in haystack or "sow" in haystack:
            return "SOW"
        if "license agreement" in haystack:
            return "License Agreement"
        return None

    def _governing_law(self, text: str) -> str | None:
        return self._first_match(
            text,
            (
                r"governed by (?:and construed in accordance with )?the laws of ([A-Za-z ,]+)",
                r"laws of the State of ([A-Za-z ,]+)",
            ),
        )

    def _jurisdiction(self, text: str) -> str | None:
        return self._first_match(
            text,
            (
                r"courts? (?:located )?in ([A-Za-z ,]+) shall have",
                r"exclusive jurisdiction (?:of|in) ([A-Za-z ,]+)",
            ),
        )

    def _effective_date(self, text: str) -> str | None:
        return self._first_match(
            text,
            (
                r"effective as of ([A-Za-z]+ \d{1,2}, \d{4})",
                r"effective date[:\s]+([A-Za-z]+ \d{1,2}, \d{4})",
                r"effective date[:\s]+(\d{4}-\d{2}-\d{2})",
            ),
        )

    def _renewal_term(self, text: str) -> str | None:
        return self._first_match(
            text,
            (
                r"renew(?:s|al)?(?: automatically)? for ([^.]{5,80})",
                r"successive renewal terms? of ([^.]{5,80})",
            ),
        )

    def _party(self, text: str, role: str) -> str | None:
        return self._first_match(
            text,
            (
                rf"{role}[:\s]+([A-Z][A-Za-z0-9 &.,'-]{{2,120}})",
                rf"{role} means ([A-Z][A-Za-z0-9 &.,'-]{{2,120}})",
            ),
        )

    def _first_match(self, text: str, patterns: tuple[str, ...]) -> str | None:
        for pattern in patterns:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if match:
                return match.group(1).strip(" .,\n\t")
        return None
