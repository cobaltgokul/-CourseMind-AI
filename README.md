# Course Assistant — Multi-Course RAG Chatbot (Deep Learning Course Project)

A course-aware Retrieval-Augmented Generation (RAG) assistant embedded as a
small popup widget on college course-material pages. It indexes materials
from **all courses** (5+ PDFs each, in this demo), but every student only
ever sees and queries **their selected course** — retrieval, materials
list, and downloads are all scoped to one course_id at a time.

Faculty documents are indexed automatically in the background.
**Students never upload anything.**

## What's new in this version

- **Quiz mode.** A third "Quiz" tab alongside Ask and Search. Students choose
  "Entire Course" or "Select Topic" (reusing the existing Important Topics
  list), pick 5/10/15 questions and Easy/Medium/Hard difficulty, then get
  course-grounded MCQs (4 options, 1 correct answer, an explanation, and the
  exact source PDF) one question at a time, followed by a score, a full
  review, and Retry/New Quiz options. Entirely additive — Ask and Search work
  exactly as before.
- **Relevance-gated retrieval.** Every retrieval is scored (cosine similarity).
  If the best match is below a threshold, the assistant doesn't force an
  answer out of unrelated course chunks — it clearly labels the answer as
  general knowledge instead (see "General fallback" below).
- **Study/Exam response modes.** Every question can be asked in **Normal**,
  **Simple**, or **Exam** mode — same retrieval, different explanation style
  (concise / plain-language-with-analogy / exam-bullet-format).
- **Course Material Search.** A separate "Search" tab in the widget bypasses
  the LLM entirely and shows the exact matching passages with their source
  PDF and a snippet — useful when a student wants to find *where* something
  is covered, not just an explanation.
- **Important Topics.** A course-level (not per-question) synthesis of what
  the course covers, generated from a sample of every document and cached
  until faculty adds new material.
- **Smarter prompting.** The model is explicitly instructed not to copy
  context verbatim, to explain in its own words, to add an analogy/example
  where it helps, and never to contradict or go beyond what the context (or,
  in the general-fallback case, general knowledge) actually supports.
- **General fallback, clearly labeled.** If nothing relevant is found, the
  widget shows a distinctly-styled badge — "General knowledge — not from
  course material" — instead of silently blending it in with grounded answers.

## How it works

```
 Faculty drops file into              Auto-watcher tags it
 faculty_uploads/<course_id>/  --->   with course_id + course_name --->  Extract, chunk, embed
                                       (faculty_watch.py)                       |
                                                                                 v
                                                              That course's OWN FAISS index
                                                              data/index/<course_id>/
                                                                                 |
 Student picks a course from a          |
 "Select Registered Course" dropdown ---|
                                         |
 Student asks a question (mode: Normal/Simple/Exam)
   or searches materials directly  ------ query -------->  embed  ------------|
                                                                                 v
                                                            top-k chunks + similarity scores
                                                                                 |
                                              score >= threshold?  ---- no ---->  general-knowledge
                                                     |  yes                       fallback prompt
                                                     v                            (clearly labeled,
                                    mode-specific prompt: explain in own          brief, not grounded)
                                    words, analogy if helpful, no verbatim
                                    copying, no unsupported claims
                                                     |
                                                     v
                                     Local LLM (Ollama) returns { explanation, concepts }
                                                     |
                                                     v
              Widget renders explanation + concept chips + source tags (or general-knowledge badge)
              Course page dims all materials except the cited source(s)
```

No student-facing upload UI exists anywhere in the system — documents only
enter via `faculty_watch.py` (or, for manual testing, the admin panel).

## 1. Prerequisites

- Python 3.10+
- [Ollama](https://ollama.com/download) installed (for LLM-generated answers — optional, there's a graceful fallback)

## 2. Setup

```bash
cd backend
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

Pull a small local model (one-time, ~2GB):
```bash
ollama pull llama3.2:3b
```

## 3. Generate sample course data (optional — already included, but regenerable)

```bash
python3 scripts/generate_sample_data.py
```

This creates 5 PDFs each for two demo courses directly inside
`backend/data/faculty_uploads/ISWE411L/` and `.../MGT2001/` — exactly where
the auto-watcher expects new faculty material.

## 4. Run the backend

```bash
cd backend
uvicorn main:app --reload --port 8000
```

## 5. Start the faculty auto-watcher

In a **second terminal**:

```bash
cd backend
python3 faculty_watch.py
```

This watches every subfolder under `data/faculty_uploads/` — each subfolder
name is treated as a `course_id` — and indexes new/updated files into that
course's own index automatically. With the sample data already in place,
it'll index all 10 PDFs (5 per course) within a few seconds of starting.

## 6. Open the student-facing widget

```bash
cd frontend
python3 -m http.server 5500
```

Visit `http://localhost:5500/course-page.html`.

This mirrors a real student portal's course page: a **"Select Registered
Course" dropdown** (populated from `/courses`, formatted the same way —
`Fall Semester 2026-27 - ISWE411L - Deep Learning - TH - Theory Only - 3.0`).
Materials only appear once a course is selected, and the widget switches
context live via `window.CourseAssistant.setCourse(id, name)` — no page
reload, same as a real single-page portal course view.

Pick "Deep Learning" and ask something (e.g. *"What is reinforcement
learning?"*) — you'll see:

1. A concise explanation.
2. An **Important Concepts** chip list.
3. The material list dimming, with the source PDF(s) highlighted.

Then switch the dropdown to "Principles of Management" and ask a
management question — the widget clears its context and only draws from
that course's own materials.

### Trying Quiz mode

Click the **Quiz** tab (next to Ask and Search):

1. Choose **Entire Course** or **Select Topic** (the topic list is pulled
   from the same Important Topics feature — click Topics on the Ask tab
   first if you want to see where those come from).
2. Pick 5, 10, or 15 questions and a difficulty.
3. Click **Generate Quiz** — this calls Ollama, so it can take a little
   while on a local model, especially for 15 questions.
4. Answer one question at a time. Each answer is locked in immediately and
   shows the correct option, an explanation, and the source PDF it came
   from (the material list on the page highlights that source too, same as
   Ask/Search).
5. After the last question, you'll see a score, a full review of every
   question, and **Retry Same Quiz** (re-attempt the same questions) or
   **New Quiz** (back to setup for different settings).

Switching courses mid-quiz resets back to a fresh setup screen — a
half-finished quiz for the old course is never left dangling.

### Embedding the widget on a real page

**If the host page has its own course selector** (recommended — mirrors a
real portal like the screenshot this was modeled on):

```html
<script>
  window.COURSE_ASSISTANT_CONFIG = {
    apiBase: "http://localhost:8000",
    courseSelector: "external",   // tells the widget: don't show its own picker
    title: "Course Assistant"
  };
</script>
<script src="widget.js"></script>
<script>
  // call this whenever the page's own dropdown changes:
  window.CourseAssistant.setCourse("ISWE411L", "Deep Learning");
</script>
```

**If the widget is embedded on one fixed course's own page** (no selector needed):

```html
<script>
  window.COURSE_ASSISTANT_CONFIG = {
    apiBase: "http://localhost:8000",
    courseId: "ISWE411L",
    title: "Course Assistant"
  };
</script>
<script src="widget.js"></script>
```

For the page-level highlighting to work, give each material row/card an
attribute pair the widget can match against:

```html
<tr data-course-material data-source="M4-reinforcement-learning.pdf">...</tr>
```

`data-source` must exactly match the filename as indexed (see `/materials`).

## 7. Admin / testing panel (not shown to students)

`frontend/admin.html` — pick a course, manually upload a document (fallback
to the auto-watcher), inspect indexed materials, and sanity-check answers
including the raw `concepts`/`sources` fields.

## Project structure

```
college-rag-chatbot/
├── backend/
│   ├── main.py                  # FastAPI: /courses, /materials, /materials/download,
│   │                                /chat (student-facing) + /upload, /reset (admin)
│   ├── ingest.py                  # Extraction, chunking, embedding, PER-COURSE FAISS indices
│   ├── rag.py                      # Relevance-gated retrieval, Normal/Simple/Exam prompts,
│   │                                  Important Topics generation, anti-copying/anti-hallucination rules
│   ├── faculty_watch.py             # Auto-indexes faculty_uploads/<course_id>/ subfolders
│   ├── requirements.txt
│   └── data/
│       ├── courses.json              # course_id -> {name, faculty}
│       ├── faculty_uploads/            # faculty drops files here, per course subfolder
│       │   ├── ISWE411L/                # 5 sample PDFs
│       │   └── MGT2001/                  # 5 sample PDFs
│       ├── uploads/                       # admin manual-upload staging
│       └── index/                          # one FAISS index per course_id (created at runtime)
├── frontend/
│   ├── widget.js                  # Embeddable popup widget: course-aware, Ask/Search/Quiz tabs,
│   │                                  Normal/Simple/Exam modes, Important Topics, page highlighting,
│   │                                  external-course-selector API (Shadow DOM isolated)
│   ├── course-page.html            # Student portal-style page with a "Select Registered Course"
│   │                                  dropdown (mirrors real portals like VTOP), drives the widget live
│   └── admin.html                   # Faculty/admin panel — manual upload + testing, not for students
├── scripts/
│   └── generate_sample_data.py     # Generates the 10 sample course PDFs
└── README.md
```

## API reference

| Method | Endpoint                              | Used by          | Description |
|--------|----------------------------------------|------------------|--------------|
| GET    | `/courses`                              | Student widget/page | List of `{id, name, faculty, semester, type, credits}` |
| GET    | `/materials?course_id=X`                 | Student page      | Materials indexed for one course |
| GET    | `/materials/download/{course_id}/{file}`  | Student page      | Download one material (read-only) |
| POST   | `/chat`                                    | Student widget    | `{question, course_id, mode}` → `{explanation, concepts, sources, source_type, used_llm, mode}` |
| GET    | `/search-materials?course_id=X&query=`      | Student widget (Search tab) | `{results: [{source, title, snippet, score}]}` — no LLM involved |
| GET    | `/important-topics?course_id=X`              | Student widget (Topics button, Quiz "Select Topic") | `{topics: [...], source_type}` — cached, regenerated when new material is indexed |
| POST   | `/quiz/generate`                                | Student widget (Quiz tab) | `{course_id, scope, topic?, num_questions, difficulty}` → `{questions: [{id, question, options[4], correct_index, explanation, source}], num_generated, scope, topic, difficulty}` |
| POST   | `/upload`                                     | Admin panel only | Manually index a file into a course |
| POST   | `/reset`                                       | Admin panel only | Wipe one course's index (`?course_id=X`) or all |

`mode` on `/chat` is one of `normal` (default) / `simple` / `exam`, and
`source_type` in the response is one of:

| `source_type`     | Meaning |
|--------------------|---------|
| `course_grounded`   | Answer generated from retrieved course material above the relevance threshold |
| `general_fallback`   | No sufficiently relevant course content found — answer is general knowledge, clearly labeled in the UI |
| `no_materials`        | Nothing is indexed for this course at all yet |
| `llm_offline`           | Ollama unreachable — showing the closest retrieved passage instead of a generated answer |

`POST /quiz/generate` returns one of these HTTP statuses on failure, matched to `rag.generate_quiz`'s internal `error` field:

| Status | `error` (internal) | Meaning |
|--------|---------------------|---------|
| `404`   | `no_materials`        | Nothing indexed for this course yet |
| `404`   | `no_relevant_content`  | `scope="topic"` but nothing relevant was retrieved for that topic |
| `503`   | `llm_offline`           | The `ollama_health_check()` ping failed — Ollama itself isn't reachable, zero generation attempted |
| `502`   | `generation_failed`      | Ollama IS reachable, but the retry/refill loop couldn't produce `num_questions` valid, distinct questions within its attempt budget |

## Notes for your report

- **Course isolation as an architectural property, not a filter.** Each
  course has its own `IndexFlatIP` FAISS index on disk. This is a
  deliberate trade-off worth discussing: it trades a small amount of
  storage/index-count overhead for a *structural* guarantee that queries
  can't leak across courses, versus a single global index with a metadata
  filter (which is simpler to manage but relies on filtering logic being
  correct every time).
- **Relevance gating.** `RELEVANCE_THRESHOLD` in `rag.py` (default `0.30`,
  cosine similarity) decides whether the top retrieved chunk is "relevant
  enough" to ground an answer. This is a real precision/recall trade-off
  worth a paragraph: too low, and the assistant will confidently answer
  off-topic questions using irrelevant course chunks; too high, and it'll
  punt to the general-knowledge fallback too often. The threshold is tuned
  for MiniLM cosine similarity specifically — swapping embedding models
  means re-tuning it.
- **Structured generation.** The prompt asks the LLM to emit `{explanation,
  concepts}` as JSON (`format: "json"` on the Ollama call, plus a
  regex/fence fallback parser). Small local models don't always comply
  perfectly, hence the multi-stage fallback in `parse_structured_answer`.
- **Quiz generation and validation.** Each generated question is validated
  independently (exactly 4 non-empty options, a `correct_index` in range,
  a source that's actually one of the retrieved documents) and dropped if
  malformed, rather than failing the whole quiz over one bad question —
  worth mentioning as a robustness pattern for structured LLM output at
  scale.
- **Quiz generation: one question at a time, with a health check to tell
  "offline" apart from "generation failed."** Earlier versions asked the
  LLM for several questions per call; this version generates and validates
  exactly ONE question per Ollama call, in a bounded refill loop
  (`generate_quiz` in `rag.py`):
  - **Every attempt targets a new "focus fact".** The pooled chunks are
    split into `QUIZ_CHUNK_CHAR_LIMIT`-sized slices, ordered round-robin
    across documents; attempt *k* uses slice *k* as the FIRST excerpt and
    tells the model to write the question about it. Retries therefore never
    resend the same context (the old rotating window cycled back to
    identical prompts after ~N attempts, so a deterministic small model kept
    emitting the same question and every retry was rejected as a duplicate).
    Retry temperature rises after consecutive rejections, a per-attempt seed
    is sent, rejected duplicates are fed back as "avoid", and the cited
    source is the focus excerpt's file. `generation_failed` logs attempts,
    timeouts, malformed and duplicate counts.
  - Each call gets a small window of context
    (`QUIZ_CHUNKS_PER_QUESTION` excerpts, `QUIZ_CHUNK_CHAR_LIMIT` characters
    each) — tiny and roughly constant per call regardless of whether the
    student asked for 5, 10, or 15 questions overall.
  - A **quiz-specific timeout** (`QUIZ_OLLAMA_TIMEOUT`, 25s) is used
    instead of the shared 60s default — a single MCQ with a 3-chunk
    context should finish well inside that, so a call that doesn't is
    cheaply abandoned and retried with fresh context, rather than tying up
    the request for a full 60s. The 60s default is untouched for chat and
    Important Topics — `call_ollama` takes `timeout`/`keep_alive` as
    optional parameters that only quiz generation actually passes.
  - `keep_alive="10m"` is sent on quiz calls so Ollama keeps the model
    loaded across the many rapid single-question calls one quiz needs,
    instead of risking a reload mid-quiz.
  - **A proper Ollama health check** (`ollama_health_check()`, a cheap
    `GET /api/tags` — no model load) runs once, before any generation is
    attempted. This is what separates two genuinely different failure
    modes that used to collapse into the same `llm_offline` error: if the
    health check fails, it's `llm_offline` immediately, with zero
    generation attempts made; if the health check *passes* but the retry
    loop still can't produce enough valid, distinct questions, that's
    `generation_failed` — Ollama is up, generation itself is what didn't
    work out. A per-call `RequestException` *during* the retry loop
    (after the health check already passed) is treated as one failed
    attempt, not as new evidence that Ollama is offline.
  - **Duplicate prevention** compares each new candidate's *content
    words* (common/template words stripped) against every previously
    accepted question in the same quiz, using Jaccard overlap
    (`QUIZ_DUPLICATE_JACCARD_THRESHOLD`). This deliberately avoids raw
    character-level similarity: two genuinely different questions that
    share a sentence template (e.g. "...the **input** layer..." vs
    "...the **output** layer...") can score a *higher* character-level
    ratio than a true reworded duplicate does, since character similarity
    is dominated by shared boilerplate rather than the words that actually
    distinguish the questions — I hit exactly this false-positive while
    testing and switched approaches because of it. The most recently
    accepted questions are also echoed into the next prompt as a "don't
    repeat these" hint, as a proactive complement to the after-the-fact
    check.
  - **Automatic refill, bounded.** The loop keeps requesting new questions
    (skipping duplicates/malformed output/failed calls) until exactly
    `num_questions` valid, distinct questions are accepted, or a hard cap
    (`num_questions * QUIZ_MAX_ATTEMPTS_MULTIPLIER`) is hit.
  - **Never a silent partial success.** If the attempt cap is hit first,
    the result is `generation_failed` with zero questions — never a
    "successful" response with fewer questions than requested. A course
    project demoing this is worth a sentence on why: silently returning 3
    of 5 requested questions would be a worse experience (and a subtler
    bug to notice) than a clear failure the UI can react to.
  "Entire Course" scope samples chunks round-robin across every document
  (`sample_broad_chunks`) so a long document can't dominate the question
  set; "Select Topic" scope reuses the same relevance-scored retrieval as
  Ask.
- **Anti-copying / anti-hallucination instructions.** The prompt explicitly
  forbids verbatim copying and unsupported claims, and encourages analogies
  only where they genuinely help. This is inherently a soft constraint with
  a local 3B model — worth discussing as a limitation, and a good place to
  mention what a larger/hosted model or an added verification pass could
  improve.
- **Important Topics caching.** Computed once per course from one
  representative chunk per document (not the whole course), cached to
  `data/index/<course_id>/important_topics.json`, and invalidated by
  comparing chunk counts — a cheap proxy for "has new material been added"
  without needing a proper content hash.
- **Grounded UI feedback.** The highlight/dim behavior on the course page
  is driven directly by the `sources` field returned from `/chat` — it's a
  concrete, visible demonstration of retrieval grounding, not just a
  citation printed in text.
- **Why a local LLM**: keeps the whole pipeline free and offline-capable.
  Swapping in a hosted LLM API only requires changing `rag.py`.
- **Extending it**: real deployment into a college portal would replace
  `faculty_watch.py`'s folder-polling with a webhook from the portal's file
  storage, add auth per course/role, and likely move each course's FAISS
  index into a proper vector DB for scale — good "future work" material.

## Troubleshooting

- **"Backend not reachable"** → make sure `uvicorn` is running on port 8000.
- **Materials table is empty** → make sure `faculty_watch.py` is running and
  has had a few seconds to index `data/faculty_uploads/<course_id>/`.
- **Answers show a raw passage instead of an explanation + concepts** →
  Ollama isn't running / model not pulled (`ollama serve`, `ollama pull llama3.2:3b`).
- **Answer occasionally has empty "concepts"** → small local models don't
  always follow the JSON format perfectly; this is expected sometimes and
  handled gracefully rather than crashing.
- **Slow first request per course** → the embedding model downloads once
  (~90MB) the first time it's used, and needs internet access for that.
- **Everything gets answered as "general knowledge" even for on-topic
  questions** → `RELEVANCE_THRESHOLD` in `rag.py` may be too high for your
  embedding model/content — try lowering it (e.g. to `0.2`) and re-test.
- **Off-topic questions get answered from course material anyway** →
  the opposite problem; raise `RELEVANCE_THRESHOLD`.
- **"Important Topics" just shows document filenames** → that's the
  `document_titles_fallback` path — Ollama wasn't reachable when it was
  generated. Once Ollama is running, click the button again (or hit
  `/important-topics?course_id=X&refresh=true`) to regenerate properly.
- **Search tab shows results but Ask tab says "general knowledge"** →
  expected and correct: Search has no relevance gate (it's meant for
  browsing/discovery), Ask does (it's meant for trustworthy answers).
- **Quiz generation returns a 503** → the `ollama_health_check()` ping to
  Ollama's `/api/tags` failed, meaning Ollama itself isn't reachable
  (not just slow). Unlike `/chat`, quiz generation has no extractive/
  general-knowledge fallback — a quiz needs the LLM to actually run.
- **Quiz generation returns a 502 (`generation_failed`)** → Ollama IS
  reachable (health check passed) but the retry/refill loop hit its
  attempt cap (`num_questions * QUIZ_MAX_ATTEMPTS_MULTIPLIER`) without
  producing enough valid, distinct questions — e.g. the model keeps
  returning malformed JSON, or a narrow topic genuinely doesn't support
  as many distinct questions as requested. Try a smaller `num_questions`
  or a broader scope ("Entire Course" instead of a narrow topic).
- **Quiz generation is slow but doesn't time out** → each call is
  deliberately small (1 question, 3 chunks, ~280 chars each, a small fixed
  token budget, a 25s quiz-specific timeout) and `keep_alive` keeps the
  model loaded between calls, so this should stay fast under normal local
  hardware. A 15-question quiz makes at least 15 sequential calls by
  design (one per question) — that's expected, not a bug, even though it
  may take noticeably longer than a 5-question quiz overall.
- **Quiz never comes back with fewer questions than you asked for** →
  that's intentional. A shortfall after the retry budget is exhausted is
  reported as `generation_failed`, not returned as a smaller "successful"
  quiz — see the API reference table above.
- **"Select Topic" shows no topics** → Important Topics hasn't been
  generated for this course yet (or Ollama was offline when it last tried).
  Click "Important Topics" on the Ask tab first, or use "Entire Course" scope.
