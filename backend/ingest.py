"""
ingest.py
---------
Turns uploaded course documents into searchable vector indices, PARTITIONED
BY COURSE. Each course gets its own FAISS index + metadata file, so:

  - Retrieval is always scoped to one course (a query for Course A can
    structurally never surface Course B's content).
  - Indices can be rebuilt/reset per-course without touching others.

Pipeline per document:
    PDF/TXT file -> raw text -> overlapping chunks -> embeddings -> that
    course's FAISS index, tagged with course_id/course_name/source/title.

Layout on disk:
    data/index/<course_id>/faiss.index
    data/index/<course_id>/metadata.pkl
"""

import json
import pickle
from pathlib import Path
from typing import List, Dict, Optional

import numpy as np
import faiss
from pypdf import PdfReader
from sentence_transformers import SentenceTransformer

BASE_DIR = Path(__file__).parent
UPLOAD_DIR = BASE_DIR / "data" / "uploads"                # admin manual-upload staging
FACULTY_DIR = BASE_DIR / "data" / "faculty_uploads"        # auto-watched, one subfolder per course
INDEX_DIR = BASE_DIR / "data" / "index"                     # one subfolder per course
COURSES_FILE = BASE_DIR / "data" / "courses.json"

UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
FACULTY_DIR.mkdir(parents=True, exist_ok=True)
INDEX_DIR.mkdir(parents=True, exist_ok=True)

EMBED_MODEL_NAME = "all-MiniLM-L6-v2"   # small, fast, runs on CPU
CHUNK_SIZE = 800
CHUNK_OVERLAP = 150

_model = None  # lazy-loaded singleton


def get_embedder() -> SentenceTransformer:
    global _model
    if _model is None:
        _model = SentenceTransformer(EMBED_MODEL_NAME)
    return _model


# ---------------------------------------------------------------- courses --

def load_courses() -> Dict[str, Dict]:
    """course_id -> {"name": ..., "faculty": ...}. Auto-registers unknown
    course_ids (e.g. a new faculty_uploads/<course_id>/ folder) so nothing
    breaks if courses.json wasn't updated first."""
    if COURSES_FILE.exists():
        return json.loads(COURSES_FILE.read_text())
    return {}


def save_courses(courses: Dict[str, Dict]):
    COURSES_FILE.write_text(json.dumps(courses, indent=2))


def register_course_if_missing(course_id: str):
    courses = load_courses()
    if course_id not in courses:
        courses[course_id] = {"name": course_id, "faculty": "Unknown"}
        save_courses(courses)


def list_courses() -> List[Dict]:
    courses = load_courses()
    return [{"id": cid, **info} for cid, info in sorted(courses.items())]


# ------------------------------------------------------------- extraction --

def extract_text_from_pdf(filepath: Path) -> str:
    reader = PdfReader(str(filepath))
    return "\n".join((page.extract_text() or "") for page in reader.pages)


def extract_text(filepath: Path) -> str:
    suffix = filepath.suffix.lower()
    if suffix == ".pdf":
        return extract_text_from_pdf(filepath)
    elif suffix in (".txt", ".md"):
        return filepath.read_text(errors="ignore")
    else:
        raise ValueError(f"Unsupported file type: {suffix}")


def chunk_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> List[str]:
    text = " ".join(text.split())
    if not text:
        return []
    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunk = text[start:end]
        if chunk.strip():
            chunks.append(chunk)
        start += chunk_size - overlap
    return chunks


# ----------------------------------------------------------- per-course index --

def _course_index_dir(course_id: str) -> Path:
    d = INDEX_DIR / course_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def load_index(course_id: str):
    d = _course_index_dir(course_id)
    index_path = d / "faiss.index"
    meta_path = d / "metadata.pkl"

    if index_path.exists() and meta_path.exists():
        index = faiss.read_index(str(index_path))
        with open(meta_path, "rb") as f:
            metadata = pickle.load(f)
        return index, metadata

    embedder = get_embedder()
    dim = embedder.get_sentence_embedding_dimension()
    index = faiss.IndexFlatIP(dim)  # cosine similarity via normalized vectors
    metadata = []  # list of dicts: source, title, chunk_id, text, course_id, course_name
    return index, metadata


def save_index(course_id: str, index, metadata):
    d = _course_index_dir(course_id)
    faiss.write_index(index, str(d / "faiss.index"))
    with open(d / "metadata.pkl", "wb") as f:
        pickle.dump(metadata, f)


def add_document_to_index(
    filepath: Path,
    source_name: str,
    course_id: str,
    course_name: Optional[str] = None,
    title: Optional[str] = None,
) -> int:
    """Extract, chunk, embed a document into ONE course's index. Returns
    number of chunks added."""
    register_course_if_missing(course_id)
    if course_name:
        courses = load_courses()
        courses.setdefault(course_id, {})["name"] = course_name
        save_courses(courses)
    else:
        course_name = load_courses().get(course_id, {}).get("name", course_id)

    text = extract_text(filepath)
    chunks = chunk_text(text)
    if not chunks:
        return 0

    embedder = get_embedder()
    embeddings = embedder.encode(chunks, normalize_embeddings=True, show_progress_bar=False)
    embeddings = np.array(embeddings, dtype="float32")

    index, metadata = load_index(course_id)
    index.add(embeddings)
    for i, chunk in enumerate(chunks):
        metadata.append({
            "text": chunk,
            "source": source_name,
            "title": title or source_name,
            "chunk_id": i,
            "course_id": course_id,
            "course_name": course_name,
        })
    save_index(course_id, index, metadata)
    return len(chunks)


def list_sources(course_id: str) -> List[Dict]:
    """Distinct materials indexed for a course, e.g. for a materials/download list."""
    _, metadata = load_index(course_id)
    seen = {}
    for m in metadata:
        seen.setdefault(m["source"], {"source": m["source"], "title": m["title"], "course_id": course_id})
    return list(seen.values())


def course_chunk_count(course_id: str) -> int:
    index, _ = load_index(course_id)
    return index.ntotal


def sample_representative_chunks(course_id: str, per_doc: int = 1, max_docs: int = 10) -> List[Dict]:
    """One (or a few) early chunk(s) per distinct document in a course — enough
    breadth to summarize what the course covers without feeding an entire
    course's text through the LLM. Used for the 'Important Topics' feature."""
    _, metadata = load_index(course_id)
    per_source_count: Dict[str, int] = {}
    sampled = []
    seen_sources = []
    for m in metadata:
        src = m["source"]
        if src not in seen_sources:
            if len(seen_sources) >= max_docs:
                continue
            seen_sources.append(src)
        if per_source_count.get(src, 0) < per_doc:
            sampled.append(m)
            per_source_count[src] = per_source_count.get(src, 0) + 1
    return sampled


def sample_broad_chunks(course_id: str, max_chunks: int = 20) -> List[Dict]:
    """Round-robin sample across every distinct document in the course, so
    a fixed-size sample still has breadth even on a course with many
    documents or documents of very different lengths. Used for 'Entire
    Course' quiz generation, where we want questions to be able to draw
    from any material rather than being dominated by one long document."""
    _, metadata = load_index(course_id)
    if not metadata:
        return []

    groups: Dict[str, List[Dict]] = {}
    for m in metadata:
        groups.setdefault(m["source"], []).append(m)
    sources = list(groups.keys())

    result = []
    idx = 0
    safety = 0
    while len(result) < max_chunks and safety < max_chunks * 20:
        source = sources[idx % len(sources)]
        if groups[source]:
            result.append(groups[source].pop(0))
        idx += 1
        safety += 1
        if all(not g for g in groups.values()):
            break
    return result[:max_chunks]


def search(course_id: str, query: str, top_k: int = 4) -> List[Dict]:
    """Retrieval scoped to a single course's index only."""
    index, metadata = load_index(course_id)
    if index.ntotal == 0:
        return []

    embedder = get_embedder()
    q_emb = embedder.encode([query], normalize_embeddings=True)
    q_emb = np.array(q_emb, dtype="float32")

    scores, indices = index.search(q_emb, min(top_k, index.ntotal))
    results = []
    for score, idx in zip(scores[0], indices[0]):
        if idx == -1:
            continue
        item = metadata[idx].copy()
        item["score"] = float(score)
        results.append(item)
    return results


def reset_index(course_id: Optional[str] = None):
    """Wipe one course's index, or everything if course_id is None."""
    if course_id:
        d = INDEX_DIR / course_id
        for f in d.glob("*"):
            f.unlink()
        fac_dir = FACULTY_DIR / course_id
        if fac_dir.exists():
            for f in fac_dir.glob("*"):
                f.unlink()
    else:
        for course_dir in INDEX_DIR.glob("*"):
            for f in course_dir.glob("*"):
                f.unlink()
        for f in UPLOAD_DIR.glob("*"):
            f.unlink()


# ------------------------------------------------------- important-topics cache --
# "Important Topics" is a course-level (not per-question) summary, so it's
# computed once and cached to disk, invalidated whenever the course's chunk
# count changes (i.e. faculty added/removed material).

def _topics_cache_path(course_id: str) -> Path:
    return _course_index_dir(course_id) / "important_topics.json"


def load_topics_cache(course_id: str) -> Optional[Dict]:
    path = _topics_cache_path(course_id)
    if path.exists():
        try:
            return json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            return None
    return None


def save_topics_cache(course_id: str, topics: List[str], source_type: str):
    data = {
        "topics": topics,
        "source_type": source_type,
        "chunk_count": course_chunk_count(course_id),
    }
    _topics_cache_path(course_id).write_text(json.dumps(data))
