import json
import math
import os
import subprocess
import sys
import threading
import uuid

from job_store import (
    create_job, update_job, get_job,
    create_job_group, update_job_group, get_job_group, list_child_jobs,
)
from sqs_client import send_job_message
from stats_aggregator import merge_stats_csvs

RESULTS_DIR = "load_test_results"
os.makedirs(RESULTS_DIR, exist_ok=True)

USE_SQS = os.environ.get("USE_SQS", "false").lower() == "true"

# A single worker has been validated comfortably up to this many concurrent
# users. Requests above this get split into multiple child jobs so several
# worker pods can process them in parallel.
SPLIT_THRESHOLD = 50
# app.MAX_USERS (1000) / SPLIT_THRESHOLD (50) = 20: the fewest children that
# keeps every child at or under the threshold for any accepted request.
MAX_CHILD_JOBS = 20


def _run_api_job(job_id, target_url, target_path, cases, users, spawn_rate, duration_seconds):
    job_dir = os.path.join(RESULTS_DIR, job_id)
    os.makedirs(job_dir, exist_ok=True)

    cases_file = os.path.join(job_dir, "cases.json")
    with open(cases_file, "w") as f:
        json.dump(cases, f)

    csv_prefix = os.path.join(job_dir, "result")

    env = os.environ.copy()
    env["LOCUST_CASES_FILE"] = cases_file
    env["LOCUST_TARGET_PATH"] = target_path

    locustfile_path = os.path.join(os.path.dirname(__file__), "locust_tests", "dynamic_locustfile.py")
    _run_locust(job_id, locustfile_path, env, target_url, users, spawn_rate, duration_seconds, csv_prefix)


def _run_website_job(job_id, target_url, paths, users, spawn_rate, duration_seconds):
    job_dir = os.path.join(RESULTS_DIR, job_id)
    os.makedirs(job_dir, exist_ok=True)

    paths_file = os.path.join(job_dir, "paths.json")
    with open(paths_file, "w") as f:
        json.dump(paths, f)

    csv_prefix = os.path.join(job_dir, "result")

    env = os.environ.copy()
    env["LOCUST_PATHS_FILE"] = paths_file

    locustfile_path = os.path.join(os.path.dirname(__file__), "locust_tests", "website_locustfile.py")
    _run_locust(job_id, locustfile_path, env, target_url, users, spawn_rate, duration_seconds, csv_prefix)


def _run_locust(job_id, locustfile_path, env, target_url, users, spawn_rate, duration_seconds, csv_prefix):
    if not os.path.exists(locustfile_path):
        update_job(job_id, status="failed", error=f"locustfile not found at {locustfile_path}")
        return

    cmd = [
        sys.executable, "-m", "locust",
        "-f", locustfile_path,
        "--headless",
        "-u", str(users),
        "-r", str(spawn_rate),
        "-t", f"{duration_seconds}s",
        "--host", target_url,
        "--csv", csv_prefix,
    ]

    update_job(job_id, status="running")

    try:
        proc = subprocess.run(
            cmd, env=env, capture_output=True, text=True,
            timeout=duration_seconds + 60,
        )
        stats_csv = None
        stats_file = f"{csv_prefix}_stats.csv"
        if os.path.exists(stats_file):
            with open(stats_file) as f:
                stats_csv = f.read()

        update_job(
            job_id,
            status="completed",
            stdout=proc.stdout[-3000:],
            stderr=proc.stderr[-3000:],
            stats_csv=stats_csv,
        )
    except subprocess.TimeoutExpired:
        update_job(job_id, status="timeout")
    except Exception as e:
        update_job(job_id, status="failed", error=str(e))


def _dispatch_single(job_type, job_id, target_url, users, spawn_rate, duration_seconds,
                      target_path=None, cases=None, paths=None):
    """Runs one job locally (thread) or sends it to SQS, depending on USE_SQS."""
    if USE_SQS:
        payload = {
            "job_id": job_id, "job_type": job_type, "target_url": target_url,
            "users": users, "spawn_rate": spawn_rate, "duration_seconds": duration_seconds,
        }
        if job_type == "api":
            payload["target_path"] = target_path
            payload["cases"] = cases
        else:
            payload["paths"] = paths
        send_job_message(payload)
    else:
        target = _run_api_job if job_type == "api" else _run_website_job
        args = (
            (job_id, target_url, target_path, cases, users, spawn_rate, duration_seconds)
            if job_type == "api"
            else (job_id, target_url, paths, users, spawn_rate, duration_seconds)
        )
        threading.Thread(target=target, args=args, daemon=True).start()


def _split_users(total_users):
    """Splits a large user count into a list of per-child user counts,
    each no larger than SPLIT_THRESHOLD, capped at MAX_CHILD_JOBS children."""
    child_count = min(MAX_CHILD_JOBS, math.ceil(total_users / SPLIT_THRESHOLD))
    base = total_users // child_count
    remainder = total_users % child_count
    return [base + (1 if i < remainder else 0) for i in range(child_count) if base + (1 if i < remainder else 0) > 0]


def start_load_test(target_url, target_path, cases, users=5, spawn_rate=1, duration_seconds=30):
    """Starts a single API load test job. For large user counts, transparently
    splits into multiple child jobs distributed across workers — see
    start_split_load_test. Returns (id, is_group)."""
    if users > SPLIT_THRESHOLD:
        group_id = start_split_load_test(target_url, target_path, cases, users, spawn_rate, duration_seconds)
        return group_id, True

    job_id = str(uuid.uuid4())
    create_job(job_id, target_url, users, spawn_rate, duration_seconds)
    _dispatch_single("api", job_id, target_url, users, spawn_rate, duration_seconds,
                      target_path=target_path, cases=cases)
    return job_id, False


def start_website_load_test(target_url, paths, users=5, spawn_rate=1, duration_seconds=30):
    if users > SPLIT_THRESHOLD:
        group_id = start_split_website_load_test(target_url, paths, users, spawn_rate, duration_seconds)
        return group_id, True

    job_id = str(uuid.uuid4())
    create_job(job_id, target_url, users, spawn_rate, duration_seconds)
    _dispatch_single("website", job_id, target_url, users, spawn_rate, duration_seconds, paths=paths)
    return job_id, False


def start_split_load_test(target_url, target_path, cases, users, spawn_rate, duration_seconds):
    per_child_users = _split_users(users)
    group_id = str(uuid.uuid4())
    create_job_group(group_id, target_url, "api", users, spawn_rate, duration_seconds, len(per_child_users))

    for child_users in per_child_users:
        job_id = str(uuid.uuid4())
        create_job(job_id, target_url, child_users, spawn_rate, duration_seconds, group_id=group_id)
        _dispatch_single("api", job_id, target_url, child_users, spawn_rate, duration_seconds,
                          target_path=target_path, cases=cases)

    return group_id


def start_split_website_load_test(target_url, paths, users, spawn_rate, duration_seconds):
    per_child_users = _split_users(users)
    group_id = str(uuid.uuid4())
    create_job_group(group_id, target_url, "website", users, spawn_rate, duration_seconds, len(per_child_users))

    for child_users in per_child_users:
        job_id = str(uuid.uuid4())
        create_job(job_id, target_url, child_users, spawn_rate, duration_seconds, group_id=group_id)
        _dispatch_single("website", job_id, target_url, child_users, spawn_rate, duration_seconds, paths=paths)

    return group_id


def get_job_status(job_id):
    return get_job(job_id)


def get_group_status(group_id):
    """Returns the combined status of a split job group. Aggregates results
    once every child job has finished; otherwise reports the group's overall
    progress state."""
    group = get_job_group(group_id)
    if group is None:
        return None

    children = list_child_jobs(group_id)
    statuses = [c["status"] for c in children]

    if any(s == "failed" for s in statuses):
        overall = "failed"
    elif any(s == "timeout" for s in statuses):
        overall = "timeout"
    elif all(s == "completed" for s in statuses):
        overall = "completed"
    elif any(s == "running" for s in statuses):
        overall = "running"
    else:
        overall = "queued"

    result = dict(group)
    result["child_jobs"] = children
    result["status"] = overall

    if overall == "completed" and not group.get("aggregated_stats_csv"):
        stats_list = [c["stats_csv"] for c in children if c.get("stats_csv")]
        merged = merge_stats_csvs(stats_list) if stats_list else None
        update_job_group(group_id, status="completed", aggregated_stats_csv=merged)
        result["aggregated_stats_csv"] = merged
    elif overall == "completed":
        result["aggregated_stats_csv"] = group.get("aggregated_stats_csv")

    return result