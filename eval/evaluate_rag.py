"""
evaluate_rag.py -- measures the RETRIEVAL and LATENCY side of CourseMind AI on
YOUR labelled questions, against the REAL running system (real MiniLM
embeddings, real FAISS index, real Ollama).

Run from the backend/ folder after the PDFs are indexed:
    python ../eval/evaluate_rag.py --gold ../eval/gold_questions.csv --k 1 3 4 5 --chat

gold_questions.csv columns:
    id, course_id, question, relevant_sources, gold_answer
  relevant_sources: one or more PDF filenames separated by '|' (document-level relevance)

Outputs (written next to the gold file):
    retrieval_results.csv      per-question ranks, P@K, R@K, RR, latency
    answers_for_manual_scoring.csv   (with --chat) generated answers + empty
                               faithfulness / relevance columns for you to score by hand
Prints a summary table you can paste into the report (Tables 5.2-5.4).
Nothing here is invented: every number comes from running the system.
"""
import argparse, csv, statistics, sys, time
from pathlib import Path

sys.path.insert(0, str(Path.cwd()))


def precision_at_k(ranked_sources, relevant, k):
    top = ranked_sources[:k]
    return sum(1 for s in top if s in relevant) / k


def recall_at_k(ranked_sources, relevant, k):
    # document-level recall: fraction of the relevant documents found in the top-k
    found = {s for s in ranked_sources[:k] if s in relevant}
    return len(found) / len(relevant)


def reciprocal_rank(ranked_sources, relevant):
    for i, s in enumerate(ranked_sources, start=1):
        if s in relevant:
            return 1.0 / i
    return 0.0


def percentile(values, p):
    v = sorted(values)
    if not v:
        return float("nan")
    idx = min(len(v) - 1, max(0, round(p / 100 * (len(v) - 1))))
    return v[idx]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gold", required=True)
    ap.add_argument("--k", type=int, nargs="+", default=[1, 3, 5])
    ap.add_argument("--chat", action="store_true", help="also call answer_question() (needs Ollama) for latency + manual scoring sheet")
    args = ap.parse_args()

    from ingest import search          # real embedder + FAISS
    rows = list(csv.DictReader(open(args.gold, newline="", encoding="utf-8")))
    kmax = max(args.k)
    out, lat_ret = [], []
    for r in rows:
        rel = {s.strip() for s in r["relevant_sources"].split("|") if s.strip()}
        t0 = time.perf_counter()
        hits = search(r["course_id"], r["question"], top_k=kmax)
        dt = (time.perf_counter() - t0) * 1000
        lat_ret.append(dt)
        ranked = [h["source"] for h in hits]
        rec = {"id": r["id"], "course_id": r["course_id"], "retrieval_ms": round(dt, 1),
               "top_sources": " > ".join(ranked), "RR": round(reciprocal_rank(ranked, rel), 4)}
        for k in args.k:
            rec[f"P@{k}"] = round(precision_at_k(ranked, rel, k), 4)
            rec[f"R@{k}"] = round(recall_at_k(ranked, rel, k), 4)
        out.append(rec)

    base = Path(args.gold).parent
    with open(base / "retrieval_results.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0].keys())); w.writeheader(); w.writerows(out)

    print(f"\nQuestions: {len(rows)}")
    for k in args.k:
        print(f"  Precision@{k}: {statistics.mean(o[f'P@{k}'] for o in out):.3f}   Recall@{k}: {statistics.mean(o[f'R@{k}'] for o in out):.3f}")
    print(f"  MRR: {statistics.mean(o['RR'] for o in out):.3f}")
    print(f"  Retrieval latency ms  mean {statistics.mean(lat_ret):.1f}  median {statistics.median(lat_ret):.1f}  p95 {percentile(lat_ret,95):.1f}")

    if args.chat:
        from rag import answer_question
        sheet, lat = [], []
        for r in rows:
            t0 = time.perf_counter()
            res = answer_question(r["question"], r["course_id"], "normal")
            dt = time.perf_counter() - t0
            lat.append(dt)
            sheet.append({"id": r["id"], "question": r["question"], "gold_answer": r["gold_answer"],
                          "system_answer": res["explanation"], "source_type": res["source_type"],
                          "cited_sources": "|".join(res["sources"]), "end_to_end_s": round(dt, 2),
                          "claims_total": "", "claims_supported_by_context": "", "answer_relevance_1to5": ""})
        with open(base / "answers_for_manual_scoring.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(sheet[0].keys())); w.writeheader(); w.writerows(sheet)
        print(f"  End-to-end /chat latency s  mean {statistics.mean(lat):.2f}  median {statistics.median(lat):.2f}  p95 {percentile(lat,95):.2f}")
        print("  -> Fill the 3 blank columns in answers_for_manual_scoring.csv, then:")
        print("     Faithfulness = sum(claims_supported_by_context)/sum(claims_total);  Answer relevance = mean(answer_relevance_1to5)")


if __name__ == "__main__":
    main()
