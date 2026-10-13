"""Story 2.2: MongoDB collections, validators, deterministic IDs and the vector index definition.

Everything else in `building_with_rag.ingestion` imports from here; nothing is redefined elsewhere.
"""

import hashlib

from pymongo import ASCENDING
from pymongo.database import Database

SOURCES = "sources"
SECTIONS = "sections"
CHUNKS = "chunks"
EMBEDDINGS = "embeddings"

EMBEDDING_MODEL = "voyage-3.5"
EMBEDDING_MODEL_VERSION = "voyage-3.5"
EMBEDDING_DIMENSIONS = 1024
ACCESS_LEVEL_PUBLIC = "public"

SPLITTER = "RecursiveCharacterTextSplitter"
CHUNK_SIZE = 2048  # characters, about 512 tokens
CHUNK_OVERLAP = 256
CHUNKING_VERSION = f"recursive-char-{CHUNK_SIZE}-{CHUNK_OVERLAP}-v1"

VECTOR_INDEX_NAME = "embeddings_vector_index"
VECTOR_PATH = "vector"
FILTER_FIELDS = ("act", "chapter", "status", "access_level")

# Story 2.1 writes BNS_2023 / IPC_1860; MongoDB stores BNS / IPC (matches ChunkDocument).
ACT_CODES = {"BNS_2023": "BNS", "IPC_1860": "IPC"}


# ------------------------------------------------------------------ deterministic IDs


def source_id(act_version: str) -> str:
    return f"source:{act_version}"


def chunk_id(section_id: str, chunk_index: int) -> str:
    return f"{section_id}:{chunk_index}"


def embedding_id(chunk: str, model: str = EMBEDDING_MODEL, dimensions: int = EMBEDDING_DIMENSIONS) -> str:
    return f"{chunk}:{model}:{dimensions}"


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ------------------------------------------------------------------ validators

_STR = {"bsonType": "string"}
_INT = {"bsonType": ["int", "long"]}


def _schema(required: list[str], extra: dict | None = None) -> dict:
    props = {name: _STR for name in required}
    props.update(extra or {})
    return {"$jsonSchema": {"bsonType": "object", "required": required, "properties": props}}


VALIDATORS: dict[str, dict] = {
    SOURCES: _schema(
        ["_id", "source_id", "source_pdf", "source_sha256", "act", "act_version", "act_label",
         "status", "parser", "parser_version", "source_status_version"]
    ),
    SECTIONS: _schema(
        ["_id", "section_id", "source_id", "act", "act_version", "act_label", "status", "chapter",
         "heading", "text", "text_sha256", "source_pdf", "source_sha256", "access_level"],
        {"section_number": _INT, "needs_review": {"bsonType": "bool"}},
    ),
    CHUNKS: _schema(
        ["_id", "chunk_id", "section_id", "source_id", "chunking_version", "splitter", "text",
         "embedding_input", "input_sha256", "act", "chapter", "status", "access_level"],
        {"chunk_index": _INT},
    ),
    EMBEDDINGS: _schema(
        ["_id", "embedding_id", "chunk_id", "model", "model_version", "input_sha256", "act",
         "chapter", "status", "access_level"],
        {
            "dimensions": _INT,
            "vector": {
                "bsonType": "array",
                "minItems": EMBEDDING_DIMENSIONS,
                "maxItems": EMBEDDING_DIMENSIONS,
                "items": {"bsonType": ["double", "int", "long"]},
            },
        },
    ),
}
VALIDATORS[EMBEDDINGS]["$jsonSchema"]["required"] += ["dimensions", "vector"]
VALIDATORS[CHUNKS]["$jsonSchema"]["required"].append("chunk_index")
VALIDATORS[SECTIONS]["$jsonSchema"]["required"] += ["section_number"]

# (keys, unique)
ORDINARY_INDEXES: dict[str, list[tuple[list[tuple[str, int]], bool]]] = {
    SECTIONS: [
        ([("source_id", ASCENDING)], False),
        ([("act", ASCENDING), ("section_number", ASCENDING)], False),
    ],
    CHUNKS: [
        ([("section_id", ASCENDING), ("chunk_index", ASCENDING)], True),
        ([("act", ASCENDING), ("chapter", ASCENDING)], False),
    ],
    EMBEDDINGS: [
        ([("chunk_id", ASCENDING), ("model", ASCENDING), ("dimensions", ASCENDING)], True),
        ([("chunk_id", ASCENDING)], False),
    ],
}


def ensure_collections(db: Database) -> None:
    """Create the four collections with validators and ordinary indexes. Safe to repeat."""
    existing = set(db.list_collection_names())
    for name, validator in VALIDATORS.items():
        if name in existing:
            db.command("collMod", name, validator=validator, validationLevel="strict",
                       validationAction="error")
        else:
            db.create_collection(name, validator=validator, validationLevel="strict",
                                 validationAction="error")
        for keys, unique in ORDINARY_INDEXES.get(name, []):
            db[name].create_index(keys, unique=unique)


# ------------------------------------------------------------------ vector index


def vector_index_definition() -> dict:
    """Atlas `vectorSearch`-type definition: one vector field plus four filter fields."""
    return {
        "fields": [
            {
                "type": "vector",
                "path": VECTOR_PATH,
                "numDimensions": EMBEDDING_DIMENSIONS,
                "similarity": "cosine",
            },
            *({"type": "filter", "path": f} for f in FILTER_FIELDS),
        ]
    }
