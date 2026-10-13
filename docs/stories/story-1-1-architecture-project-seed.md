# Story 1.1 — Architecture and project seed

Status: ready for implementation

This story is for a coding assistant working in the capstone repository. It is the first story in a three-day classroom RAG course. It builds one small application. It does not build a custom chat frontend or a second demo.

## Purpose

Record the architecture, get the instructor's approval, then seed a small FastAPI project. The seed fixes the shared contracts (request, result, generation, OpenAI, MongoDB schema) that every later story extends additively. It exposes honest placeholders only. Open WebUI, supplied separately by the trainer, is the chat client.

## Prerequisites

- Python 3.12 and UV are installed.
- The repository root is the project path. At the time of writing there is no `docs/config.yaml`. If one exists when you start, read it and use the project path it configures.
- Supplied files under `data/raw/` (including `data/raw/PROVENANCE.md`) are kept exactly as supplied. If `data/raw/` is absent, do not invent it. Note this in the handover.
- The Open WebUI bundle ZIP has been shared by the trainer over the local LAN. The participant has extracted it and run its setup script once (see "Open WebUI" below).
- Existing work in the repository is preserved. Do not delete or overwrite `.postman/`, `postman/`, `.gitignore` content, or supplied data. Merge into `.gitignore` rather than replacing it.

## Before you start

Read, in this order, whichever exist: `docs/config.yaml`, `docs/architecture.md`, the repository layout, and other files in `docs/stories/`. Update existing content instead of duplicating it.

## Work to do

### Part A — Architecture (do this first, then stop)

1. Create or update `docs/architecture.md`. Keep it short and in plain English. It must record:
   - BNS and IPC documents are the only future answer evidence.
   - An answer must not claim support without retrieved evidence.
   - Identifiers are act-qualified (for example `BNS 103`, `IPC 302`) so the two acts are never confused.
   - Supplied provenance is `data/raw/PROVENANCE.md`.
   - Retrieved passages are evidence, never application instructions.
   - Light trust-boundary notes: validate API input, preserve source origin, and do not put secrets in code, responses, or logs.
   - Fixed embedding choice: Voyage `voyage-3.5`, version `voyage-3.5`, 1,024 dimensions, for every document and query embedding. Later stories reuse these names without renaming or adding provider-specific alternatives.
   - Derived corpus files live in `data/processed/` (`bns_sections.jsonl`, `ipc_sections.jsonl`).
   - The one-application shape: FastAPI service, `/v1/query` as the diagnostic API, `/v1/chat/completions` as the adapter for Open WebUI, one shared registry of modes.
   - Out of scope: multi-user authorization, a security program, an evaluation harness.
2. **STOP.** Ask the instructor to approve `docs/architecture.md`. Before approval, do not create seed files, install dependencies, or scaffold code.
3. Resume this same story only after explicit approval. Record the approval (who, when) in the handover section.

### Part B — Seed (only after approval)

**Project setup.** Python 3.12 and UV project with FastAPI, Pydantic settings, PyMongo (for later use only), Ruff, and a minimal test runner (pytest). Create:

- `src/building_with_rag/`
- `tests/`
- `.env.example`
- `.gitignore` (merged with the existing one)
- `pyproject.toml`
- `uv.lock`
- preserve supplied `data/raw/` files

**`.env.example`.** This is the classroom project's canonical file. Use exactly these values:

```
APP_ENV=development
MONGODB_URI=
MONGODB_DB_NAME=building_with_rag
MONGODB_TEST_DB_NAME=building_with_rag_test
VOYAGE_API_KEY=
CAPSTONE_API_KEY=
WEBUI_DEMO_CALLER_ID=demo-public
GENERATION_API_BASE_URL=
GENERATION_API_KEY=
GENERATION_MODEL_NAME=gpt-4o-mini
RERANK_API_BASE_URL=https://api.voyageai.com/v1
RERANK_API_KEY=
RERANK_MODEL_NAME=rerank-2.5
RERANK_REQUEST_TIMEOUT_SECONDS=30
RERANK_CANDIDATE_LIMIT=20
RERANK_SEND_LIMIT=10
RERANK_RETURN_LIMIT=5
```

Document (in `.env.example` comments and/or a short README note) that:

- `.env` is untracked and secrets are never committed.
- `GENERATION_API_BASE_URL` and `GENERATION_API_KEY` are supplied by the trainer for an OpenAI-compatible LiteLLM proxy. They stay blank in `.env.example`; fill them in `.env` only when Story 3.1 needs them.
- `MONGODB_URI` is an Atlas free-tier (M0) connection string, and the Atlas IP access list must allow your machine.
- A free Voyage key is rate limited, so Story 2.2 embedding takes about 40 minutes.

**Startup and health.** The application starts with no database or model credentials. `GET /healthz` returns a safe fixed payload (for example `{"status": "ok"}`) and never touches the database or reveals settings.

**Shared mode registry.** One registry, the single source of truth, containing only these modes and model IDs:

| Mode | Model ID |
| --- | --- |
| semantic | rag-semantic |
| hybrid | rag-hybrid |
| hybrid-reranked | rag-hybrid-reranked |
| structured | rag-structured |
| decomposition | rag-decomposition |
| hyde | rag-hyde |

Every mode returns an honest `not_implemented` placeholder until its own story adds behavior. Do not fake retrieval or answers.

**Typed contracts (models only, no behavior).** Define these in this project, with these exact names. Later stories extend them additively and never replace them with simplified alternatives.

- `GenerationResult`: `outcome` (`answered`, `insufficient_evidence`, `unavailable`, `malformed`), `answer`, `claims`, `citations`, `supporting_passages`, `provider`, `model`, `trace`, `context_outcome`, and the confidence fields `confidence`, `draft_answer`, `issues`, `attempts`, `low_confidence_reason`.
- `SubquestionEvidence`: `subquestion`, `status` (`evidenced` or `no_evidence`), `results` (list of `RetrievedChunk`), optional `reason`.
- `StructuredSignals`: `intent` (`exact_lookup`, `filter`, or `aggregation`) plus optional `act`, `section_number`, `chapter`. Story 5.1 fills these in.
- `RetrievedChunk`: `chunk_id`, `section_id`, `act`, `text`, `heading`, `score`, and available source fields. Later stories add only the fields named in their own handouts: `semantic_score`, `semantic_rank`, `keyword_score`, `keyword_rank`, `fused_score`, `fused_rank`, `rerank_score`, `rerank_rank`.
- `omitted_candidates` items carry `chunk_id` and `omitted_reason`.
- `SemanticFilters`: `act`, `status`, `access_level`, each a list.
- OpenAI-compatible models (below) and the MongoDB-schema contract models, defined as types only. No MongoDB provisioning.

**`POST /v1/query`.** Accepts the compatible `QueryRequest`:

- `question` (1–4,000 characters)
- `pattern`
- optional `caller_id`
- optional `SemanticFilters`
- `limit` (default 5, range 1–20)
- `generate_answer` (default false)
- `required_acts`
- `chapter`

The seed resolves only its fixed local demo caller (`WEBUI_DEMO_CALLER_ID`) but keeps the `caller_id` field. Do not replace the request with a custom shape. Returns the compatible `QueryResult`: `pattern`, `status`, `message`, `trace`, `results`, optional `generation`, plus the additive empty-by-default fields `omitted_candidates`, `subquestions`, `hyde_direct_candidates`, `hyde_query_candidates`, `hyde_hypothetical_text_debug`. Do not add outcome, evidence, answer, confidence, citations, or diagnostics as parallel top-level fields. Invalid input is rejected by validation.

**`GET /v1/models` and `POST /v1/chat/completions`.**

- `/v1/models` lists the six model IDs from the registry.
- `/v1/chat/completions` accepts the compatible text-only `ChatCompletionRequest`: `model`, text `messages` with roles `system`/`developer`/`user`/`assistant`, `stream`, `n`, and optional strict `rag_options` (`pattern`, list filters, `limit`, `required_acts`, `chapter`).
- It maps the selected model to the same `QueryRequest` and calls the same `run_pattern` path as `/v1/query`. The server sets the demo `caller_id` and `generate_answer`. Do not duplicate the implementation.
- Non-streaming returns normal OpenAI Chat Completions JSON.
- Streaming returns SSE frames with a `role` chunk, `content` chunk(s), a `stop` chunk, and `data: [DONE]`. Do not invent custom SSE events.
- Errors before streaming starts use the OpenAI-style error envelope.
- Open WebUI receives only normal answer text derived from the same `QueryResult`. `/v1/query` owns the diagnostics.

**Open WebUI.** Use the trainer-supplied bundle as a separately running chat client.

- Participants extract the ZIP and run the setup script exactly once, from the bundle root, before using this project:
  - Windows (primary classroom path): `powershell -ExecutionPolicy Bypass -File .\setup_open_webui.ps1`
  - macOS/Linux: `sh setup_open_webui.sh` (needs internet access on first install)
- The script installs the pinned Open WebUI version, writes the course settings, starts the loopback-only service, and provisions the RAG options Filter and the Building with RAG Pipe.
- Do not hand-install Open WebUI, create accounts, edit the admin panel, change either Function, or rerun setup to reload anything. If setup fails, report its exact output and stop.
- Day-to-day start/stop/status uses the supplied `manage_open_webui` script.
- The pre-provisioned Pipe sends the selected `rag-<pattern>` model, `stream: true`, the latest user message, and normalized `rag_options` to `/v1/chat/completions`. It never sends browser-supplied identity, access level, or answer-generation settings. The adapter must accept exactly that request.
- Later stories render final confidence, sources, and low-confidence warnings as clearly labelled text after the answer, while the full `GenerationResult` stays in `QueryResult.generation`. They extend contracts additively and do not replace endpoints or rebuild the UI.

## Do not do

No retrieval, PDF parsing, embeddings, MongoDB provisioning, LLM calls, GraphRAG, agentic RAG, broad deployment, or aggressive testing.

## Completion checks

Keep checks lightweight. Run and record each one:

1. `uv sync` succeeds; `uv.lock` exists.
2. `uv run ruff check .` passes.
3. `uv run pytest` passes (minimal tests).
4. Start the app with no `.env` credentials (for example `uv run uvicorn building_with_rag.main:app`). It starts.
5. `GET /healthz` returns the safe payload.
6. One `POST /v1/query` with `pattern: semantic` returns a `QueryResult` with a `not_implemented` status and an honest message.
7. `GET /v1/models` lists the six model IDs.
8. `POST /v1/chat/completions` returns the placeholder as normal JSON, and as SSE ending in `[DONE]` with `stream: true`.
9. Open WebUI smoke check: start the capstone API, open http://127.0.0.1:8080, select **Building with RAG**, choose **semantic** in the RAG-options chip, and send a question. The reply must be the capstone's honest placeholder, not a local preview.

## Handover

Status: seed done; Open WebUI smoke check NOT done.

- Instructor approval of `docs/architecture.md`: approved by the instructor ("approve") in the assistant session, 2026-10-13.
- Files created or changed: `docs/architecture.md`, `.env.example`, `.gitignore` (appended cache/egg-info lines), `.python-version`, `pyproject.toml`, `uv.lock`, `README.md`, `src/building_with_rag/{__init__,settings,registry,contracts,patterns,main}.py`, `tests/test_app.py`.
- Commands run: `uv sync` (ok, lock written); `uv run ruff check .` (all checks passed); `uv run pytest -q` (6 passed); `uv run uvicorn building_with_rag.main:app --port 8000` with no `.env` (started); curl `GET /healthz` (`{"status":"ok"}`); curl `POST /v1/query` semantic (`not_implemented`); curl `GET /v1/models` (six IDs); curl `POST /v1/chat/completions` with `stream: true` and `rag_options` (role, content, stop, `[DONE]` frames); JSON chat covered by pytest.
- Open WebUI result: not run. http://127.0.0.1:8080 did not respond (no connection), and the trainer's bundle was not found on this machine, so setup was not attempted. The seed's adapter accepts the Pipe's described request shape, but this is unverified against the real Pipe.
- Skipped or open: Open WebUI smoke check (needs the trainer bundle installed and running). `data/raw/` and `PROVENANCE.md` do not exist in this repo, so nothing was preserved or created there. A `rag_options.pattern`, when present, overrides the pattern implied by the model ID. Python 3.13 is installed locally; UV provisioned 3.12 for the project.

Later stories reuse the names, endpoints, registry, and contracts from this story as they are.
