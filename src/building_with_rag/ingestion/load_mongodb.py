"""Story 2.2: load sources, sections and chunks into MongoDB (no Voyage call).

Run with: uv run python -m building_with_rag.ingestion.load_mongodb [--test-db]
"""

import json
from datetime import UTC, datetime
from pathlib import Path

from pymongo import DeleteMany, ReplaceOne

from building_with_rag.ingestion import mongodb_schema as S
from building_with_rag.ingestion.chunking import embedding_input, split_section_text
from building_with_rag.ingestion.common import PrerequisiteError, base_parser, preflight, run

PROCESSED = Path(__file__).resolve().parents[3] / "data" / "processed"
FILES = {"BNS_2023": "bns_sections.jsonl", "IPC_1860": "ipc_sections.jsonl"}


def read_records() -> dict[str, list[dict]]:
    out = {}
    for act_version, name in FILES.items():
        path = PROCESSED / name
        if not path.exists():
            raise PrerequisiteError(f"missing corpus file {path}. Run Story 2.1 ingestion first.")
        text = path.read_text(encoding="utf-8")
        out[act_version] = [json.loads(x) for x in text.splitlines() if x.strip()]
    return out


def build_docs(act_version: str, rows: list[dict]) -> tuple[dict, list[dict], list[dict]]:
    first = rows[0]
    act = S.ACT_CODES[act_version]
    sid = S.source_id(act_version)
    source = {
        "_id": sid, "source_id": sid, "source_pdf": first["source_pdf"],
        "source_sha256": first["source_sha256"], "act": act, "act_version": act_version,
        "act_label": first["act_label"], "status": first["status"], "parser": first["parser"],
        "parser_version": first["parser_version"],
        "source_status_version": first["source_status_version"],
    }
    sections, chunks = [], []
    for r in rows:
        sec_id = r["section_id"]
        sections.append({
            "_id": sec_id, "section_id": sec_id, "source_id": sid, "act": act,
            "act_version": act_version, "act_label": r["act_label"], "status": r["status"],
            "chapter": r["chapter"], "chapter_title": r["chapter_title"],
            "section_number": r["section_number"], "heading": r["heading"], "text": r["text"],
            "text_sha256": S.sha256_text(r["text"]), "source_pdf": r["source_pdf"],
            "source_sha256": r["source_sha256"], "page_start": r.get("page_start"),
            "page_end": r.get("page_end"), "needs_review": r["needs_review"],
            "access_level": S.ACCESS_LEVEL_PUBLIC,
        })
        for i, text in enumerate(split_section_text(r["text"])):
            cid = S.chunk_id(sec_id, i)
            inp = embedding_input(r["act_label"], r["section_number"], r["heading"], text)
            chunks.append({
                "_id": cid, "chunk_id": cid, "section_id": sec_id, "source_id": sid,
                "chunk_index": i, "chunking_version": S.CHUNKING_VERSION, "splitter": S.SPLITTER,
                "text": text, "embedding_input": inp, "input_sha256": S.sha256_text(inp),
                "act": act, "chapter": r["chapter"], "status": r["status"],
                "access_level": S.ACCESS_LEVEL_PUBLIC,
            })
    return source, sections, chunks


def sync(coll, new_docs: list[dict], acts: list[str], ignore: tuple[str, ...] = ()) -> dict:
    """Upsert `new_docs`; remove stale docs of `acts`. Returns counts and the changed/removed ids."""

    def core(d: dict) -> dict:
        return {k: v for k, v in d.items() if k not in ignore}

    old = {d["_id"]: d for d in coll.find({"act": {"$in": acts}})}
    new_ids = {d["_id"] for d in new_docs}
    todo, inserted, changed_ids = [], 0, []
    for d in new_docs:
        o = old.get(d["_id"])
        if o is None:
            inserted += 1
            todo.append(ReplaceOne({"_id": d["_id"]}, d, upsert=True))
        elif core(o) != core(d):
            changed_ids.append(d["_id"])
            todo.append(ReplaceOne({"_id": d["_id"]}, d, upsert=True))
    removed = [i for i in old if i not in new_ids]
    if removed:
        todo.append(DeleteMany({"_id": {"$in": removed}}))
    if todo:
        coll.bulk_write(todo, ordered=True)
    return {
        "inserted": inserted,
        "unchanged": len(new_docs) - inserted - len(changed_ids),
        "changed": len(changed_ids),
        "removed": len(removed),
        "changed_ids": changed_ids,
        "removed_ids": removed,
    }


def line(name: str, c: dict, extra: str = "") -> None:
    print(
        f"{name}: inserted {c['inserted']}, unchanged {c['unchanged']}, "
        f"changed {c['changed']}, removed {c['removed']}{extra}"
    )


def main() -> int:
    args = base_parser(__doc__).parse_args()
    data = read_records()
    db = preflight(args.test_db, probe_collection=S.EMBEDDINGS)
    S.ensure_collections(db)

    sources, sections, chunks = [], [], []
    for act_version, rows in data.items():
        a, b, c = build_docs(act_version, rows)
        sources.append(a)
        sections += b
        chunks += c
    acts = [S.ACT_CODES[a] for a in data]

    # imported_at only moves when the source record itself changes
    old_src = {d["_id"]: d for d in db[S.SOURCES].find()}
    now = datetime.now(UTC)
    for s in sources:
        o = old_src.get(s["_id"])
        same = o is not None and all(o.get(k) == v for k, v in s.items())
        s["imported_at"] = o["imported_at"] if same else now
        if o is not None and o["source_sha256"] != s["source_sha256"]:
            print(f"WARNING: source file for {s['act_version']} changed; replacing the whole act")
    line("sources", sync(db[S.SOURCES], sources, acts, ignore=("imported_at",)))
    line("sections", sync(db[S.SECTIONS], sections, acts))
    c = sync(db[S.CHUNKS], chunks, acts)
    stale = c["changed_ids"] + c["removed_ids"]
    dropped = 0
    if stale:
        dropped = db[S.EMBEDDINGS].delete_many({"chunk_id": {"$in": stale}}).deleted_count
    line("chunks", c, f" (stale embeddings deleted: {dropped})")
    print(f"chunking: {S.CHUNKING_VERSION}")
    return 0


if __name__ == "__main__":
    run(main)
