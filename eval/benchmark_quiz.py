import requests
import csv
import time
import argparse
import os
from collections import defaultdict
from statistics import mean

# ==========================================
# CONFIGURATION
# ==========================================

API_URL = "http://127.0.0.1:8080/quiz/generate"

COURSE_ID = "ISWE411L"
TOPIC = "Neural Networks"

RUNS_PER_CONFIG = 5
DIFFICULTY = "medium"

LOG_FILE = "quiz_benchmark_backend.log"

RUNS_CSV = "quiz_benchmark_runs.csv"
SUMMARY_CSV = "quiz_benchmark_results.csv"


# ==========================================
# BENCHMARK CONFIGURATIONS
# ==========================================

CONFIGURATIONS = [
    {"scope": "entire", "num_questions": 5},
    {"scope": "entire", "num_questions": 10},
    {"scope": "entire", "num_questions": 15},

    {"scope": "topic", "num_questions": 5},
    {"scope": "topic", "num_questions": 10},
    {"scope": "topic", "num_questions": 15},
]


# ==========================================
# OLLAMA CALL COUNTER
# ==========================================

def count_ollama_calls(log_file, start_position):

    if not os.path.exists(log_file):
        return 0

    with open(log_file, "r", encoding="utf-8", errors="ignore") as file:

        file.seek(start_position)

        content = file.read()

    return content.count("OLLAMA_CALL:")


# ==========================================
# GET LOG FILE POSITION
# ==========================================

def get_log_position(log_file):

    if not os.path.exists(log_file):
        return 0

    return os.path.getsize(log_file)


# ==========================================
# RUN SINGLE BENCHMARK
# ==========================================

def run_benchmark(config, run_number, log_file):

    scope = config["scope"]
    num_questions = config["num_questions"]

    payload = {
        "course_id": COURSE_ID,
        "scope": scope,
        "num_questions": num_questions,
        "difficulty": DIFFICULTY
    }

    if scope == "topic":
        payload["topic"] = TOPIC

    print("\n--------------------------------------")
    print(f"Configuration: {scope.upper()}")
    print(f"Questions: {num_questions}")
    print(f"Run: {run_number}/{RUNS_PER_CONFIG}")
    print("--------------------------------------")

    log_start = get_log_position(log_file)

    start_time = time.perf_counter()

    try:

        response = requests.post(
            API_URL,
            json=payload,
            timeout=600
        )

        completion_time = time.perf_counter() - start_time

        ollama_calls = count_ollama_calls(
            log_file,
            log_start
        )

        success = response.status_code == 200

        error_message = ""

        if not success:
            error_message = response.text[:500]

        print(f"HTTP Status: {response.status_code}")
        print(f"Success: {success}")
        print(f"Completion Time: {completion_time:.2f} seconds")
        print(f"Ollama Calls: {ollama_calls}")

        return {
            "scope": scope,
            "topic": TOPIC if scope == "topic" else "N/A",
            "num_questions": num_questions,
            "run": run_number,
            "http_status": response.status_code,
            "success": success,
            "completion_time_seconds": round(completion_time, 2),
            "ollama_calls": ollama_calls,
            "error": error_message
        }

    except requests.exceptions.RequestException as error:

        completion_time = time.perf_counter() - start_time

        ollama_calls = count_ollama_calls(
            log_file,
            log_start
        )

        print(f"Request failed: {error}")

        return {
            "scope": scope,
            "topic": TOPIC if scope == "topic" else "N/A",
            "num_questions": num_questions,
            "run": run_number,
            "http_status": "ERROR",
            "success": False,
            "completion_time_seconds": round(completion_time, 2),
            "ollama_calls": ollama_calls,
            "error": str(error)
        }


# ==========================================
# SAVE INDIVIDUAL RUN RESULTS
# ==========================================

def save_run_results(results):

    if not results:
        return

    with open(RUNS_CSV, "w", newline="", encoding="utf-8") as file:

        writer = csv.DictWriter(
            file,
            fieldnames=results[0].keys()
        )

        writer.writeheader()
        writer.writerows(results)

    print(f"\nIndividual results saved: {RUNS_CSV}")


# ==========================================
# GENERATE SUMMARY
# ==========================================

def generate_summary(results):

    grouped = defaultdict(list)

    for result in results:

        key = (
            result["scope"],
            result["num_questions"]
        )

        grouped[key].append(result)

    summary = []

    for (scope, num_questions), records in grouped.items():

        successful = [
            r for r in records if r["success"]
        ]

        times = [
            r["completion_time_seconds"]
            for r in successful
        ]

        calls = [
            r["ollama_calls"]
            for r in records
        ]

        summary.append({
            "scope": scope,
            "topic": TOPIC if scope == "topic" else "N/A",
            "num_questions": num_questions,
            "total_runs": len(records),
            "successful_runs": f"{len(successful)}/{len(records)}",
            "mean_completion_time_seconds": (
                round(mean(times), 2) if times else "N/A"
            ),
            "mean_ollama_calls": (
                round(mean(calls), 2) if calls else "N/A"
            )
        })

    with open(SUMMARY_CSV, "w", newline="", encoding="utf-8") as file:

        writer = csv.DictWriter(
            file,
            fieldnames=summary[0].keys()
        )

        writer.writeheader()
        writer.writerows(summary)

    print(f"Summary saved: {SUMMARY_CSV}")

    print("\n========== BENCHMARK SUMMARY ==========")

    for row in summary:
        print(row)


# ==========================================
# MAIN
# ==========================================

def main():

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--log",
        default=LOG_FILE,
        help="Backend Ollama logging file"
    )

    args = parser.parse_args()

    log_file = args.log

    all_results = []

    print("\n======================================")
    print(" COURSEMIND AI - QUIZ BENCHMARK")
    print("======================================")

    print(f"Course ID: {COURSE_ID}")
    print(f"Topic: {TOPIC}")
    print(f"Runs per configuration: {RUNS_PER_CONFIG}")
    print(f"Difficulty: {DIFFICULTY}")

    print("\nTotal configurations:", len(CONFIGURATIONS))
    print("Expected API requests:", len(CONFIGURATIONS) * RUNS_PER_CONFIG)

    for config in CONFIGURATIONS:

        for run_number in range(1, RUNS_PER_CONFIG + 1):

            result = run_benchmark(
                config,
                run_number,
                log_file
            )

            all_results.append(result)

            save_run_results(all_results)

            # Small pause between requests
            time.sleep(2)

    generate_summary(all_results)

    print("\n======================================")
    print(" BENCHMARK COMPLETED")
    print("======================================")


if __name__ == "__main__":
    main()