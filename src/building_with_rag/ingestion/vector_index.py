"""Story 2.2: create or reuse the Atlas vectorSearch index on embeddings.vector, then sample it.

Run with: uv run python -m building_with_rag.ingestion.vector_index
(always the main database; M0 allows only a few search indexes)

Uses PyMongo create_search_index(SearchIndexModel(type="vectorSearch")) and $vectorSearch.
Never deletes or updates an existing index.
"""

import time

from pymongo.operations import SearchIndexModel

from building_with_rag.ingestion import mongodb_schema as S
from building_with_rag.ingestion.common import PrerequisiteError, preflight, run
from building_with_rag.ingestion.embed_chunks import embed_texts, voyage_client

POLL_SECONDS = 10
READY_TIMEOUT_SECONDS = 300
SAMPLE_QUESTION = "punishment for murder"


def describe(definition: dict) -> dict:
    fields = definition.get("fields", [])
    vec = [f for f in fields if f.get("type") == "vector"]
    return {
        "vector": [
            (f.get("path"), f.get("numDimensions"), f.get("similarity")) for f in vec
        ],
        "filters": sorted(f["path"] for f in fields if f.get("type") == "filter"),
    }


def differences(existing: dict) -> list[str]:
    if existing.get("type") != "vectorSearch":
        return [f"type is {existing.get('type')!r}, expected 'vectorSearch'"]
    have = describe(existing.get("latestDefinition") or existing.get("definition") or {})
    want = describe(S.vector_index_definition())
    return [f"{k}: found {have[k]}, expected {want[k]}" for k in want if have[k] != want[k]]


def get_index(coll) -> dict | None:
    return next(iter(coll.list_search_indexes(S.VECTOR_INDEX_NAME)), None)


def ensure_index(coll) -> dict:
    idx = get_index(coll)
    if idx is None:
        coll.create_search_index(
            SearchIndexModel(
                definition=S.vector_index_definition(),
                name=S.VECTOR_INDEX_NAME,
                type="vectorSearch",
            )
        )
        print(f"index '{S.VECTOR_INDEX_NAME}': created (vectorSearch)")
        return {"created": True}
    diff = differences(idx)
    if diff:
        raise PrerequisiteError(
            f"index '{S.VECTOR_INDEX_NAME}' exists with a different configuration: "
            + "; ".join(diff)
            + ". Not changed. Drop it yourself in Atlas if you want it recreated."
        )
    print(f"index '{S.VECTOR_INDEX_NAME}': exists and is compatible, reused")
    return {"created": False}


def wait_ready(coll) -> bool:
    deadline = time.time() + READY_TIMEOUT_SECONDS
    while True:
        idx = get_index(coll)
        if idx and idx.get("queryable"):
            print(f"index '{S.VECTOR_INDEX_NAME}': queryable (status {idx.get('status')})")
            return True
        if time.time() >= deadline:
            status = idx.get("status") if idx else "missing"
            print(f"index not ready yet (status {status}); re-run this command to check again")
            return False
        time.sleep(POLL_SECONDS)


def sample_query(db) -> None:
    n = db[S.EMBEDDINGS].count_documents({})
    if n == 0:
        print("verification pending: no embeddings yet (run embed_chunks, then this command again)")
        return
    try:
        client = voyage_client()
        qvec = embed_texts(client, [SAMPLE_QUESTION], "query")[0]
    except PrerequisiteError as exc:
        print(f"verification pending: {exc}")
        return
    pipeline = [
        {
            "$vectorSearch": {
                "index": S.VECTOR_INDEX_NAME,
                "path": S.VECTOR_PATH,
                "queryVector": qvec,
                "numCandidates": 100,
                "limit": 3,
                "filter": {"status": "in_force", "access_level": S.ACCESS_LEVEL_PUBLIC},
            }
        },
        {"$project": {"chunk_id": 1, "score": {"$meta": "vectorSearchScore"}}},
    ]
    hits: list[dict] = []
    for _ in range(6):  # a just-built index can be briefly empty
        hits = list(db[S.EMBEDDINGS].aggregate(pipeline))
        if hits:
            break
        time.sleep(POLL_SECONDS)
    if not hits:
        print("verification pending: $vectorSearch returned no results yet; re-run shortly")
        return
    top = hits[0]
    chunk = db[S.CHUNKS].find_one({"_id": top["chunk_id"]})
    section = db[S.SECTIONS].find_one({"_id": chunk["section_id"]}) if chunk else None
    if not chunk or not section:
        print(f"sample FAILED: chunk_id {top['chunk_id']} did not resolve to a chunk and section")
        return
    print(f"sample query: {SAMPLE_QUESTION!r} (filter status=in_force, access_level=public)")
    print(f"  chunk_id:   {chunk['chunk_id']}")
    print(f"  section_id: {section['section_id']}")
    print(f"  heading:    {section['heading']}")
    print(f"  score:      {top['score']:.4f}")


def main() -> int:
    db = preflight(test_db=False, probe_collection=S.EMBEDDINGS)
    S.ensure_collections(db)
    coll = db[S.EMBEDDINGS]
    ensure_index(coll)
    if not wait_ready(coll):
        return 1
    sample_query(db)
    return 0


if __name__ == "__main__":
    run(main)
