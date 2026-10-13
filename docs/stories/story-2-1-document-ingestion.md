# Story 2.1 — Document ingestion

Status: ready for implementation

This story follows Story 1.1. It reuses the same application, `docs/architecture.md`, and the existing `.env.example` contract. It adds no settings and renames none.

## Purpose

Turn the supplied BNS and IPC PDFs into a small, inspectable, section-level JSONL corpus in `data/processed/`. Nothing else. MongoDB, embeddings, vector indexes, retrieval, and answer generation belong to later stories.

## Prerequisites

- Story 1.1 is complete (project seed, `uv sync` works).
- Inputs under `data/raw/`: the supplied BNS PDF, the supplied IPC PDF, and `data/raw/PROVENANCE.md`. At the time this story was written, `data/raw/` does not exist in the repository and there is no `docs/config.yaml`. If either is still missing when you start, report exactly what is missing and stop. Do not invent PDFs or provenance. If `docs/config.yaml` exists, read it and use the paths it configures.
- Existing work is preserved. Do not modify or delete the original PDFs or `PROVENANCE.md`.

## Before you start

Read, in this order, whichever exist: `docs/config.yaml`, `docs/architecture.md`, `docs/stories/story-1-1-architecture-project-seed.md`, the existing code under `src/building_with_rag/`, and `data/raw/`. Update existing content instead of duplicating it.

## Work to do

### 1. Parser choice

Choose a suitable PDF parsing library and add it with UV (`uv add ...`), so `pyproject.toml` and `uv.lock` change. Prefer a text-based parser that exposes page numbers. Do not add OCR. Record the choice and its version.

### 2. Extraction command

Provide one command that extracts both acts, for example `uv run python -m building_with_rag.ingest`. Keep it small and put it in this project's package. It must not need MongoDB, Voyage, or any credential, and it must not read or add any `.env` setting.

### 3. Output

Write exactly two files, one record per line (JSONL, UTF-8):

- `data/processed/bns_sections.jsonl`
- `data/processed/ipc_sections.jsonl`

Keep BNS and IPC records separate, even where section numbers match.

Each record has exactly these fields, with exactly these values:

| Field | Value |
| --- | --- |
| `section_id` | `bns:<number>` or `ipc:<number>` |
| `act` | `BNS_2023` or `IPC_1860` |
| `act_label` | human label, for example `Bharatiya Nyaya Sanhita, 2023` or `Indian Penal Code, 1860` |
| `status` | `in_force` (BNS) or `repealed` (IPC) |
| `chapter` | string, for example `I` |
| `chapter_title` | chapter title as printed |
| `section_number` | integer |
| `heading` | section heading as printed |
| `text` | full section text, never empty |
| `source_pdf` | file name of the source PDF |
| `source_sha256` | SHA-256 of the source PDF |
| `parser` | parser library name |
| `parser_version` | parser library version |
| `source_status_version` | taken from `data/raw/PROVENANCE.md`; if it is not stated there, write `unknown`. Do not invent it |
| `needs_review` | `true` if extraction was uncertain, otherwise `false` |

Page references (for example `page_start`, `page_end`) may be kept as additional fields, but they do not replace any field above. Do not invent unknown provenance.

### 4. Extraction rules

- Extract sections without rewriting their meaning. Keep the text as printed apart from the cleanup below.
- Remove repeated page headers and footers, normalize spacing, and join sections that span pages.
- Treat obvious duplicate extraction (the same section captured twice) conservatively: keep one record and set `needs_review` to `true` if you are not sure.
- Flag uncertain content (unparseable section number, missing heading, very short text, scanned or image-only pages) with `needs_review: true`. Do not silently repair it, and do not guess.

### 5. Safe re-runs

- Re-running must not append duplicate records. Write each file as one complete replacement (write to a temporary file, then replace).
- If a source hash differs from the one in the existing output, regenerate that whole file. Never mix records from two source versions in one file.
- Do not overwrite a supplied valid corpus unnecessarily. If an output file already exists with matching `source_sha256` values and the same parser and parser version, leave it unchanged.

### 6. Record in `docs/architecture.md`

Add a short "Ingestion" section stating: the parser choice and version, the output format and fields, the command, and known limitations (for example scanned pages are flagged, not OCR'd). Update the existing text instead of duplicating it.

### 7. How later chunking preserves source information

State this in the handover, in plain words. Later chunking must keep each section as the parent. Every chunk carries its parent `section_id`, `act`, `chapter`, `heading`, `status`, `source_pdf`, `source_sha256`, and any page references, so a retrieved passage can always be traced back to one act and one section. The `ChunkDocument` contract in `contracts.py` uses `act` values `BNS` and `IPC`. The later importer maps `BNS_2023` to `BNS` and `IPC_1860` to `IPC`. This story does not change the contract.

## Do not do

No MongoDB, embeddings, vector indexes, retrieval, answer generation, OCR, a corpus-validation framework, a reference-difference report, broad security tests, or synthetic permission records.

## Completion checks

Keep checks small and directly relevant. Run and record each one:

1. `uv sync` succeeds; `uv run ruff check .` passes; `uv run pytest` passes.
2. The extraction command runs and writes both JSONL files.
3. Every record has all required fields with the required values and types (`section_number` is an integer, `chapter` is a string, `section_id` matches its act and number). No record has empty `text`.
4. Inspect a few representative records from each act against its PDF, including a section that spans pages if one exists.
5. Report how many records are flagged `needs_review`, and why.
6. Run the extraction a second time. The line counts and file contents are unchanged, with no duplicates.

## Handover

To be completed by the implementer:

- Inputs used (PDF names, `PROVENANCE.md`) and any that were missing.
- Output files and record counts per act.
- Parser name and version, and the command.
- Records inspected against the PDFs, and the result.
- `needs_review` count and reasons.
- Result of the second run.
- Files created or changed.
- Skipped or open items, and known limitations.
