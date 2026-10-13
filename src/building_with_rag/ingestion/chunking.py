"""Story 2.2: split one section's text into chunks. Sections and acts are never mixed."""

from langchain_text_splitters import RecursiveCharacterTextSplitter

from building_with_rag.ingestion.mongodb_schema import CHUNK_OVERLAP, CHUNK_SIZE

_splitter = RecursiveCharacterTextSplitter(
    chunk_size=CHUNK_SIZE,
    chunk_overlap=CHUNK_OVERLAP,
    separators=["\n\n", "\n", ". ", " ", ""],
)


def split_section_text(text: str) -> list[str]:
    text = text.strip()
    if not text:
        return []
    if len(text) <= CHUNK_SIZE:
        return [text]
    return _splitter.split_text(text)


def embedding_input(act_label: str, section_number: int | str, heading: str, chunk_text: str) -> str:
    return f"{act_label} — Section {section_number}: {heading}\n\n{chunk_text}"
