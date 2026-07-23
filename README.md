# Contract AI Assistant

Enterprise-ready AI assistant for contract review built with Python, FastAPI, LangGraph,
LangChain, OpenAI GPT-5, Ollama, ChromaDB, PostgreSQL, Redis/RQ, Streamlit, and Docker.

## Capabilities

- PDF contract ingestion with text extraction.
- Deterministic clause segmentation and clause type classification.
- Optional GPT-5 or Ollama clause refinement through structured output.
- Agentic LangGraph workflows for ingestion, metadata, retrieval, risk, compliance,
  negotiation, comparison, and Q&A.
- Metadata-aware ChromaDB vector indexing for contract-aware Q&A.
- Local deterministic embeddings by default, with optional OpenAI embeddings.
- Ollama-first local AI analysis, with optional GPT-5 through OpenAI.
- Bearer-token API authentication, rate limiting, request IDs, JSON production logs,
  Prometheus-style `/metrics`, and audit events.
- PostgreSQL metadata storage with Alembic migrations; JSON storage remains available for
  local fallback.
- Redis/RQ background ingestion jobs with inline local fallback.
- Streamlit web UI for uploading, reviewing, comparing, and asking about contracts.
- Rule-based offline analysis path for tests and local development.
- Docker and docker-compose deployment assets.
- CI for lint, tests, Docker build, dependency audit, and secret scanning.

## Architecture

```text
app/
  api/          FastAPI routes and dependency wiring
  core/         settings, logging, application errors
  graphs/       LangGraph workflow orchestration
  schemas/      Pydantic request and response models
  services/     PDF, clause parsing, GPT-5, comparison, risk rules
  storage/      JSON/Postgres metadata stores and ChromaDB vector repository
  ui/           Streamlit app and FastAPI client
  workers/      RQ background task entrypoints
alembic/        PostgreSQL migration scripts
tests/          offline unit tests
```

## Quickstart

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env
```

By default the app uses local embeddings and Ollama for LLM analysis:

```bash
ollama pull llama3.1:8b
```

Then run:

```bash
uvicorn app.main:app --reload
```

In another terminal, run the Streamlit UI:

```bash
streamlit run app/ui/streamlit_app.py
```

Open the main UI at `http://localhost:8501`.

By default, `EMBEDDING_PROVIDER=local`, so uploads, clause review, rule-based risk analysis,
clause comparison, and excerpt-based Q&A can run without OpenAI credits. Set
`LLM_PROVIDER=openai` and `EMBEDDING_PROVIDER=openai` when you want GPT-5 and OpenAI embeddings.
The Streamlit sidebar also includes an AI provider selector, so you can switch individual
AI-powered actions between Ollama and GPT/OpenAI without changing `.env` or restarting the app.

Local development uses `STORAGE_BACKEND=json`, `JOB_BACKEND=inline`, and `AUTH_ENABLED=false`
unless you change `.env`. For a public or enterprise deployment, set `AUTH_ENABLED=true` and
provide `API_AUTH_TOKEN`.

The Swagger API console is also available at `http://localhost:8000/docs` for testing raw API
requests.

On Windows PowerShell, you can run both apps without activating the virtual environment:

```powershell
& ".\.venv\Scripts\python.exe" -m uvicorn app.main:app --reload
& ".\.venv\Scripts\python.exe" -m streamlit run app/ui/streamlit_app.py
```

## Docker

```bash
cp .env.example .env
docker compose up --build
```

The Streamlit UI will be available at `http://localhost:8501`.

The FastAPI backend will be available at `http://localhost:8000`, with API docs at
`http://localhost:8000/docs`.

Docker Compose runs five services:

- `postgres` on port `5432`
- `redis` on port `6379`
- `contract-ai-assistant-api` on port `8000`
- `contract-ai-assistant-worker` for Redis/RQ background jobs
- `contract-ai-assistant-ui` on port `8501`

Compose overrides the app to use `STORAGE_BACKEND=postgres` and `JOB_BACKEND=rq`. If
`AUTH_ENABLED=true`, set `API_AUTH_TOKEN` in `.env`; Streamlit reads the same token through
`STREAMLIT_API_TOKEN`.

## API Examples

Upload and index a PDF:

```bash
curl -X POST "http://localhost:8000/contracts/upload?use_ai=false&contract_type=MSA" \
  -F "file=@sample-contract.pdf"
```

Queue a background upload:

```bash
curl -X POST "http://localhost:8000/contracts/upload-async?use_ai=false" \
  -F "file=@sample-contract.pdf"
```

Check a job:

```bash
curl "http://localhost:8000/jobs/{job_id}"
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
  -d '{
    "question": "What is the liability cap?",
    "top_k": 5,
    "metadata_filters": {"contract_type": "MSA"}
  }'
```

When auth is enabled, include:

```bash
-H "Authorization: Bearer <API_AUTH_TOKEN>"
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
| `ENVIRONMENT` | `development` | Use `production` for deployed services. |
| `AUTH_ENABLED` | `false` | Require bearer tokens for all endpoints except `/health`. |
| `API_AUTH_TOKEN` | empty | Shared bearer token for API access. Required when auth is enabled in production. |
| `RATE_LIMIT_PER_MINUTE` | `60` | In-memory per-client route limit. Set `0` to disable. |
| `LLM_PROVIDER` | `ollama` | Use `ollama` locally or `openai` for GPT-5. |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama server URL for local runs. |
| `OLLAMA_CHAT_MODEL` | `llama3.1:8b` | Ollama chat model used for AI analysis. |
| `OPENAI_API_KEY` | empty | Required only for GPT-5 analysis and OpenAI embeddings. |
| `OPENAI_MODEL` | `gpt-5` | Chat model used by LangChain. |
| `OPENAI_EMBEDDING_MODEL` | `text-embedding-3-large` | Embedding model used for ChromaDB indexing. |
| `EMBEDDING_PROVIDER` | `local` | Use `local` without OpenAI credits or `openai` for OpenAI embeddings. |
| `LOCAL_EMBEDDING_DIMENSIONS` | `384` | Vector size for local deterministic embeddings. |
| `CHROMA_PERSIST_DIRECTORY` | `data/chroma` | Local ChromaDB persistence path. |
| `CONTRACTS_DIRECTORY` | `data/contracts` | JSON metadata and extracted clause storage. |
| `UPLOADS_DIRECTORY` | `data/uploads` | Uploaded PDF storage path. |
| `STORAGE_BACKEND` | `json` | Use `json` locally or `postgres` for production metadata. |
| `DATABASE_URL` | `sqlite:///data/contracts.db` | SQLAlchemy database URL. Compose uses PostgreSQL. |
| `DATABASE_AUTO_CREATE` | `true` | Create SQL tables on startup for local/Compose runs. |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis URL for RQ jobs. |
| `JOB_BACKEND` | `inline` | Use `inline` local background tasks or `rq` Redis-backed jobs. |
| `RQ_QUEUE_NAME` | `contract-ai-assistant` | RQ queue name. |
| `MAX_UPLOAD_MB` | `25` | Upload size limit. |
| `ALLOWED_PDF_CONTENT_TYPES` | PDF MIME list | Accepted upload MIME types. |
| `STREAMLIT_API_BASE_URL` | `http://localhost:8000` | FastAPI URL used by Streamlit. |
| `STREAMLIT_API_TOKEN` | empty | Bearer token sent by Streamlit when API auth is enabled. |

## Database Migrations

Alembic migration files are included for the PostgreSQL metadata layer:

```bash
alembic upgrade head
```

For local Docker Compose demos, `DATABASE_AUTO_CREATE=true` creates the tables automatically.
Use Alembic-managed migrations for shared or production databases.

## Codespaces

In GitHub Codespaces:

```bash
pip install -r requirements-dev.txt
cp .env.example .env
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
python -m streamlit run app/ui/streamlit_app.py --server.address 0.0.0.0 --server.port 8501
```

Forward ports `8000` and `8501`. Swagger is for API testing; Streamlit is the main user UI.

## Production Notes

- Store secrets in a managed secret store, not in `.env`.
- Set `AUTH_ENABLED=true`, provide `API_AUTH_TOKEN`, and place the API behind TLS.
- Use `STORAGE_BACKEND=postgres`, managed PostgreSQL, managed Redis, and persistent Chroma storage.
- Treat GPT-5 output as decision support and keep human legal review in the workflow.
- For Azure, map the architecture to Azure Container Apps, Azure OpenAI, Azure AI Search or
  Chroma-compatible vector storage, Azure Blob Storage, Azure Database for PostgreSQL,
  Azure Cache for Redis, and Application Insights.
- Keep Ollama for local/private deployments; use OpenAI/Azure OpenAI for public hosted deployments.
- Add OCR support for scanned PDFs.
- Add PDF or Word report exports for risk findings.
- Add Azure AD/Auth0 when multi-user organization access is required.
