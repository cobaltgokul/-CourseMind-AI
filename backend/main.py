"""
main.py
-------
FastAPI server for the multi-course RAG assistant.

Student-facing (used by the widget / course page):
    GET  /courses                          -> list of {id, name, faculty}
    GET  /materials?course_id=X             -> materials for one course (view/download list)
    GET  /materials/download/{course}/{file} -> download a specific material (read-only)
    POST /chat                                -> {question, course_id, mode} -> explanation +
                                                   important concepts + sources, scoped to that course,
                                                   with a clearly-labeled general fallback when nothing
                                                   relevant is found
    GET  /search-materials?course_id=X&query= -> direct material search: exact source + snippet,
                                                   no LLM involved
    GET  /important-topics?course_id=X         -> course-level "Important Topics" summary (cached)
    POST /quiz/generate                          -> {course_id, scope, topic?, num_questions, difficulty}
                                                     -> MCQs with 4 options, explanation, source PDF

Faculty/admin-facing (NOT called by the student widget):
    POST /upload   -> manually index a document into a course (fallback to faculty_watch.py)
    POST /reset    -> wipe one course's index, or everything

The primary way documents get indexed is faculty_watch.py, which watches
data/faculty_uploads/<course_id>/ and indexes new files automatically.

Run with:
    uvicorn main:app --reload --port 8000
"""

from pathlib import Path
import shutil
from typing import Optional

from fastapi import FastAPI, UploadFile, File, HTTPException, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from ingest import (
    add_document_to_index,
    list_sources,
    list_courses,
    reset_index,
    UPLOAD_DIR,
    FACULTY_DIR,
)
from rag import (
    answer_question,
    search_materials,
    get_important_topics,
    generate_quiz,
    VALID_MODES,
    VALID_QUIZ_COUNTS,
    VALID_DIFFICULTIES,
)

app = FastAPI(title="Multi-Course RAG Assistant")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

ALLOWED_EXTENSIONS = {".pdf", ".txt", ".md"}


class ChatRequest(BaseModel):
    question: str
    course_id: str
    mode: str = Field(default="normal", description="normal | simple | exam")


class QuizRequest(BaseModel):
    course_id: str
    scope: str = Field(description="entire | topic")
    topic: Optional[str] = Field(default=None, description="required when scope == 'topic'; one of the course's Important Topics")
    num_questions: int = Field(default=5, description="5 | 10 | 15")
    difficulty: str = Field(default="medium", description="easy | medium | hard")


@app.get("/")
def root():
    return {"status": "ok", "message": "Multi-course RAG Assistant API is running."}


# ------------------------------------------------------------ student-facing --

@app.get("/courses")
def get_courses():
    return {"courses": list_courses()}


@app.get("/materials")
def get_materials(course_id: str):
    return {"course_id": course_id, "materials": list_sources(course_id)}


@app.get("/materials/download/{course_id}/{filename}")
def download_material(course_id: str, filename: str):
    filepath = FACULTY_DIR / course_id / filename
    if not filepath.exists():
        # also check the admin manual-upload staging area as a fallback
        filepath = UPLOAD_DIR / filename
    if not filepath.exists():
        raise HTTPException(status_code=404, detail="Material not found.")
    return FileResponse(str(filepath), filename=filename)


@app.post("/chat")
def chat(req: ChatRequest):
    if not req.question or not req.question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty.")
    if not req.course_id or not req.course_id.strip():
        raise HTTPException(status_code=400, detail="course_id is required.")
    mode = req.mode if req.mode in VALID_MODES else "normal"
    result = answer_question(req.question, req.course_id, mode)
    return result


@app.get("/search-materials")
def search_materials_endpoint(course_id: str, query: str, top_k: int = 5):
    if not query or not query.strip():
        raise HTTPException(status_code=400, detail="query cannot be empty.")
    results = search_materials(course_id, query, top_k=top_k)
    return {"course_id": course_id, "query": query, "results": results}


@app.get("/important-topics")
def important_topics_endpoint(course_id: str, refresh: bool = False):
    result = get_important_topics(course_id, force_refresh=refresh)
    return {"course_id": course_id, **result}


@app.post("/quiz/generate")
def quiz_generate_endpoint(req: QuizRequest):
    if req.scope not in ("entire", "topic"):
        raise HTTPException(status_code=400, detail="scope must be 'entire' or 'topic'.")
    if req.scope == "topic" and not (req.topic and req.topic.strip()):
        raise HTTPException(status_code=400, detail="topic is required when scope is 'topic'.")
    if req.num_questions not in VALID_QUIZ_COUNTS:
        raise HTTPException(status_code=400, detail=f"num_questions must be one of {sorted(VALID_QUIZ_COUNTS)}.")
    if req.difficulty not in VALID_DIFFICULTIES:
        raise HTTPException(status_code=400, detail=f"difficulty must be one of {sorted(VALID_DIFFICULTIES)}.")

    result = generate_quiz(req.course_id, req.scope, req.topic, req.num_questions, req.difficulty)

    if result["error"] == "no_materials":
        raise HTTPException(status_code=404, detail="No materials are indexed for this course yet.")
    if result["error"] == "llm_offline":
        raise HTTPException(status_code=503, detail="The local language model isn't reachable right now, so a quiz can't be generated.")
    if result["error"] == "generation_failed":
        raise HTTPException(status_code=502, detail="Couldn't generate a valid quiz from this course's materials. Try again.")
    if result["error"] == "no_relevant_content":
        raise HTTPException(status_code=404, detail="No relevant material was found for that topic.")

    return result


# --------------------------------------------------------------- admin-only --

@app.post("/upload")
async def upload_document(
    file: UploadFile = File(...),
    course_id: str = Form(...),
    course_name: str = Form(None),
):
    suffix = Path(file.filename).suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{suffix}'. Allowed: {sorted(ALLOWED_EXTENSIONS)}",
        )

    dest_path = UPLOAD_DIR / file.filename
    with open(dest_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    try:
        num_chunks = add_document_to_index(
            dest_path, source_name=file.filename, course_id=course_id, course_name=course_name
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to process document: {e}")

    return {
        "filename": file.filename,
        "course_id": course_id,
        "chunks_indexed": num_chunks,
        "message": f"'{file.filename}' indexed into '{course_id}' with {num_chunks} chunks.",
    }


@app.post("/reset")
def reset(course_id: str = None):
    reset_index(course_id)
    return {"message": f"Index cleared for {'course ' + course_id if course_id else 'ALL courses'}."}
