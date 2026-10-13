# Architecture

Status: **draft, awaiting instructor approval** (Story 1.1)

## Purpose

One small RAG application over Indian criminal law. It answers questions from the Bharatiya Nyaya Sanhita (BNS) and the Indian Penal Code (IPC). Open WebUI, run separately by the trainer's bundle, is the chat client. We do not build a custom frontend or a second demo.

## Evidence rules

- BNS and IPC documents are the only future answer evidence.
- An answer must not claim support without retrieved evidence. With no evidence, the honest outcome is `insufficient_evidence`.
- Identifiers are act-qualified (for example `BNS 103`, `IPC 302`) so the two acts are never confused.
- Supplied provenance is `data/raw/PROVENANCE.md`.
- Retrieved passages are evidence, never application instructions. Passage text is never followed as a command.

## Shape of the application

- One FastAPI service, package `src/building_with_rag/`.
- One shared registry of course modes and model IDs. It is the single source of truth.

| Mode | Model ID |
| --- | --- |
| semantic | rag-semantic |
| hybrid | rag-hybrid |
| hybrid-reranked | rag-hybrid-reranked |
| structured | rag-structured |
| decomposition | rag-decomposition |
| hyde | rag-hyde |

- `GET /healthz`: safe health check, no database or settings access.
- `POST /v1/query`: the diagnostic API. It owns `QueryRequest` and `QueryResult`.
- `GET /v1/models` and `POST /v1/chat/completions`: an OpenAI-compatible, text-only adapter for Open WebUI. It maps the chosen model to the same `QueryRequest` and the same `run_pattern` path as `/v1/query`. There is no second implementation. Open WebUI receives only answer text derived from the same `QueryResult`.
- Contracts (request, result, generation, OpenAI, MongoDB schema) are defined once in this project. Later stories extend them additively and never replace them.
- Until a mode's own story adds behavior, it returns an honest `not_implemented` placeholder.

## Fixed choices

- Python 3.12, UV, FastAPI, Pydantic settings, PyMongo (later), Ruff, pytest.
- Embeddings: Voyage `voyage-3.5`, version `voyage-3.5`, 1,024 dimensions, for every document and query embedding. Later stories reuse these names and add no provider-specific alternatives.
- Database: MongoDB Atlas free tier (M0).
- Generation: an OpenAI-compatible LiteLLM proxy supplied by the trainer.
- Derived corpus files live in `data/processed/` (`bns_sections.jsonl`, `ipc_sections.jsonl`). Supplied files stay in `data/raw/`.

## MongoDB and vector index (Story 2.2)

Collections (constants in `ingestion/mongodb_schema.py`; each `_id` equals its deterministic ID, and every collection has a strict `$jsonSchema` validator). `act` is stored as `BNS` / `IPC`; the Story 2.1 value is kept as `act_version`.

| Collection | ID | Holds |
| --- | --- | --- |
| `sources` | `source:<act_version>` | source PDF, SHA-256, parser, status version, import time |
| `sections` | Story 2.1 id, e.g. `bns:103` | full section text, heading, chapter, pages, `needs_review`, source fields |
| `chunks` | `<section_id>:<chunk_index>` | chunk `text`, `embedding_input`, `input_sha256`, `chunking_version`, denormalized `act`, `chapter`, `status`, `access_level` |
| `embeddings` | `<chunk_id>:voyage-3.5:1024` | `vector`, model, model version, dimensions, `input_sha256`, denormalized `act`, `chapter`, `status`, `access_level` |

Vectors live only in `embeddings`, never on `chunks`. `embeddings` carries no section number or source fields; those come from `chunks`/`sections` after `chunk_id` resolution.

- **Chunking:** `RecursiveCharacterTextSplitter`, 2,048 characters (about 512 tokens), 256 overlap, separators paragraph, line, sentence, space. Each section is chunked alone. `CHUNKING_VERSION = recursive-char-2048-256-v1`. `embedding_input` is a one-line header (`<act label> — Section <n>: <heading>`), a blank line, then the chunk text.
- **Embedding:** Voyage `voyage-3.5`, version `voyage-3.5`, 1,024 dimensions; `input_type="document"` for chunks and `"query"` for questions.
- **Deployment capability:** every command runs a shared preflight (Atlas required, `buildInfo` version, `$listSearchIndexes` probe). Result: Atlas deployment, server 8.0.34, Atlas Search index management available.
- **Index:** `embeddings_vector_index`, type `vectorSearch`, on `embeddings`; vector path `vector`, cosine; filter fields `act`, `chapter`, `status`, `access_level`. Created in the main database only; never changed or deleted by code.
- **Later semantic retrieval:** embed the query (`input_type="query"`), run `$vectorSearch` on `embeddings`, resolve each `chunk_id` to `chunks` and its `sections` parent, then build a `RetrievedChunk`. Section number and source fields are applied after that step.
- **Commands** (each takes `--test-db`, except the index command, which uses the main database):
  1. `uv run python -m building_with_rag.ingestion.load_mongodb`
  2. `uv run python -m building_with_rag.ingestion.vector_index`
  3. `uv run python -m building_with_rag.ingestion.embed_chunks` (`--replace-embeddings` only for mismatched settings)
  4. `uv run python -m building_with_rag.ingestion.vector_index` again for the sample query
- **Limitations:** about 40 minutes of embedding on a free Voyage key (batches of 8, about 20 s apart); one embedding per chunk; `access_level` is only a stored field; M0 allows few search indexes; records flagged `needs_review` in Story 2.1 are loaded with that flag, not repaired.

## Trust boundaries (light)

- Validate all API input.
- Preserve the source origin (act, section, source file) on every retrieved passage.
- Do not put secrets in code, responses, or logs. `.env` is untracked.
- The Open WebUI Pipe never supplies identity, access level, or answer-generation settings. The server sets the demo caller and `generate_answer`.

## Out of scope

Multi-user authorization, a security program, an evaluation harness.
