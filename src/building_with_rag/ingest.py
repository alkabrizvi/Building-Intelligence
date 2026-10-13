"""Story 2.1: turn the supplied BNS and IPC PDFs into section-level JSONL.

Run with: uv run python -m building_with_rag.ingest

Needs no database, no credentials and no .env setting. Text-based extraction only (no OCR).
"""

import hashlib
import json
import os
import re
import sys
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from importlib.metadata import version
from pathlib import Path

from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = ROOT / "data" / "raw"
OUT_DIR = ROOT / "data" / "processed"
PARSER = "pypdf"
MIN_TEXT_CHARS = 25  # shorter section text is flagged for review
EMPTY_PAGE_CHARS = 20  # fewer extracted characters than this: likely scanned/image-only

ACTS = {
    "bns": {
        "pdf": "BNS_2023_bare_act.pdf",
        "act": "BNS_2023",
        "act_label": "Bharatiya Nyaya Sanhita, 2023",
        "status": "in_force",
    },
    "ipc": {
        "pdf": "IPC_1860_bare_act.pdf",
        "act": "IPC_1860",
        "act_label": "Indian Penal Code, 1860",
        "status": "repealed",
    },
}

DASH = re.compile(r"-\s?-|(?<=\.)-(?=\s?[A-Za-z\[])")  # heading end: "--", "- -" or ".-"
NOISE = re.compile(r"HomePage|Note: For Reference only|^-{20,}$|^\d{1,4}$")
SEC_NO = r"(\d+)([A-Z]{0,2})"
PARA_START = re.compile(r"^(\([a-zA-Z0-9]{1,5}\)\s|Illustrations?\b|Explanations?\b|Exceptions?\b|Provided\b)")


@dataclass
class Raw:
    """A section as found in the PDF, before it becomes a record."""

    number: int
    suffix: str
    chapter: str = ""
    chapter_title: str = ""
    heading: str = ""
    lines: list[str] = field(default_factory=list)
    page_start: int = 0
    page_end: int = 0
    review: list[str] = field(default_factory=list)


def norm(s: str) -> str:
    return re.sub(r"[\s.,;:\-–—'\"“”‘’()]+", "", s).lower()


def read_pages(path: Path) -> list[list[str]]:
    """Return per-page lists of cleaned, non-empty lines (spacing normalized)."""
    pages = []
    for page in PdfReader(path).pages:
        raw = page.extract_text() or ""
        lines = [re.sub(r"\s+", " ", ln).strip() for ln in raw.split("\n")]
        pages.append([ln for ln in lines if ln])
    return pages


def clean_pages(pages: list[list[str]]) -> list[list[str]]:
    return [[ln for ln in page if not NOISE.search(ln)] for page in pages]


def join_paragraphs(lines: list[str]) -> str:
    out: list[str] = []
    for ln in lines:
        if out and not PARA_START.match(ln):
            out[-1] += " " + ln
        else:
            out.append(ln)
    return "\n".join(out).strip()


# ---------------------------------------------------------------- BNS


def parse_bns_index(path: Path, stop_page: int) -> tuple[dict, dict, set]:
    reader = PdfReader(path)
    lines: list[str] = []
    for page in reader.pages[1:stop_page]:
        lines += [re.sub(r"\s+", " ", ln).strip() for ln in (page.extract_text() or "").split("\n")]
    chapters: dict[str, str] = {}
    sections: dict[int, tuple[str, str]] = {}  # number -> (chapter, heading)
    subheads: set[str] = set()
    chapter = ""
    i = 0
    prev_blank = True
    cur: int | None = None
    buf: list[str] = []

    def flush() -> None:
        nonlocal cur, buf
        if cur is not None:
            sections[cur] = (chapter, " ".join(buf).strip())
        cur, buf = None, []

    while i < len(lines):
        ln = lines[i]
        i += 1
        if not ln:
            prev_blank = True
            if cur is not None:
                flush()
            continue
        if ln.startswith(("Index", "BHARATIYA", "ARRANGEMENT")) or "HomePage" in ln:
            continue
        if ln == "SECTION":
            continue
        m = re.match(r"^CHAPTER ([IVXL]+)$", ln)
        if m:
            flush()
            chapter = m.group(1)
            title = []
            while i < len(lines) and lines[i]:
                title.append(lines[i])
                i += 1
            chapters[chapter] = " ".join(title)
            continue
        m = re.match(r"^(\d+)\.\s+(.*)$", ln)
        if m:
            flush()
            cur, buf = int(m.group(1)), [m.group(2)]
        elif cur is not None and not prev_blank:
            buf.append(ln)
        elif ln and prev_blank:
            subheads.add(norm(ln))
        prev_blank = False
    flush()
    return chapters, sections, subheads


def parse_bns(pages: list[list[str]], path: Path) -> list[Raw]:
    stop = next(i for i, p in enumerate(pages) if any("CORRESPONDING SECTION TABLE" in x for x in p))
    chapters, index, subheads = parse_bns_index(path, stop)
    start = next(i for i, p in enumerate(pages) if any(x.startswith("1. (1) This Act may") for x in p))
    flat = [(pn + 1, ln) for pn, page in enumerate(pages[start:], start) for ln in page]

    # A section starts at "N. ..." where N is the next expected number.
    starts: list[int] = []
    expected = 1
    for idx, (_, ln) in enumerate(flat):
        m = re.match(r"^(\d+)\.(?:\s|(?=\())", ln)
        if m and int(m.group(1)) == expected:
            starts.append(idx)
            expected += 1

    secs: list[Raw] = []
    for k, s in enumerate(starts):
        e = starts[k + 1] if k + 1 < len(starts) else len(flat)
        number = k + 1
        chapter, heading = index.get(number, ("", ""))
        raw = Raw(number, "", chapter, chapters.get(chapter, ""), heading)
        body = [ln for _, ln in flat[s:e]]
        body[0] = re.sub(r"^\d+\.\s*", "", body[0])
        raw.lines = body
        raw.page_start = flat[s][0]
        raw.page_end = flat[e - 1][0]
        if not heading:
            raw.review.append("heading not found in index")
        secs.append(raw)

    # The next section's heading (and any chapter/sub-heading) sits at the tail of the previous one.
    for k in range(len(secs) - 1):
        trim_tail(secs[k], secs[k + 1].heading, chapters, subheads)
    return secs


def tail_matches(lines: list[str], target: str) -> int | None:
    """Return how many trailing lines make up `target` (normalized), else None.

    Exact match first; otherwise the closest near-match (the body sometimes words a heading
    slightly differently from the printed index).
    """
    best: tuple[float, int] = (0.0, 0)
    acc = ""
    for n in range(1, min(len(lines), 8) + 1):
        acc = norm(lines[-n]) + acc
        if acc == target:
            return n
        if len(acc) > len(target) * 1.25 + 4:
            break
        ratio = SequenceMatcher(None, acc, target).ratio()
        if ratio > best[0]:
            best = (ratio, n)
    return best[1] if best[0] >= 0.9 else None


def trim_tail(sec: Raw, next_heading: str, chapters: dict, subheads: set) -> None:
    lines = sec.lines
    n = tail_matches(lines, norm(next_heading)) if next_heading else None
    if n is None:
        sec.review.append("next heading not located at section end; tail may include heading")
        return
    del lines[-n:]
    # optional sub-heading, then optional chapter header, before that heading
    while lines:
        for sub in subheads:
            n = tail_matches(lines, sub)
            if n:
                del lines[-n:]
                break
        else:
            hit = False
            for rom, title in chapters.items():
                n = tail_matches(lines, norm("CHAPTER " + rom + " " + title))
                if n:
                    del lines[-n:]
                    hit = True
                    break
            if not hit:
                break


# ---------------------------------------------------------------- IPC

LONE_NO = re.compile(r"^(?:\d+\*+\[)*(\d+)([A-Z]{0,2})\.$")
START = re.compile(rf"^(?:\d+\*+\[)*{SEC_NO}\.\s+(.*)$")
CHAPTER = re.compile(r"^(?:\d+\*+\[)*CHAPTER ([IVXL]+[A-Z]?)\s*$")
FOOTNOTE = re.compile(
    r"^(\d{1,3})\. (?:Subs|Ins|Added|Omitted|Rep|The|Clause|Sub|Sections?|Para|Paragraph|"
    r"Explanation|Illustration|See|Vide|Cl|These|Now|Proviso|Words|Figures|Item|Entry|In|For|It|This|"
    r"Brackets|Bracket|Inserted|Substituted|Repealed|Original|Old)"
)


def strip_footnotes(page: list[str], last_fn: int) -> tuple[list[str], int]:
    """Drop footnotes. A footnote run at the top of a page continues the previous page's
    footnotes and ends at a line ending in a full stop; a run further down is the page's own
    footnote block and lasts to the end of the page."""
    out: list[str] = []
    mode = ""  # "" | "top" (until sentence end) | "bottom" (until end of page)
    for idx, ln in enumerate(page):
        m = FOOTNOTE.match(ln)
        if m and not DASH.search(ln) and mode != "bottom":
            n = int(m.group(1))
            if n == last_fn + 1 or (n == 1 and not mode):
                last_fn = n
                mode = "top" if idx == 0 or (mode == "top" and not out) else "bottom"
                if mode == "top" and re.search(r"[.\"”\]]$", ln):
                    mode = "top-done"
                continue
        if mode == "bottom" and (LONE_NO.match(ln) or CHAPTER.match(ln)):
            mode = ""  # body resumes (a new section or chapter heading)
        if mode == "bottom":
            continue
        if mode == "top":
            if re.search(r"[.\"”\]]$", ln):
                mode = "top-done"
            continue
        if mode == "top-done" and not out and FOOTNOTE.match(ln):
            continue
        out.append(ln)
    return out, last_fn


def parse_ipc(pages: list[list[str]]) -> list[Raw]:
    flat: list[tuple[int, str]] = []
    last_fn = 0
    for pn, page in enumerate(pages, 1):
        body, last_fn = strip_footnotes(page, last_fn)
        # a page with no footnote on it ends a footnote run; numbering restarts
        if len(body) == len(page):
            last_fn = 0
        flat += [(pn, ln) for ln in body]

    secs: list[Raw] = []
    chapter = title = ""
    i = 0
    last_key = (0, "")
    n = len(flat)
    while i < n:
        pn, ln = flat[i]
        m = CHAPTER.match(ln)
        if m:
            chapter = m.group(1)
            title_lines = []
            i += 1
            while i < n and not CHAPTER.match(flat[i][1]) and not LONE_NO.match(flat[i][1]):
                title_lines.append(flat[i][1])
                i += 1
            # the title is the leading upper-case lines; later lines are sub-headings or preamble
            keep = []
            for t in title_lines:
                if t != t.upper():
                    break
                keep.append(t)
            title = " ".join(keep)
            continue
        m = LONE_NO.match(ln)
        if m:  # margin copy of the heading; skip to the real start line (may be on the next page)
            target = (int(m.group(1)), m.group(2))
            for j in range(i + 1, min(i + 80, n)):
                m2 = START.match(flat[j][1])
                if m2 and (int(m2.group(1)), m2.group(2)) == target:
                    i = j
                    break
            else:
                i += 1
            continue
        m = START.match(ln)
        if m:
            num, suf = int(m.group(1)), m.group(2)
            key = (num, suf)
            # heading runs up to "--", at most 4 lines
            window = [ln]
            j = i
            while not DASH.search(" ".join(window)) and j + 1 < n and len(window) < 4:
                j += 1
                window.append(flat[j][1])
            joined = " ".join(window)
            if DASH.search(joined) and key > last_key and num - last_key[0] <= 12:
                head_part, rest = DASH.split(joined, 1)
                heading = re.sub(rf"^(?:\d+\*+\[)*{SEC_NO}\.\s+", "", head_part).strip()
                used = len(window)
                # the text on the lines consumed after the "--" belongs to the section
                first = rest.strip()
                raw = Raw(num, suf, chapter, title, heading)
                raw.lines = [first] if first else []
                raw.page_start = pn
                # re-emit remaining text of the last window line already merged into `rest`
                i += used
                while i < n:
                    ln2 = flat[i][1]
                    if CHAPTER.match(ln2) or LONE_NO.match(ln2):
                        break
                    m2 = START.match(ln2)
                    if m2 and (int(m2.group(1)), m2.group(2)) > key and _starts_section(flat, i):
                        break
                    raw.lines.append(ln2)
                    raw.page_end = flat[i][0]
                    i += 1
                raw.page_end = max(raw.page_end, raw.page_start)
                secs.append(raw)
                last_key = key
                continue
        i += 1
    return secs


def _starts_section(flat: list[tuple[int, str]], i: int) -> bool:
    window = " ".join(ln for _, ln in flat[i : i + 4])
    return bool(DASH.search(window))


# ---------------------------------------------------------------- records


def provenance_status_version() -> str:
    path = RAW_DIR / "PROVENANCE.md"
    if path.exists():
        m = re.search(r"source[_ ]status[_ ]version\W+([^\n|]+)", path.read_text(encoding="utf-8"), re.IGNORECASE)
        if m and m.group(1).strip():
            return m.group(1).strip(" `*")
    return "unknown"


def build_records(key: str, status_version: str) -> list[dict]:
    cfg = ACTS[key]
    pdf = RAW_DIR / cfg["pdf"]
    pages = clean_pages(read_pages(pdf))
    empty_pages = {i + 1 for i, p in enumerate(pages) if sum(map(len, p)) < EMPTY_PAGE_CHARS}
    secs = parse_bns(pages, pdf) if key == "bns" else parse_ipc(pages)
    sha = hashlib.sha256(pdf.read_bytes()).hexdigest()
    ver = version(PARSER)

    records: dict[str, dict] = {}
    for s in secs:
        sid = f"{key}:{s.number}{s.suffix}"
        text = join_paragraphs(s.lines)
        review = list(s.review)
        if len(text) < MIN_TEXT_CHARS:
            review.append("very short text")
        if not s.heading:
            review.append("missing heading")
        if not s.chapter:
            review.append("missing chapter")
        if any(p in empty_pages for p in range(s.page_start, s.page_end + 1)):
            review.append("spans a page with no extractable text (scanned?)")
        rec = {
            "section_id": sid,
            "act": cfg["act"],
            "act_label": cfg["act_label"],
            "status": cfg["status"],
            "chapter": s.chapter,
            "chapter_title": s.chapter_title,
            "section_number": s.number,
            "heading": s.heading,
            "text": text,
            "source_pdf": cfg["pdf"],
            "source_sha256": sha,
            "parser": PARSER,
            "parser_version": ver,
            "source_status_version": status_version,
            "needs_review": bool(review),
            "page_start": s.page_start,
            "page_end": s.page_end,
        }
        if sid in records:  # same section captured twice: keep the first, flag it
            records[sid]["needs_review"] = True
            continue
        records[sid] = rec
    return list(records.values())


def up_to_date(path: Path, sha: str) -> bool:
    if not path.exists():
        return False
    try:
        rows = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]
    except ValueError:
        return False
    return bool(rows) and all(
        r.get("source_sha256") == sha
        and r.get("parser") == PARSER
        and r.get("parser_version") == version(PARSER)
        for r in rows
    )


def write_atomic(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".jsonl.tmp")
    with tmp.open("w", encoding="utf-8", newline="\n") as fh:
        for r in records:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    os.replace(tmp, path)


def main() -> int:
    status_version = provenance_status_version()
    for key, cfg in ACTS.items():
        pdf = RAW_DIR / cfg["pdf"]
        if not pdf.exists():
            print(f"missing input: {pdf}", file=sys.stderr)
            return 1
        out = OUT_DIR / f"{key}_sections.jsonl"
        sha = hashlib.sha256(pdf.read_bytes()).hexdigest()
        if up_to_date(out, sha):
            print(f"{out.name}: unchanged (same source hash and parser)")
            continue
        records = build_records(key, status_version)
        write_atomic(out, records)
        flagged = sum(r["needs_review"] for r in records)
        print(f"{out.name}: {len(records)} records, {flagged} need review")
    return 0


if __name__ == "__main__":
    sys.exit(main())
