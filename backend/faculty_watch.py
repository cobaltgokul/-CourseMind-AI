"""
faculty_watch.py
-----------------
Watches data/faculty_uploads/<course_id>/ subfolders for new course documents
and automatically indexes them into that course's RAG index. No manual
upload step, no student-facing (or faculty-facing) UI required.

Folder layout faculty (or, for now, you) drop files into:

    data/faculty_uploads/
      ISWE411L/            <- course_id (matches courses.json + widget config)
        lecture1.pdf
        lecture2.pdf
      MGT2001/
        syllabus.pdf
        ...

In a real deployment this loop would be replaced by a webhook from the
college portal ("new file uploaded to course X") — this polling approach is
a stand-in that behaves the same way from the RAG system's point of view.

Run alongside the API server:
    python3 faculty_watch.py
"""

import json
import time
from pathlib import Path

from ingest import add_document_to_index, FACULTY_DIR, load_courses

PROCESSED_LOG = Path(__file__).parent / "data" / "faculty_processed.json"
POLL_SECONDS = 5
ALLOWED_EXTENSIONS = {".pdf", ".txt", ".md"}

FACULTY_DIR.mkdir(parents=True, exist_ok=True)


def load_processed() -> set:
    if PROCESSED_LOG.exists():
        return set(json.loads(PROCESSED_LOG.read_text()))
    return set()


def save_processed(processed: set):
    PROCESSED_LOG.write_text(json.dumps(sorted(processed)))


def scan_and_index():
    processed = load_processed()
    found_new = False
    courses = load_courses()

    for course_dir in FACULTY_DIR.glob("*"):
        if not course_dir.is_dir():
            continue
        course_id = course_dir.name
        course_name = courses.get(course_id, {}).get("name", course_id)

        for filepath in course_dir.glob("*"):
            if filepath.suffix.lower() not in ALLOWED_EXTENSIONS:
                continue
            key = f"{course_id}/{filepath.name}:{filepath.stat().st_mtime}"
            if key in processed:
                continue

            print(f"[faculty_watch] New/updated file in '{course_id}': {filepath.name}")
            try:
                num_chunks = add_document_to_index(
                    filepath,
                    source_name=filepath.name,
                    course_id=course_id,
                    course_name=course_name,
                )
                print(f"[faculty_watch] Indexed '{filepath.name}' into course '{course_id}' "
                      f"({num_chunks} chunks).")
            except Exception as e:
                print(f"[faculty_watch] ERROR indexing '{filepath.name}' ({course_id}): {e}")
                continue

            processed.add(key)
            found_new = True

    if found_new:
        save_processed(processed)


def main():
    print(f"[faculty_watch] Watching {FACULTY_DIR}/<course_id>/ for new course materials...")
    print("[faculty_watch] Each subfolder name is treated as a course_id. "
          "Drop PDF/TXT/MD files in and they're indexed automatically.")
    while True:
        scan_and_index()
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
