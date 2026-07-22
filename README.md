# Contract AI Assistant

Production-ready AI assistant for contract review built with Python, FastAPI, LangGraph,
LangChain, OpenAI GPT-5, ChromaDB, and Docker.

## Capabilities

- PDF contract ingestion with text extraction.
- Deterministic clause segmentation and clause type classification.
- Optional GPT-5 clause refinement through LangChain structured output.
- LangGraph workflows for ingestion and risk analysis.
- ChromaDB vector indexing for contract-aware Q&A.
- GPT-5 risk analysis, clause comparison, and grounded contract Q&A.
- Rule-based offline analysis path for tests and local development.
- Docker and docker-compose deployment assets.
- Unit tests with mocked external dependencies.

## Architecture

```text
app/
  api/          FastAPI routes and dependency wiring
  core/         settings, logging, application errors
  graphs/       LangGraph workflow orchestration
  schemas/      Pydantic request and response models
  services/     PDF, clause parsing, GPT-5, comparison, risk rules
  storage/      JSON contract metadata store and ChromaDB vector repository
tests/          offline unit tests
```

## Quickstart

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env
```

Set `OPENAI_API_KEY` in `.env`, then run:

```bash
uvicorn app.main:app --reload
```

Open the API docs at `http://localhost:8000/docs`.

## Docker

```bash
cp .env.example .env
docker compose up --build
```

The API will be available at `http://localhost:8000`.

## API Examples

Upload and index a PDF:

```bash
curl -X POST "http://localhost:8000/contracts/upload?use_ai=false" \
  -F "file=@sample-contract.pdf"
```

List extracted clauses:

```bash
curl "http://localhost:8000/contracts/{contract_id}/clauses"
```

Analyze risks with GPT-5:

```bash
curl -X POST "http://localhost:8000/contracts/{contract_id}/risks" \
  -H "Content-Type: application/json" \
  -d '{"use_llm": true}'
```

Compare clauses:

```bash
curl -X POST "http://localhost:8000/compare" \
  -H "Content-Type: application/json" \
  -d '{
    "source_clause": {"title": "Liability Cap", "text": "Each party liability is capped at fees paid in the prior twelve months."},
    "counterparty_clause": {"title": "Liability", "text": "Supplier liability is unlimited for all claims."},
    "preferred_position": "Mutual cap at twelve months fees.",
    "use_llm": true
  }'
```

Ask a contract question:

```bash
curl -X POST "http://localhost:8000/contracts/{contract_id}/ask" \
  -H "Content-Type: application/json" \
  -d '{"question": "What is the liability cap?", "top_k": 5}'
```

## Testing

```bash
pytest
ruff check .
```

The unit tests avoid live OpenAI and ChromaDB calls by using deterministic fakes.

## Configuration

| Variable | Default | Description |
| --- | --- | --- |
| `OPENAI_API_KEY` | empty | Required for GPT-5 analysis and OpenAI embeddings. |
| `OPENAI_MODEL` | `gpt-5` | Chat model used by LangChain. |
| `OPENAI_EMBEDDING_MODEL` | `text-embedding-3-large` | Embedding model used for ChromaDB indexing. |
| `CHROMA_PERSIST_DIRECTORY` | `data/chroma` | Local ChromaDB persistence path. |
| `CONTRACTS_DIRECTORY` | `data/contracts` | JSON metadata and extracted clause storage. |
| `UPLOADS_DIRECTORY` | `data/uploads` | Uploaded PDF storage path. |
| `MAX_UPLOAD_MB` | `25` | Upload size limit. |

## Production Notes

- Store secrets in a managed secret store, not in `.env`.
- Put the API behind TLS and authentication before exposing it outside a trusted network.
- Replace the JSON metadata store with Postgres or another transactional database when multiple
  API instances write concurrently.
- Treat GPT-5 output as decision support and keep human legal review in the workflow.
