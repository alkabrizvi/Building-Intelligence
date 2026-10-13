# Story 2.2 — MongoDB collections, chunks, embeddings, and vector index

Status: ready for implementation

This story follows Story 2.1. It reuses the same application, `docs/architecture.md`, and the existing `.env.example` contract. It adds no settings and renames none. Create no retrieval endpoint: `/healthz`, `/v1/query`, `/v1/models`, and `/v1/chat/completions` stay exactly as Story 1.1 left them, and every mode still returns `not_implemented`.

## Purpose

Load the Story 2.1 corpus into MongoDB, split it into chunks, embed each chunk with Voyage, and create an Atlas vector index over the embeddings. This prepares searchable evidence in the same database the app already uses. Retrieval, answer generation, hybrid search, re-ranking, and a separate vector store belong to later stories.

## Prerequisites

- Stories 1.1 and 2.1 are complete: `uv sync` works and `data/processed/bns_sections.jsonl` and `data/processed/ipc_sections.jsonl` exist (at the time of writing: 358 BNS and 550 IPC records). If either file is missing, report it and stop. Do not regenerate or edit the corpus here.
- An untracked `.env` (copied from `.env.example`) holds `MONGODB_URI` (Atlas free M0 connection string, with this machine allowed in the Atlas IP access list) and `VOYAGE_API_KEY`. `MONGODB_DB_NAME` and `MONGODB_TEST_DB_NAME` keep their `.env.example` values. These four are the only settings this story uses. Do not add, rename, or remove any variable.
- If `docs/config.yaml` exists when you start, read it and use the paths it configures. At the time of writing there is none.
- Existing work is preserved: `.postman/`, `postman/`, `data/raw/`, `data/processed/`, `.gitignore`, and the existing contracts, routes, and registry.

## Before you start

Read, in this order, whichever exist: `docs/config.yaml`, `docs/architecture.md`, Stories 1.1 and 2.1, `src/building_with_rag/` (especially `settings.py`, `contracts.py`, `ingest.py`), and the two JSONL files. Update existing content instead of duplicating it.

Fixed choices to reuse, not guess (from `docs/architecture.md`): Voyage `voyage-3.5`, version `voyage-3.5`, 1,024 dimensions, for every document and query embedding. MongoDB Atlas free tier (M0).

## Work to do

### 0. Credential hygiene

`src/building_with_rag/settings.py` currently has a real-looking Voyage key as the default for `voyage_api_key`. Change that default to an empty string, so the key is read only from `.env`. Do not print, log, or commit any key or connection string. Tell the participant that key was committed to the working tree and should be rotated. Make no other change to `Settings`.

### 1. Preflight: deployment and capability check

Add one shared preflight used by every command below. It must:

1. Stop with a clear prerequisite message, naming the setting but never its value, if `MONGODB_URI` is empty, the server cannot be reached, or authentication fails.
2. Identify the deployment: is it Atlas (an `mongodb+srv://` URI or a `*.mongodb.net` host), and what server version does `buildInfo` report. Print only the class of deployment and the version, never the URI.
3. Probe Atlas Search index management by running `$listSearchIndexes` (PyMongo `list_search_indexes`) on the target collection. If the deployment is not Atlas, the command is unsupported, or the user lacks the privilege, stop with a message saying exactly which prerequisite is missing. Do not fall back to a generic index, a local vector store, or a different mechanism.
4. Print the capability found, for example "Atlas deployment, server X.Y, Atlas Search index management available". Record it in the handover and `docs/architecture.md`.

The documented API is PyMongo's `Collection.create_search_index` with `SearchIndexModel(..., type="vectorSearch")`, plus `list_search_indexes` and the `$vectorSearch` aggregation stage. The project already requires `pymongo>=4.8`.

Every command takes `--test-db` to use `MONGODB_TEST_DB_NAME` instead of `MONGODB_DB_NAME`. Tests use the test database only. Atlas M0 allows a small number of search indexes, so create the index in the main database only.

### 2. Schema module: `src/building_with_rag/ingestion/mongodb_schema.py`

Create the `ingestion` package (with `__init__.py`). Leave `ingest.py` and its command (`python -m building_with_rag.ingest`) as they are. Put these in `mongodb_schema.py` and import them everywhere else; nothing is redefined elsewhere:

- Collection-name constants: `SOURCES = "sources"`, `SECTIONS = "sections"`, `CHUNKS = "chunks"`, `EMBEDDINGS = "embeddings"`.
- Constants for the fixed choices: `EMBEDDING_MODEL = "voyage-3.5"`, `EMBEDDING_MODEL_VERSION = "voyage-3.5"`, `EMBEDDING_DIMENSIONS = 1024`, `ACCESS_LEVEL_PUBLIC = "public"`, `VECTOR_INDEX_NAME = "embeddings_vector_index"`, `VECTOR_PATH = "vector"`, `CHUNKING_VERSION` (see section 3).
- One `$jsonSchema` validator per collection (strict level, error action), applied when the collection is created, or with `collMod` if it already exists.
- Deterministic ID helpers and ordinary index definitions, below.
- A single `ensure_collections(db)` that creates the four collections, validators, and ordinary indexes, and is safe to repeat.

**Act values.** In MongoDB the `act` field is `BNS` or `IPC`, matching `ChunkDocument.act` and `SemanticFilters.act`. The importer maps `BNS_2023` to `BNS` and `IPC_1860` to `IPC`, and keeps the original value in `act_version`. `status` stays `in_force` / `repealed`. Do not change `contracts.py`. `ChunkDocument` has an optional `embedding` field, but this story never stores vectors on chunks. The `chunks` and `embeddings` documents defined here are the stored shapes.

**Four collections, not merged.** Each document's `_id` equals its deterministic ID, which is also stored in a named field.

| Collection | ID | Holds |
| --- | --- | --- |
| `sources` | `source_id` = `source:<act_version>`, e.g. `source:BNS_2023` | `source_pdf`, `source_sha256`, `act`, `act_version`, `act_label`, `status`, `parser`, `parser_version`, `source_status_version`, `imported_at` |
| `sections` | `section_id` = the Story 2.1 id, e.g. `bns:103` | `source_id`, `act`, `act_version`, `act_label`, `status`, `chapter`, `chapter_title`, `section_number`, `heading`, `text`, `text_sha256`, `source_pdf`, `source_sha256`, `page_start`, `page_end`, `needs_review`, `access_level` |
| `chunks` | `chunk_id` = `<section_id>:<chunk_index>`, e.g. `bns:103:0` | `section_id`, `source_id`, `chunk_index`, `chunking_version`, `splitter`, `text`, `embedding_input`, `input_sha256`, denormalized `act`, `chapter`, `status`, `access_level` |
| `embeddings` | `embedding_id` = `<chunk_id>:<model>:<dimensions>`, e.g. `bns:103:0:voyage-3.5:1024` | `chunk_id`, `model`, `model_version`, `dimensions`, `vector`, `input_sha256`, `created_at`, denormalized `act`, `chapter`, `status`, `access_level` |

- Use `access_level="public"` on every section, chunk, and embedding. Keep the field; do not build access control.
- `embeddings` does not carry `section_number`, `section_id`, or source identifiers. Those stay on `chunks`/`sections` and are applied after `chunk_id` resolution.
- The `embeddings.vector` validator is an array of numbers whose length is `EMBEDDING_DIMENSIONS`.
- Ordinary indexes (unique where the ID or pair must be unique): `sections` on `(source_id)`, `(act, section_number)`; `chunks` on unique `(section_id, chunk_index)`, `(act, chapter)`; `embeddings` on unique `chunk_id` + `model` + `dimensions`, and `chunk_id`.

### 3. Chunking

- Chunk each section's `text` on its own. Never join text across sections or acts.
- Target about 512 tokens, which is about 2,048 characters, with about 256 characters of overlap. Use `RecursiveCharacterTextSplitter` from `langchain-text-splitters` (add it with `uv add langchain-text-splitters`; it is the one new splitting dependency) with `chunk_size=2048`, `chunk_overlap=256`, and separators paragraph, line, sentence, space in that order. A section of 2,048 characters or fewer becomes one chunk.
- Set `CHUNKING_VERSION` to a string that encodes the choice, for example `recursive-char-2048-256-v1`. Store it, and the splitter name and version, on every chunk.
- `embedding_input` is the chunk text with a one-line header so every chunk names its own act and section, for example `Bharatiya Nyaya Sanhita, 2023 — Section 103: Punishment for murder` followed by a blank line and the chunk text. `text` stays the plain chunk text and is what later stories show as evidence.
- `input_sha256` is the SHA-256 of `embedding_input`.

### 4. Load command: sources, sections, chunks

Provide `uv run python -m building_with_rag.ingestion.load_mongodb`. It runs the preflight, calls `ensure_collections`, then upserts `sources`, `sections`, and `chunks` from the two JSONL files by deterministic `_id`. It needs no Voyage call.

Re-run rules. Print one summary line per collection: inserted, unchanged, changed, removed.

- Unchanged data is reused: if a section's `text_sha256`, a chunk's `input_sha256`, and the `chunking_version` match, do nothing.
- If a source's `source_sha256` changed, treat that whole act as replaced: update `sources`, and report. Never leave sections from two source versions of one act.
- If a chunk's `input_sha256` or `chunking_version` changed, replace that chunk and delete its stale embeddings, and report the count.
- If a section now has fewer chunks, or a section is gone, delete its orphaned chunks and their embeddings, and report the count.
- Removal covers only derived records this story created. It never drops a collection or an index.

### 5. Embed command

Provide `uv run python -m building_with_rag.ingestion.embed_chunks`. Add `voyageai` with `uv add voyageai` (the official client; add nothing else for embedding). Use `VOYAGE_API_KEY` from `.env`, model `EMBEDDING_MODEL`, `output_dimension=EMBEDDING_DIMENSIONS`, and `input_type="document"`. Later query embeddings use the same model and dimensions with `input_type="query"`.

- Run the preflight first, then find chunks with no embedding for the current model and dimensions. Embed only those. This is what makes the run resumable: stop it at any time, start it again, and it continues.
- Embed in small batches of 8 chunks. Wait about 20 seconds between requests. On a rate-limit error (HTTP 429), wait and retry with growing delays (honour `Retry-After` if given), up to a bounded number of attempts, then stop with a clear message. Other errors stop the run with a clear message. No stored embedding is lost.
- Write each batch to `embeddings` as soon as it returns, with `act`, `chapter`, `status`, and `access_level` copied from the chunk. Do not write vectors to `chunks`.
- Print progress after every batch, for example `embedded 64/990 (6%)`. Never print the key.
- If embeddings exist for a different model, version, or dimensions, do not mix them silently: stop, say which settings were found, and require an explicit `--replace-embeddings` flag, which deletes only the mismatched embeddings and reports the count. The fixed choices make this unlikely, but the check is required.
- **Expected duration.** There are roughly 1,000 chunks (the 2.1 corpus has about 676,000 characters; most sections are shorter than one chunk), so about 125 requests at roughly 20 seconds each: about 40 minutes on a free, rate-limited Voyage key. This matches the `.env.example` note. Plan for it, run it in a terminal that stays open, and tell the participant before starting. Record the real duration in the handover.

### 6. Vector index command

Provide `uv run python -m building_with_rag.ingestion.vector_index`. It runs the preflight against `embeddings`, then sets up the index:

- Index name `VECTOR_INDEX_NAME`, type `vectorSearch`, on the `embeddings` collection. The definition is a `fields` array:
  - one `vector` entry: `path` = `VECTOR_PATH` (`vector`), `numDimensions` = `EMBEDDING_DIMENSIONS`, `similarity` = `cosine`;
  - four `filter` entries, with paths exactly `act`, `chapter`, `status`, and `access_level`.
- Do not use the legacy `knnVector` / `mappings` syntax. That belongs to `search`-type indexes. Copy field names from the constants in `mongodb_schema.py`.
- Safe to repeat. If an index with that name exists and matches the definition (type, path, dimensions, similarity, filter set), reuse it and say so. If it exists but differs, print what differs and stop with a non-zero exit. Do not delete, drop, or update the existing index; the participant decides.
- Create the collection first if needed (`ensure_collections`), because an index needs an existing collection.
- Wait a bounded time for readiness: poll about every 10 seconds, for at most about 5 minutes, until the index is `queryable`. If it is not ready in time, report "index not ready yet" and exit non-zero without deleting anything. Re-running the command checks again.
- Sample query. When the index is queryable and embeddings exist: embed one fixed sample question (for example `punishment for murder`) with `input_type="query"` using the same model and dimensions (one Voyage request), then run one `$vectorSearch` on `embeddings` with `index=VECTOR_INDEX_NAME`, `path=VECTOR_PATH`, `numCandidates` around 100, `limit` 3, and a filter on `status` and `access_level`. Take the top result's `chunk_id`, look it up in `chunks`, then its parent in `sections`, and print `chunk_id`, `section_id`, `heading`, and the `vectorSearchScore`. A just-built index can return nothing for a moment; retry for a short, bounded time before reporting a failure.
- If services or credentials are missing (no embeddings yet, no Voyage key, or no connection), skip only the sample, and print `verification pending` with the reason. Do not fake a result.
- This command is a setup tool, not a retrieval endpoint. Do not add an API route, do not return a `RetrievedChunk`, and do not build the semantic pattern.

Suggested order: load, then index setup (it fails fast if Atlas Search is unavailable, before the 40-minute embed), then embed, then run the index command again for the sample query.

### 7. Dependencies

Add only `langchain-text-splitters` and `voyageai`, through UV (`uv add ...`), so `pyproject.toml` and `uv.lock` change. Do not add an ODM, a vector store, or other tooling.

### 8. Record in `docs/architecture.md`

Add a short "MongoDB and vector index" section (update existing text, don't duplicate):

- the four collections and what each holds, the deterministic ID formats, and that vectors live only in `embeddings`;
- the chunking choice (splitter, size, overlap, `CHUNKING_VERSION`);
- the embedding decision (Voyage `voyage-3.5`, version `voyage-3.5`, 1,024 dimensions, `input_type` document/query);
- the deployment capability found by the preflight;
- the index: name, `vectorSearch` type, vector path, cosine similarity, and the four filter fields;
- how later semantic retrieval works: `$vectorSearch` on `embeddings`, then resolve each `chunk_id` to `chunks` and `sections` before building a `RetrievedChunk`; section number and source fields are applied after that step;
- the commands from this story;
- limitations: about 40 minutes of embedding on a free Voyage key, one embedding per chunk, `access_level` is only a stored field, M0 search-index limits, and corpus records flagged `needs_review` in Story 2.1 are loaded with that flag, not repaired.

## Do not do

No retrieval or other API endpoints, answer generation, hybrid or keyword search, re-ranking, a separate vector store, Voyage re-ranking, new settings, broad validation frameworks, access-control logic, or deployment work. Do not print credentials. Do not delete or change an existing index.

## Completion checks

Keep checks small. Run and record each one. If something cannot run because MongoDB or Voyage is unavailable, mark it **pending** with the reason. Do not mark it passed.

1. `uv sync` succeeds, `uv run ruff check .` passes, and `uv run pytest` passes. Existing tests still pass, and no route or contract changed. Add a few small tests for chunking (a short section gives one chunk; a long one gives overlapping chunks that never cross sections), the deterministic IDs, and the index definition (a `vectorSearch` `fields` array, 1,024 dimensions, cosine, four filters). They need no database or network.
2. Preflight: with an empty `MONGODB_URI` the commands stop with a clear message that names the setting and does not print its value. With the real `.env`, the preflight prints the deployment capability.
3. Load command: the four collections exist; report counts for `sources` (2), `sections`, and `chunks`. Check one stored section-to-chunk link: pick one section (for example `bns:103`) and confirm its chunks exist with the same `section_id`, consecutive `chunk_index`, and the same `act`, `chapter`, and `status`.
4. Embed command: run to completion, with progress printed and the duration recorded. The `embeddings` count equals the `chunks` count. Check one embedding: `dimensions` is 1,024 and `len(vector)` is 1,024. No vectors exist on `chunks`.
5. Repeat setup: run the load, embed, and index commands a second time. The load reports everything unchanged, the embed run sends no Voyage request, and the index command reuses the compatible index. There are no duplicate documents and no new embeddings.
6. Index readiness: the index named `embeddings_vector_index` is `queryable`.
7. Sample query: record the top result's `chunk_id`, `section_id`, heading, and score, and say whether it is plausible (for example a murder-related section). Confirm `chunk_id` resolves to a chunk and its parent section.
8. `.env` is untracked (`git status` does not list it), and no key or connection string appears in command output, code, or docs.

## Handover

To be completed by the implementer:

- Deployment capability recorded by the preflight (Atlas or not, server version, search index management available).
- Counts per collection, and the chunking choice with `CHUNKING_VERSION`.
- Embedding run: batch size, delay, rate-limit retries seen, and actual duration.
- Index: name, definition, readiness, and whether it was created or reused.
- Sample query result: top `chunk_id`, `section_id`, heading, score, and your plausibility judgement. Mark pending if it could not run.
- Result of the repeat run (nothing new written).
- Confirmation that the `settings.py` key default was removed and the participant was told to rotate the key.
- Files created or changed, and dependencies added (`langchain-text-splitters`, `voyageai`).
- Skipped or open items, and known limitations.
- What the next story needs: the semantic pattern queries `embeddings` with `$vectorSearch` on `embeddings_vector_index`, embeds the query with `input_type="query"`, resolves each `chunk_id` to `chunks` and `sections`, and maps `act` and `status` filters from `SemanticFilters`.
