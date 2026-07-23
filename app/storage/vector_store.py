import hashlib
import math
import re

from langchain_core.embeddings import Embeddings

from app.core.config import Settings
from app.core.errors import VectorStoreError
from app.schemas.contracts import Clause, ContractMetadata, VectorSearchResult

TOKEN_RE = re.compile(r"[a-zA-Z][a-zA-Z0-9_-]{1,}")


class LocalHashEmbeddings(Embeddings):
    def __init__(self, dimensions: int = 384):
        self.dimensions = dimensions

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._embed(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed(text)

    def _embed(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        tokens = TOKEN_RE.findall(text.lower())
        for token in tokens:
            digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
            index = int.from_bytes(digest[:4], byteorder="big") % self.dimensions
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vector[index] += sign

        norm = math.sqrt(sum(value * value for value in vector))
        if not norm:
            return vector
        return [value / norm for value in vector]


class ContractVectorRepository:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._store = None

    @property
    def collection_name(self) -> str:
        if self.settings.embedding_provider == "local":
            return f"{self.settings.chroma_collection_name}_local"
        return self.settings.chroma_collection_name

    def upsert_clauses(
        self,
        clauses: list[Clause],
        contract_metadata: ContractMetadata | None = None,
    ) -> None:
        if not clauses:
            return
        try:
            from langchain_core.documents import Document
        except ImportError as exc:
            raise RuntimeError("langchain-core is required for vector indexing") from exc

        contract_metadata_values = (
            contract_metadata.vector_metadata() if contract_metadata is not None else {}
        )
        documents = []
        for clause in clauses:
            metadata = {
                "contract_id": clause.contract_id,
                "clause_id": clause.id,
                "title": clause.title,
                "type": clause.type.value,
                "page_start": clause.page_start,
                "page_end": clause.page_end,
                "source": clause.source,
                **contract_metadata_values,
            }
            documents.append(
                Document(
                    page_content=clause.text,
                    metadata={key: value for key, value in metadata.items() if value is not None},
                )
            )
        ids = [clause.id for clause in clauses]
        try:
            self._ensure_store().add_documents(documents, ids=ids)
        except VectorStoreError:
            raise
        except Exception as exc:
            raise VectorStoreError("Unable to index clauses in ChromaDB.") from exc

    def search(
        self,
        contract_id: str,
        query: str,
        top_k: int,
        metadata_filters: dict[str, str] | None = None,
    ) -> list[VectorSearchResult]:
        where = self._build_where(contract_id, metadata_filters or {})
        try:
            results = self._ensure_store().similarity_search_with_relevance_scores(
                query,
                k=top_k,
                filter=where,
            )
        except VectorStoreError:
            raise
        except Exception as exc:
            raise VectorStoreError("Unable to search clauses in ChromaDB.") from exc

        return [
            VectorSearchResult(
                clause_id=str(document.metadata.get("clause_id", "")),
                text=document.page_content,
                score=score,
                metadata=document.metadata,
            )
            for document, score in results
            if document.metadata.get("clause_id")
        ]

    def _ensure_store(self):
        if self._store is not None:
            return self._store

        try:
            from langchain_chroma import Chroma
        except ImportError as exc:
            raise RuntimeError("langchain-chroma is required for ChromaDB") from exc

        self.settings.chroma_persist_directory.mkdir(parents=True, exist_ok=True)
        embeddings = self._build_embeddings()
        self._store = Chroma(
            collection_name=self.collection_name,
            persist_directory=str(self.settings.chroma_persist_directory),
            embedding_function=embeddings,
        )
        return self._store

    def _build_embeddings(self) -> Embeddings:
        if self.settings.embedding_provider == "local":
            return LocalHashEmbeddings(self.settings.local_embedding_dimensions)

        api_key = self.settings.openai_api_key_value
        if not api_key:
            raise VectorStoreError("OPENAI_API_KEY is required for OpenAI embeddings and ChromaDB.")

        try:
            from langchain_openai import OpenAIEmbeddings
        except ImportError as exc:
            raise RuntimeError("langchain-openai is required for OpenAI embeddings") from exc

        return OpenAIEmbeddings(
            model=self.settings.openai_embedding_model,
            api_key=api_key,
        )

    def _build_where(self, contract_id: str, metadata_filters: dict[str, str]) -> dict:
        filters = [{"contract_id": contract_id}]
        filters.extend(
            {key: value}
            for key, value in metadata_filters.items()
            if key in ContractMetadata.model_fields and value
        )
        if len(filters) == 1:
            return filters[0]
        return {"$and": filters}
