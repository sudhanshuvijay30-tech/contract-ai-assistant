from app.core.config import Settings
from app.core.errors import VectorStoreError
from app.schemas.contracts import Clause, VectorSearchResult


class ContractVectorRepository:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._store = None

    def upsert_clauses(self, clauses: list[Clause]) -> None:
        if not clauses:
            return
        try:
            from langchain_core.documents import Document
        except ImportError as exc:
            raise RuntimeError("langchain-core is required for vector indexing") from exc

        documents = [
            Document(
                page_content=clause.text,
                metadata={
                    "contract_id": clause.contract_id,
                    "clause_id": clause.id,
                    "title": clause.title,
                    "type": clause.type.value,
                    "page_start": clause.page_start,
                    "page_end": clause.page_end,
                    "source": clause.source,
                },
            )
            for clause in clauses
        ]
        ids = [clause.id for clause in clauses]
        try:
            self._ensure_store().add_documents(documents, ids=ids)
        except Exception as exc:
            raise VectorStoreError("Unable to index clauses in ChromaDB.") from exc

    def search(self, contract_id: str, query: str, top_k: int) -> list[VectorSearchResult]:
        try:
            results = self._ensure_store().similarity_search_with_relevance_scores(
                query,
                k=top_k,
                filter={"contract_id": contract_id},
            )
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

        api_key = self.settings.openai_api_key_value
        if not api_key:
            raise VectorStoreError("OPENAI_API_KEY is required for OpenAI embeddings and ChromaDB.")

        try:
            from langchain_chroma import Chroma
            from langchain_openai import OpenAIEmbeddings
        except ImportError as exc:
            raise RuntimeError(
                "langchain-chroma and langchain-openai are required for ChromaDB"
            ) from exc

        self.settings.chroma_persist_directory.mkdir(parents=True, exist_ok=True)
        embeddings = OpenAIEmbeddings(
            model=self.settings.openai_embedding_model,
            api_key=api_key,
        )
        self._store = Chroma(
            collection_name=self.settings.chroma_collection_name,
            persist_directory=str(self.settings.chroma_persist_directory),
            embedding_function=embeddings,
        )
        return self._store
