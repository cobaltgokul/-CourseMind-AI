"""
rag.py
------
Course-scoped Retrieval-Augmented Generation, with:

  - A relevance gate: if nothing retrieved is actually relevant to the
    question, the assistant falls back to a brief, clearly-labeled GENERAL
    answer instead of forcing an answer out of unrelated course chunks.
  - Three response modes (Normal / Simple / Exam) that change HOW the same
    grounded content gets explained, not WHAT gets retrieved.
  - Instructions that push the model to explain/synthesize/analogize rather
    than paraphrase-close-to-verbatim, while still forbidding claims that
    aren't supported by the retrieved context (or, in the general-fallback
    case, well-established general knowledge).
  - "Important Topics": a course-level (not per-question) synthesis of what
    the course covers, generated once from a sample of each document and
    cached until new material is indexed.
"""

import json
import logging
import re
import requests
from typing import List, Dict, Optional

from ingest import (
    search,
    sample_representative_chunks,
    sample_broad_chunks,
    load_topics_cache,
    save_topics_cache,
    course_chunk_count,
    load_courses,
)

logger = logging.getLogger(__name__)
from pathlib import Path

QUIZ_LOG_PATH = (
    Path(__file__).resolve().parent.parent
    / "eval"
    / "quiz_benchmark_backend.log"
)

QUIZ_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

quiz_file_handler = logging.FileHandler(
    QUIZ_LOG_PATH, encoding="utf-8"
)
quiz_file_handler.setLevel(logging.INFO)
quiz_file_handler.setFormatter(
    logging.Formatter("%(asctime)s %(message)s")
)

logger.addHandler(quiz_file_handler)
logger.setLevel(logging.INFO)

OLLAMA_HOST = "http://localhost:11434"
OLLAMA_URL = f"{OLLAMA_HOST}/api/generate"
OLLAMA_TAGS_URL = f"{OLLAMA_HOST}/api/tags"
OLLAMA_MODEL = "llama3.2:3b"
TOP_K = 4

# Default timeout for call_ollama, used as-is (unchanged) by chat and Important
# Topics generation. Quiz generation uses its own, smaller QUIZ_OLLAMA_TIMEOUT
# instead of this -- see the quiz section below.
OLLAMA_DEFAULT_TIMEOUT = 60
OLLAMA_HEALTH_CHECK_TIMEOUT = 5  # cheap ping to /api/tags, no model load required

# Cosine similarity (IndexFlatIP on normalized MiniLM embeddings) below this
# is treated as "not actually relevant" rather than forced into an answer.
# Tune this per embedding model / domain if answers feel over- or under-gated.
RELEVANCE_THRESHOLD = 0.30

MAX_TOKENS_BY_MODE = {"normal": 260, "simple": 300, "exam": 340}

VALID_MODES = {"normal", "simple", "exam"}

VALID_QUIZ_COUNTS = {5, 10, 15}
VALID_DIFFICULTIES = {"easy", "medium", "hard"}

# --- Quiz generation: one question at a time -------------------------------
# Earlier versions generated questions in fixed-size batches (5 per Ollama
# call). That still meant one call's output length grew with batch size, and
# a single slow/incomplete generation could cost an entire batch. This
# version generates and validates ONE question per Ollama call:
#   - Each call gets a small, rotating slice of context (a handful of
#     chunks, not the whole sampled/retrieved pool), so prompt size per call
#     stays tiny and roughly constant no matter how many questions the
#     student asked for overall.
#   - A dedicated, SMALL per-call timeout (QUIZ_OLLAMA_TIMEOUT) is used
#     instead of the shared 60s OLLAMA_DEFAULT_TIMEOUT -- a single MCQ with
#     a 3-chunk context should complete well inside this, so a call that
#     doesn't is cheaply abandoned and retried with fresh context rather
#     than tying up the request for a full 60s.
#   - keep_alive is passed on quiz calls so Ollama keeps llama3.2:3b loaded
#     in memory across the many rapid single-question calls one quiz
#     generates, instead of risking a reload between calls.
#   - A bounded retry/refill loop keeps requesting new questions (skipping
#     duplicates and malformed output) until exactly the requested count is
#     reached, or a hard attempt cap is hit.
QUIZ_CHUNK_CHAR_LIMIT = 280        # per-chunk prompt size cap
QUIZ_POOL_SIZE_ENTIRE = 24         # sampled chunk pool for "entire course" scope (each chunk yields several "fact slices")
QUIZ_POOL_SIZE_TOPIC_MAX = 20      # retrieved chunk pool cap for "select topic" scope
QUIZ_TOPIC_POOL_MIN = 10           # always retrieve at least this many chunks for a topic
QUIZ_CHUNKS_PER_QUESTION = 2       # excerpts sent for ONE question: 1 FOCUS slice + (n-1) context excerpts for distractors
QUIZ_MAX_ATTEMPTS_MULTIPLIER = 4   # hard cap: at most num_questions * this many total tries
QUIZ_OLLAMA_TIMEOUT = 25           # seconds -- quiz-specific, deliberately smaller than the 60s default
QUIZ_KEEP_ALIVE = "10m"            # keep the model loaded across a quiz's many rapid calls
QUIZ_DUPLICATE_JACCARD_THRESHOLD = 0.75  # content-word overlap ratio above which a new question is treated as a repeat
QUIZ_TEMPERATURE_BASE = 0.35       # first attempt; rises on consecutive rejections so retries are not clones
QUIZ_TEMPERATURE_STEP = 0.15
QUIZ_TEMPERATURE_MAX = 0.9
QUIZ_MIN_SLICE_CHARS = 60          # ignore tiny leftover slices of a chunk
QUIZ_AVOID_LIST_MAX = 8            # cap how many prior questions get echoed into the "don't repeat" prompt hint

# Duplicate detection compares CONTENT words (nouns/verbs/topic terms), not raw
# character similarity. Character-level similarity is the wrong tool here: two
# genuinely different questions sharing a template ("...the INPUT layer..." vs
# "...the OUTPUT layer...") can score a HIGHER character-similarity ratio than
# a true reworded duplicate does, because it's dominated by shared boilerplate
# rather than the words that actually distinguish the questions. Stripping
# common/template words and comparing what's left (Jaccard overlap) avoids
# that failure mode.
QUIZ_DEDUP_STOPWORDS = {
    "what", "is", "are", "was", "were", "the", "a", "an", "of", "on", "to", "for", "and", "or",
    "does", "do", "did", "how", "why", "which", "this", "that", "these", "those", "its", "it", "in",
    "main", "primary", "key", "purpose", "role", "function", "according", "excerpt", "excerpts",
    "material", "materials", "course", "following", "below", "above", "true", "false", "not",
    "correct", "incorrect", "best", "most", "describes", "describe", "explain", "explains",
}


# ------------------------------------------------------------- prompt rules --

BASE_RULES = """You are a course assistant embedded on a college course-material page.
Use the context below, which comes from official materials for THIS course, only as
grounding for your answer.

Critical rules:
- Do NOT copy sentences verbatim from the context. Explain the idea in your own words.
- Where it genuinely helps understanding, add a short real-world analogy or example --
  but don't force one in if it doesn't fit.
- Never state anything that contradicts the context.
- Never introduce facts that aren't supported by the context. If something is
  genuinely unclear or not covered, say so briefly rather than guessing.
- Never repeat the question back to the student.
"""

MODE_STYLE = {
    "normal": "Respond in 2-4 clear, direct sentences. No filler like 'based on the context'.",
    "simple": ("Explain it as if the student has never seen this topic before. Use plain, "
               "everyday language, avoid jargon (or briefly define any term you must use), "
               "and include one short relatable analogy or example. 3-5 sentences."),
    "exam": ("Answer in exam-ready format: start with one precise definition or key statement, "
             "then 2-4 short bullet points (each starting with '- ') covering the details most "
             "likely to be tested. No conversational filler."),
}

JSON_SHAPE_INSTRUCTIONS = """
Respond with ONLY a JSON object (no markdown fences, no commentary outside the JSON),
in exactly this shape:

{
  "explanation": "your answer, following the style instructions above",
  "concepts": ["Important term or idea 1", "up to 5 short (2-6 word) noun phrases"]
}
"""

GENERAL_FALLBACK_INSTRUCTIONS = """You are a course assistant embedded on a college course-material page.
Nothing sufficiently relevant to the student's question was found in this course's
uploaded materials.

Give a brief, accurate GENERAL explanation from your own knowledge -- NOT tied to any
specific course document. Keep it to 2-3 sentences maximum, regardless of any response
style, since this is a fallback rather than a course-grounded answer. Do not imply this
came from the course materials. If you're not confident in a general answer either,
say so briefly instead of guessing.

Respond with ONLY a JSON object: {"explanation": "...", "concepts": []}
"""

TOPICS_INSTRUCTIONS = """You are summarizing what a college course covers, based on excerpts from its
official materials below (one excerpt per document, not the full material).

List the most important topics a student should know for this course, derived ONLY
from these excerpts. Do not invent topics not suggested by the material.

Respond with ONLY a JSON object: {"topics": ["Topic 1", "Topic 2", "...", "6-10 total, each a short (2-6 word) phrase"]}
"""

QUIZ_INSTRUCTIONS = """You are generating a multiple-choice quiz for a college course, based ONLY on
the excerpts below from its official materials.

Create exactly {num_questions} multiple-choice question(s) at {difficulty} difficulty about {scope_desc}.

Rules:
- Each question must be answerable using ONLY the excerpts below. Never invent facts,
  numbers, or claims that aren't supported by them.
- Each question has exactly 4 answer options, with exactly 1 correct answer.
- Wrong options (distractors) should be plausible to someone who hasn't studied the
  material, but clearly wrong to someone who has -- not nonsensical, not trick wording.
- For each question, give a one-sentence explanation of why the correct answer is right,
  and the exact source filename (copy it exactly from the [Source: ...] tag) it's grounded in.
- Spread questions across different source documents where the excerpts allow it, rather
  than writing all of them from a single excerpt.
- Difficulty guide -- easy: direct recall/definition-level; medium: applying a concept to
  a short scenario; hard: multi-concept reasoning or a subtle distinction between ideas.

Respond with ONLY a JSON object (no markdown fences, no commentary outside the JSON),
in exactly this shape:
{{
  "questions": [
    {{
      "question": "...",
      "options": ["option A", "option B", "option C", "option D"],
      "correct_index": 0,
      "explanation": "...",
      "source": "exact-filename.pdf"
    }}
  ]
}}
"""


def build_chat_prompt(question: str, chunks: List[Dict], mode: str) -> str:
    context_blocks = [f"[Source: {c['source']}]\n{c['text']}" for c in chunks]
    context = "\n\n---\n\n".join(context_blocks)
    style = MODE_STYLE.get(mode, MODE_STYLE["normal"])
    return f"""{BASE_RULES}
Response style: {style}
{JSON_SHAPE_INSTRUCTIONS}

Context:
{context}

Question: {question}

JSON response:"""


def build_general_prompt(question: str, mode: str) -> str:
    style = MODE_STYLE.get(mode, MODE_STYLE["normal"])
    return f"""{GENERAL_FALLBACK_INSTRUCTIONS}
Response style (still keep it to 2-3 sentences total): {style}

Question: {question}

JSON response:"""


def build_topics_prompt(course_name: str, chunks: List[Dict]) -> str:
    context_blocks = [f"[{c['source']}]\n{c['text'][:500]}" for c in chunks]
    context = "\n\n---\n\n".join(context_blocks)
    return f"""{TOPICS_INSTRUCTIONS}

Course: {course_name}

Excerpts:
{context}

JSON response:"""


def build_quiz_prompt(
    course_name: str,
    chunks: List[Dict],
    num_questions: int,
    difficulty: str,
    scope_desc: str,
    avoid_questions: Optional[List[str]] = None,
    focus_first: bool = False,
) -> str:
    context_blocks = [f"[Source: {c['source']}]\n{c['text'][:QUIZ_CHUNK_CHAR_LIMIT]}" for c in chunks]
    context = "\n\n---\n\n".join(context_blocks)
    instructions = QUIZ_INSTRUCTIONS.format(
        num_questions=num_questions, difficulty=difficulty, scope_desc=scope_desc
    )

    avoid_block = ""
    if avoid_questions:
        avoid_list = "\n".join(f"- {q}" for q in avoid_questions[-QUIZ_AVOID_LIST_MAX:])
        avoid_block = (
            "\n\nDo NOT repeat or closely rephrase any of these questions already used "
            f"earlier in this same quiz:\n{avoid_list}\n"
        )

    focus_block = ""
    if focus_first:
        focus_block = (
            "\n\nIMPORTANT: Write the question about the FIRST excerpt below. Its main fact must be what "
            "the question tests and what the correct answer states. The other excerpt(s) are context only "
            "-- use them at most to make plausible wrong options."
        )

    return f"""{instructions}{focus_block}{avoid_block}

Course: {course_name}

Excerpts:
{context}

JSON response:"""


# ------------------------------------------------------------------ ollama --

def call_ollama(
    prompt: str,
    max_tokens: int,
    timeout: int = OLLAMA_DEFAULT_TIMEOUT,
    keep_alive: Optional[str] = None,
    temperature: Optional[float] = None,
    seed: Optional[int] = None,
) -> str:
    """Unchanged default behavior for existing callers (chat, Important
    Topics): timeout=60, no keep_alive field sent, exactly as before.
    Quiz generation passes its own smaller `timeout` and a `keep_alive`
    value explicitly -- see generate_quiz."""
    payload = {
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
        "format": "json",
        "options": {"num_predict": max_tokens, "temperature": 0.25},
    }
    # Optional per-call sampling overrides (used only by quiz retries so a
    # retry is not a deterministic clone of the failed attempt). Chat and
    # Important Topics never pass these, so their payload is unchanged.
    if temperature is not None:
        payload["options"]["temperature"] = temperature
    if seed is not None:
        payload["options"]["seed"] = seed
    if keep_alive is not None:
        payload["keep_alive"] = keep_alive

    logger.info("OLLAMA_CALL: model=%s", OLLAMA_MODEL)
    response = requests.post(OLLAMA_URL, json=payload, timeout=timeout)
    response.raise_for_status()
    return response.json().get("response", "").strip()


def ollama_health_check() -> bool:
    """Cheap reachability check against Ollama's /api/tags -- does NOT load
    or run the model, just confirms the Ollama server itself is up. This is
    what lets quiz generation distinguish 'Ollama isn't running at all'
    (llm_offline) from 'Ollama is up but this generation attempt failed or
    produced bad output' (generation_failed), instead of collapsing both
    into the same error."""
    try:
        response = requests.get(OLLAMA_TAGS_URL, timeout=OLLAMA_HEALTH_CHECK_TIMEOUT)
        return response.ok
    except requests.exceptions.RequestException:
        return False


def _extract_json_candidates(raw: str) -> List[str]:
    candidates = [raw]
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
    if fenced:
        candidates.append(fenced.group(1))
    brace_match = re.search(r"\{.*\}", raw, re.DOTALL)
    if brace_match:
        candidates.append(brace_match.group(0))
    return candidates


def parse_structured_answer(raw: str) -> Dict:
    """Best-effort JSON parsing for {explanation, concepts}. Small local
    models sometimes wrap JSON in prose or code fences."""
    for candidate in _extract_json_candidates(raw):
        try:
            data = json.loads(candidate)
            explanation = str(data.get("explanation", "")).strip()
            concepts = data.get("concepts", [])
            concepts = [str(c).strip() for c in concepts if str(c).strip()][:5] if isinstance(concepts, list) else []
            if explanation:
                return {"explanation": explanation, "concepts": concepts}
        except (json.JSONDecodeError, AttributeError):
            continue
    return {"explanation": raw.strip() or "I couldn't generate an answer.", "concepts": []}


def parse_topics_answer(raw: str) -> List[str]:
    for candidate in _extract_json_candidates(raw):
        try:
            data = json.loads(candidate)
            topics = data.get("topics", [])
            if isinstance(topics, list):
                cleaned = [str(t).strip() for t in topics if str(t).strip()]
                if cleaned:
                    return cleaned[:10]
        except (json.JSONDecodeError, AttributeError):
            continue
    return []


def parse_quiz_answer(raw: str, valid_sources: List[str]) -> List[Dict]:
    """Best-effort JSON parsing for {"questions": [...]}. Drops individual
    questions that don't come back well-formed (wrong option count, missing
    correct_index, etc.) rather than failing the whole batch -- small local
    models are more likely to get one question wrong than the whole array."""
    for candidate in _extract_json_candidates(raw):
        try:
            data = json.loads(candidate)
            raw_questions = data.get("questions", [])
            if not isinstance(raw_questions, list):
                continue

            cleaned = []
            for q in raw_questions:
                if not isinstance(q, dict):
                    continue
                question_text = str(q.get("question", "")).strip()
                options = q.get("options")
                correct_index = q.get("correct_index")
                explanation = str(q.get("explanation", "")).strip()
                source = str(q.get("source", "")).strip()

                if not question_text or not isinstance(options, list) or len(options) != 4:
                    continue
                options = [str(o).strip() for o in options]
                if any(not o for o in options):
                    continue
                try:
                    correct_index = int(correct_index)
                except (TypeError, ValueError):
                    continue
                if not (0 <= correct_index < 4):
                    continue

                # If the model garbled the source filename, fall back to the
                # first valid source rather than showing a broken citation.
                if valid_sources and source not in valid_sources:
                    source = valid_sources[0]

                cleaned.append({
                    "question": question_text,
                    "options": options,
                    "correct_index": correct_index,
                    "explanation": explanation or "See the cited course material for details.",
                    "source": source,
                })
            if cleaned:
                return cleaned
        except (json.JSONDecodeError, AttributeError, TypeError):
            continue
    return []


def extractive_fallback(chunks: List[Dict]) -> Dict:
    """Used when Ollama itself is unreachable (not the same as 'no relevant
    content' -- this is 'no LLM available at all')."""
    top = chunks[0]
    snippet = top["text"][:280].rsplit(" ", 1)[0]
    return {"explanation": f'(LLM offline — closest match) "{snippet}..."', "concepts": []}


# --------------------------------------------------------------- main entry --

def answer_question(question: str, course_id: str, mode: str = "normal") -> Dict:
    mode = mode if mode in VALID_MODES else "normal"
    max_tokens = MAX_TOKENS_BY_MODE[mode]

    total_chunks = course_chunk_count(course_id)
    if total_chunks == 0:
        return {
            "explanation": "No materials are indexed for this course yet. "
                            "Ask your faculty to upload course documents first.",
            "concepts": [],
            "sources": [],
            "source_type": "no_materials",
            "used_llm": False,
            "mode": mode,
        }

    chunks = search(course_id, question, top_k=TOP_K)
    top_score = chunks[0]["score"] if chunks else -1.0
    grounded = bool(chunks) and top_score >= RELEVANCE_THRESHOLD

    if not grounded:
        # Relevant course content wasn't found -- fall back to a brief,
        # clearly-labeled general answer instead of forcing the LLM to use
        # unrelated retrieved chunks.
        prompt = build_general_prompt(question, mode)
        try:
            raw = call_ollama(prompt, max_tokens=160)  # deliberately short: this is a fallback
            structured = parse_structured_answer(raw)
            used_llm = True
        except requests.exceptions.RequestException:
            structured = {
                "explanation": "This doesn't appear to be covered in this course's materials, "
                                "and I can't reach the local language model for a general answer "
                                "right now.",
                "concepts": [],
            }
            used_llm = False
        return {
            "explanation": structured["explanation"],
            "concepts": [],  # no course-grounded concepts for a general fallback
            "sources": [],
            "source_type": "general_fallback",
            "used_llm": used_llm,
            "mode": mode,
        }

    prompt = build_chat_prompt(question, chunks, mode)
    try:
        raw = call_ollama(prompt, max_tokens=max_tokens)
        structured = parse_structured_answer(raw)
        used_llm = True
        source_type = "course_grounded"
    except requests.exceptions.RequestException:
        structured = extractive_fallback(chunks)
        used_llm = False
        source_type = "llm_offline"

    sources = sorted(set(c["source"] for c in chunks if c["score"] >= RELEVANCE_THRESHOLD))
    return {
        "explanation": structured["explanation"],
        "concepts": structured["concepts"],
        "sources": sources,
        "source_type": source_type,
        "used_llm": used_llm,
        "mode": mode,
    }


def search_materials(course_id: str, query: str, top_k: int = 5) -> List[Dict]:
    """Direct material search (item 3): no LLM involved, just the retrieval
    layer surfaced to the student -- exact source + snippet per match."""
    chunks = search(course_id, query, top_k=top_k)
    results = []
    for c in chunks:
        snippet = c["text"][:220].rsplit(" ", 1)[0]
        results.append({
            "source": c["source"],
            "title": c["title"],
            "snippet": snippet + ("..." if len(c["text"]) > len(snippet) else ""),
            "score": round(c["score"], 3),
        })
    return results


def get_important_topics(course_id: str, force_refresh: bool = False) -> Dict:
    """Course-level 'Important Topics' summary. Cached until the course's
    chunk count changes (i.e. faculty adds/removes material)."""
    current_count = course_chunk_count(course_id)

    if not force_refresh:
        cached = load_topics_cache(course_id)
        if cached and cached.get("chunk_count") == current_count:
            return {"topics": cached["topics"], "source_type": cached["source_type"]}

    if current_count == 0:
        return {"topics": [], "source_type": "no_materials"}

    course_name = load_courses().get(course_id, {}).get("name", course_id)
    sample_chunks = sample_representative_chunks(course_id, per_doc=1, max_docs=10)

    try:
        prompt = build_topics_prompt(course_name, sample_chunks)
        raw = call_ollama(prompt, max_tokens=220)
        topics = parse_topics_answer(raw)
        if topics:
            save_topics_cache(course_id, topics, "llm_generated")
            return {"topics": topics, "source_type": "llm_generated"}
    except requests.exceptions.RequestException:
        pass

    # Fallback with no LLM available: use document titles as a rough stand-in.
    titles = sorted(set(c["title"] for c in sample_chunks))
    save_topics_cache(course_id, titles, "document_titles_fallback")
    return {"topics": titles, "source_type": "document_titles_fallback"}


def _quiz_max_tokens(num_questions: int) -> int:
    return min(900, 180 + 120 * num_questions)


def _rotate_pool_slice(pool: List[Dict], index: int, num_windows: int, size: int) -> List[Dict]:
    """Kept for compatibility. Pick a `size`-chunk window from `pool`, spread
    across it by `index`. generate_quiz no longer uses this: with only
    ~num_windows distinct windows, retries cycled back to identical context."""
    n = len(pool)
    if n == 0:
        return []
    if n <= size:
        return pool
    start = (index * n) // max(num_windows, 1)
    return [pool[(start + i) % n] for i in range(size)]


def _build_focus_units(pool: List[Dict]) -> List[Dict]:
    """Split every pooled chunk into QUIZ_CHUNK_CHAR_LIMIT-sized "fact
    slices" and order them round-robin across source documents (and across
    slice depth), so consecutive attempts always target DIFFERENT facts from
    DIFFERENT materials. A 800-char chunk yields ~3 units, so 12-24 chunks
    give 36-72 distinct units -- far more than the 15 questions ever needed,
    which is what lets us never reuse the same context for a retry."""
    by_source: Dict[str, List[Dict]] = {}
    for ci, chunk in enumerate(pool):
        text = chunk["text"]
        for k, off in enumerate(range(0, max(len(text), 1), QUIZ_CHUNK_CHAR_LIMIT)):
            piece = text[off:off + QUIZ_CHUNK_CHAR_LIMIT].strip()
            if len(piece) < QUIZ_MIN_SLICE_CHARS and k > 0:
                continue
            if not piece:
                continue
            unit = dict(chunk)
            unit["text"] = piece
            unit["_depth"] = k
            unit["_ci"] = ci
            by_source.setdefault(chunk["source"], []).append(unit)

    # depth-major, then source round-robin: all first slices of every doc, then second slices, ...
    ordered: List[Dict] = []
    for depth in range(0, 50):
        layer = [[u for u in units if u["_depth"] == depth] for units in by_source.values()]
        if not any(layer):
            break
        i = 0
        while any(layer):
            if layer[i % len(layer)]:
                ordered.append(layer[i % len(layer)].pop(0))
            i += 1
    return ordered


def _content_words(text: str) -> set:
    """Strip common/template words, keep the terms that actually distinguish
    one question from another (see QUIZ_DEDUP_STOPWORDS comment above)."""
    words = re.findall(r"[a-z0-9]+", text.lower())
    return {w for w in words if w not in QUIZ_DEDUP_STOPWORDS and len(w) > 2}


def _is_duplicate_question(question_text: str, seen_word_sets: List[set]) -> bool:
    """Content-word Jaccard overlap against every previously accepted
    question in this quiz. Catches exact repeats and reworded duplicates
    without falsely flagging different questions that merely share a
    sentence template (see module-level comment on QUIZ_DEDUP_STOPWORDS)."""
    words = _content_words(question_text)
    if not words:
        return False  # nothing meaningful to compare against; let it through
    for seen in seen_word_sets:
        if not seen:
            continue
        union = words | seen
        if not union:
            continue
        jaccard = len(words & seen) / len(union)
        if jaccard >= QUIZ_DUPLICATE_JACCARD_THRESHOLD:
            return True
    return False


def _quiz_result(questions: Optional[List[Dict]] = None, error: Optional[str] = None, **extra) -> Dict:
    result = {"questions": questions or [], "error": error}
    result.update(extra)
    return result


def generate_quiz(
    course_id: str,
    scope: str,
    topic: str,
    num_questions: int,
    difficulty: str,
) -> Dict:
    """Generate an MCQ quiz grounded in one course's materials, ONE
    validated question at a time.

    scope="entire": broad round-robin sample across every indexed document,
    so questions can draw from anywhere in the course.
    scope="topic": chunks retrieved specifically for `topic` (one of the
    course's existing Important Topics), same relevance-scored search used
    for chat.

    Design, per-question:
      1. A small, rotating slice of context (QUIZ_CHUNKS_PER_QUESTION chunks)
         is fed to a single Ollama call asking for exactly 1 question, with
         a small quiz-specific timeout (QUIZ_OLLAMA_TIMEOUT) and keep_alive
         so the model stays warm across the many calls one quiz needs.
      2. The response is parsed with the SAME parse_quiz_answer() used
         everywhere else (still expects {"questions": [...]}, just with at
         most one item) -- no schema change.
      3. If the question is malformed, a duplicate/near-duplicate of one
         already accepted, or the call fails outright, that attempt is
         discarded and a fresh attempt (different context window) is made.
      4. This repeats until exactly `num_questions` valid, distinct
         questions are accepted, or a hard attempt cap is hit.

    An Ollama health check runs BEFORE any of this, so "Ollama isn't
    running at all" (llm_offline) is never confused with "Ollama is up but
    generation didn't succeed within the retry budget" (generation_failed).
    A successful response always contains exactly `num_questions` — if the
    retry budget is exhausted first, that's reported as generation_failed
    rather than silently returning fewer questions.
    """
    num_questions = num_questions if num_questions in VALID_QUIZ_COUNTS else 5
    difficulty = difficulty if difficulty in VALID_DIFFICULTIES else "medium"

    if course_chunk_count(course_id) == 0:
        return _quiz_result(error="no_materials")

    if not ollama_health_check():
        return _quiz_result(error="llm_offline")

    course_name = load_courses().get(course_id, {}).get("name", course_id)

    if scope == "topic" and topic:
        pool = search(
            course_id, topic,
            top_k=min(QUIZ_POOL_SIZE_TOPIC_MAX, max(QUIZ_TOPIC_POOL_MIN, num_questions + 4)),
        )
        scope_desc = f"the topic \"{topic}\""
    else:
        pool = sample_broad_chunks(course_id, max_chunks=QUIZ_POOL_SIZE_ENTIRE)
        scope_desc = "the course as a whole, drawing from across its different materials"

    if not pool:
        return _quiz_result(error="no_relevant_content")

    valid_sources = sorted(set(c["source"] for c in pool))
    single_q_tokens = _quiz_max_tokens(1)

    units = _build_focus_units(pool)
    if not units:
        return _quiz_result(error="no_relevant_content")
    # Context chunks (for distractors) come from the pool but are never the focus.
    context_pool = pool

    accepted: List[Dict] = []
    seen_word_sets: List[set] = []
    rejected: List[str] = []          # duplicate questions we threw away; shown to the model as "avoid"
    stats = {"timeout_or_http": 0, "malformed": 0, "duplicate": 0}
    max_attempts = num_questions * QUIZ_MAX_ATTEMPTS_MULTIPLIER
    consecutive_rejects = 0

    attempt = 0
    while len(accepted) < num_questions and attempt < max_attempts:
        # EVERY attempt gets a new focus fact; units are only reused once all
        # of them have been tried (and then at a different temperature/seed).
        focus = units[attempt % len(units)]
        extras = [
            c for c in context_pool
            if c["source"] != focus["source"] or c["text"][:40] != focus["text"][:40]
        ]
        extras = [extras[(attempt * 3 + j) % len(extras)] for j in range(QUIZ_CHUNKS_PER_QUESTION - 1)] if extras else []
        window = [focus] + extras

        avoid_questions = (
            [q["question"] for q in accepted[-QUIZ_AVOID_LIST_MAX:]] + rejected[-3:]
        )[-QUIZ_AVOID_LIST_MAX:]
        temperature = min(
            QUIZ_TEMPERATURE_MAX, QUIZ_TEMPERATURE_BASE + QUIZ_TEMPERATURE_STEP * consecutive_rejects
        )
        attempt += 1

        try:
            prompt = build_quiz_prompt(
                course_name, window, 1, difficulty, scope_desc, avoid_questions, focus_first=True
            )
            raw = call_ollama(
                prompt,
                max_tokens=single_q_tokens,
                timeout=QUIZ_OLLAMA_TIMEOUT,
                keep_alive=QUIZ_KEEP_ALIVE,
                temperature=temperature,
                seed=attempt * 7919,
            )
        except requests.exceptions.RequestException:
            # Per-call hiccup, NOT "offline" (the health check already passed).
            stats["timeout_or_http"] += 1
            consecutive_rejects += 1
            continue

        parsed = parse_quiz_answer(raw, valid_sources)
        if not parsed:
            stats["malformed"] += 1
            consecutive_rejects += 1
            continue

        candidate = parsed[0]
        if _is_duplicate_question(candidate["question"], seen_word_sets):
            stats["duplicate"] += 1
            consecutive_rejects += 1
            rejected.append(candidate["question"])
            continue

        # The question was written about the focus excerpt, so cite THAT
        # file (parse_quiz_answer's fallback would otherwise pick valid_sources[0]).
        candidate["source"] = focus["source"]
        accepted.append(candidate)
        seen_word_sets.append(_content_words(candidate["question"]))
        consecutive_rejects = 0

    if len(accepted) < num_questions:
        # Health check already proved Ollama is reachable, so this is a genuine
        # generation failure. Log WHY so it is diagnosable instead of a bare 502.
        logger.warning(
            "quiz generation_failed course=%s scope=%s requested=%d accepted=%d attempts=%d "
            "units=%d timeouts=%d malformed=%d duplicates=%d",
            course_id, scope, num_questions, len(accepted), attempt, len(units),
            stats["timeout_or_http"], stats["malformed"], stats["duplicate"],
        )
        return _quiz_result(error="generation_failed")

    for i, q in enumerate(accepted):
        q["id"] = f"q{i + 1}"

    return _quiz_result(
        questions=accepted,
        error=None,
        num_requested=num_questions,
        num_generated=len(accepted),
        scope=scope,
        topic=topic if scope == "topic" else None,
        difficulty=difficulty,
    )
