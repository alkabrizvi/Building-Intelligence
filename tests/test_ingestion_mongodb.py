from building_with_rag.ingestion import mongodb_schema as S
from building_with_rag.ingestion.chunking import split_section_text
from building_with_rag.ingestion.load_mongodb import build_docs, read_records


def test_short_section_is_one_chunk():
    assert split_section_text("A short section.") == ["A short section."]


def test_long_section_overlaps_and_respects_size():
    text = " ".join(f"word{i}" for i in range(2000))
    chunks = split_section_text(text)
    assert len(chunks) > 1
    assert all(len(c) <= S.CHUNK_SIZE for c in chunks)
    assert chunks[0][-50:] in chunks[1]  # overlap carries text forward


def test_chunks_never_cross_sections_or_acts():
    data = read_records()
    for act_version, rows in data.items():
        _, sections, chunks = build_docs(act_version, rows[:40])
        by_section = {s["section_id"]: s for s in sections}
        for c in chunks:
            sec = by_section[c["section_id"]]
            assert c["act"] == sec["act"] == S.ACT_CODES[act_version]
            assert c["chunk_id"] == S.chunk_id(c["section_id"], c["chunk_index"])
            assert c["text"] in sec["text"]
            assert "vector" not in c


def test_deterministic_ids():
    assert S.source_id("BNS_2023") == "source:BNS_2023"
    assert S.chunk_id("bns:103", 0) == "bns:103:0"
    assert S.embedding_id("bns:103:0") == "bns:103:0:voyage-3.5:1024"


def test_vector_index_definition():
    fields = S.vector_index_definition()["fields"]
    assert fields[0] == {
        "type": "vector", "path": "vector", "numDimensions": 1024, "similarity": "cosine",
    }
    assert [f["path"] for f in fields[1:]] == ["act", "chapter", "status", "access_level"]
    assert all(f["type"] == "filter" for f in fields[1:])
