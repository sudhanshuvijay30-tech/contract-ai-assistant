# Contract AI Assistant

Production-ready AI assistant for contract review built with Python, FastAPI, LangGraph,
LangChain, OpenAI GPT-5, ChromaDB, Streamlit, and Docker.

## Capabilities

- PDF contract ingestion with text extraction.
- Deterministic clause segmentation and clause type classification.
- Optional GPT-5 clause refinement through LangChain structured output.
- LangGraph workflows for ingestion and risk analysis.
- ChromaDB vector indexing for contract-aware Q&A.
- Local deterministic embeddings by default, with optional OpenAI embeddings.
- Ollama-first local AI analysis, with optional GPT-5 through OpenAI.
- Streamlit web UI for uploading, reviewing, comparing, and asking about contracts.
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
  ui/           Streamlit app and FastAPI client
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

Docker Compose runs two services:

- `contract-ai-assistant-api` on port `8000`
- `contract-ai-assistant-ui` on port `8501`

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
| `MAX_UPLOAD_MB` | `25` | Upload size limit. |
| `STREAMLIT_API_BASE_URL` | `http://localhost:8000` | FastAPI URL used by Streamlit. |

## Production Notes

- Store secrets in a managed secret store, not in `.env`.
- Put the API behind TLS and authentication before exposing it outside a trusted network.
- Replace the JSON metadata store with Postgres or another transactional database when multiple
  API instances write concurrently.
- Treat GPT-5 output as decision support and keep human legal review in the workflow.
- Add authentication before exposing the Streamlit UI or FastAPI service outside a trusted network.
- Add background jobs for large PDFs and long-running GPT-5 analysis.
- Add OCR support for scanned PDFs.
- Add PDF or Word report exports for risk findings.
- Add deployment guides for managed hosts such as Render, Railway, Azure, AWS, or Fly.io.
