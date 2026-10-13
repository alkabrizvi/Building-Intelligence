"""Story 2.2: embed chunks with Voyage into the `embeddings` collection. Resumable.

Run with: uv run python -m building_with_rag.ingestion.embed_chunks [--test-db] [--replace-embeddings]

About 40 minutes on a free, rate-limited Voyage key (batches of 8, ~20 s apart).
"""

import time
from datetime import UTC, datetime

import voyageai
from voyageai import error as verr

from building_with_rag.ingestion import mongodb_schema as S
from building_with_rag.ingestion.common import PrerequisiteError, base_parser, preflight, run
from building_with_rag.settings import get_settings

BATCH_SIZE = 8
DELAY_SECONDS = 20
MAX_ATTEMPTS = 6
RETRY_BASE_SECONDS = 30


def voyage_client() -> voyageai.Client:
    key = get_settings().voyage_api_key
    if not key:
        raise PrerequisiteError("VOYAGE_API_KEY is empty. Set it in your untracked .env.")
    return voyageai.Client(api_key=key, max_retries=0)


def embed_texts(client: voyageai.Client, texts: list[str], input_type: str) -> list[list[float]]:
    """One Voyage request, retried with growing delays on rate-limit errors."""
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            result = client.embed(
                texts,
                model=S.EMBEDDING_MODEL,
                input_type=input_type,
                output_dimension=S.EMBEDDING_DIMENSIONS,
            )
            return result.embeddings
        except verr.RateLimitError:
            if attempt == MAX_ATTEMPTS:
                raise PrerequisiteError(
                    "Voyage kept rate-limiting the request. Wait a few minutes and re-run; "
                    "finished embeddings are kept and skipped."
                ) from None
            wait = RETRY_BASE_SECONDS * 2 ** (attempt - 1)
            print(f"  rate limited; waiting {wait}s (attempt {attempt}/{MAX_ATTEMPTS})")
            time.sleep(wait)
        except verr.AuthenticationError:
            raise PrerequisiteError("Voyage rejected VOYAGE_API_KEY. Check your .env.") from None
        except verr.VoyageError as exc:
            raise PrerequisiteError(f"Voyage request failed ({type(exc).__name__}). Re-run to resume.") from None
    raise AssertionError("unreachable")


def main() -> int:
    parser = base_parser(__doc__)
    parser.add_argument("--replace-embeddings", action="store_true",
                        help="delete embeddings made with a different model/version/dimensions")
    args = parser.parse_args()
    db = preflight(args.test_db, probe_collection=S.EMBEDDINGS)
    S.ensure_collections(db)
    emb = db[S.EMBEDDINGS]

    mismatch = {
        "$or": [
            {"model": {"$ne": S.EMBEDDING_MODEL}},
            {"model_version": {"$ne": S.EMBEDDING_MODEL_VERSION}},
            {"dimensions": {"$ne": S.EMBEDDING_DIMENSIONS}},
        ]
    }
    n_bad = emb.count_documents(mismatch)
    if n_bad:
        found = sorted({(d["model"], d["model_version"], d["dimensions"]) for d in emb.find(mismatch)})
        if not args.replace_embeddings:
            raise PrerequisiteError(
                f"{n_bad} embeddings use other settings {found}; current is "
                f"({S.EMBEDDING_MODEL}, {S.EMBEDDING_MODEL_VERSION}, {S.EMBEDDING_DIMENSIONS}). "
                "Re-run with --replace-embeddings to delete only those."
            )
        print(f"deleted {emb.delete_many(mismatch).deleted_count} embeddings with other settings")

    done = {d["chunk_id"] for d in emb.find({}, {"chunk_id": 1})}
    total = db[S.CHUNKS].count_documents({})
    if total == 0:
        raise PrerequisiteError("no chunks found. Run building_with_rag.ingestion.load_mongodb first.")
    todo = [
        c for c in db[S.CHUNKS].find().sort("_id", 1) if c["chunk_id"] not in done
    ]
    print(f"chunks: {total}, already embedded: {total - len(todo)}, to embed: {len(todo)}")
    if not todo:
        print("nothing to embed (no Voyage request sent)")
        return 0

    client = voyage_client()
    started = time.time()
    for i in range(0, len(todo), BATCH_SIZE):
        if i:
            time.sleep(DELAY_SECONDS)
        batch = todo[i : i + BATCH_SIZE]
        vectors = embed_texts(client, [c["embedding_input"] for c in batch], "document")
        now = datetime.now(UTC)
        docs = []
        for c, vec in zip(batch, vectors, strict=True):
            eid = S.embedding_id(c["chunk_id"])
            docs.append({
                "_id": eid, "embedding_id": eid, "chunk_id": c["chunk_id"],
                "model": S.EMBEDDING_MODEL, "model_version": S.EMBEDDING_MODEL_VERSION,
                "dimensions": S.EMBEDDING_DIMENSIONS, "vector": vec,
                "input_sha256": c["input_sha256"], "created_at": now, "act": c["act"],
                "chapter": c["chapter"], "status": c["status"], "access_level": c["access_level"],
            })
        emb.insert_many(docs, ordered=False)
        n = min(i + BATCH_SIZE, len(todo))
        print(f"embedded {n}/{len(todo)} ({100 * n // len(todo)}%), {int(time.time() - started)}s elapsed")
    print(f"done in {int(time.time() - started)}s")
    return 0


if __name__ == "__main__":
    run(main)
