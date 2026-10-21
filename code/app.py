from urllib.parse import urlparse
from flask import Flask, request, jsonify
from flask_cors import CORS
from werkzeug.exceptions import HTTPException
from analysis.sanity_check import sanity_check
from analysis.type_detector import detect_type, try_find_sitemap, extract_paths_from_sitemap
from analysis.edge_cases import generate_edge_cases
from load_test_runner import start_load_test, start_website_load_test, get_job_status, get_group_status
from testkit.safety import check_url, UnsafeTarget
from job_store import init_db, list_jobs, list_job_groups

app = Flask(__name__)
CORS(app)
init_db()

MAX_USERS = 1000
MAX_DURATION_SECONDS = 300
MAX_SPAWN_RATE = 20


@app.errorhandler(Exception)
def handle_uncaught_exception(e):
    # Let Flask's own HTTP errors (404, 405, ...) keep their status code.
    if isinstance(e, HTTPException):
        return jsonify({"error": e.name.lower().replace(" ", "_")}), e.code
    app.logger.exception("Unhandled exception")
    return jsonify({"error": "internal_server_error"}), 500


@app.errorhandler(404)
def handle_404(e):
    return jsonify({"error": "not_found"}), 404


@app.errorhandler(405)
def handle_405(e):
    return jsonify({"error": "method_not_allowed"}), 405


@app.route("/api/health", methods=["GET"])
def health_endpoint():
    return jsonify({"status": "ok"}), 200


@app.route("/health", methods=["GET"])
def health_alias_endpoint():
    return jsonify({"status": "ok"}), 200


@app.route("/api/sanity-check", methods=["POST"])
def sanity_check_endpoint():
    data = request.get_json(silent=True) or {}
    url = (data.get("url") or "").strip()
    if not url:
        return jsonify({"error": "url is required"}), 400
    result = sanity_check(url)
    status_code = 200 if result["valid_format"] else 400
    return jsonify(result), status_code


@app.route("/api/analyze", methods=["POST"])
def analyze_endpoint():
    data = request.get_json(silent=True) or {}
    url = (data.get("url") or "").strip()
    if not url:
        return jsonify({"error": "url is required"}), 400

    sanity = sanity_check(url)
    if not sanity["valid_format"] or not sanity.get("reachable"):
        return jsonify({"sanity": sanity}), 400

    type_result = detect_type(sanity["final_url"], sanity["headers"])
    response = {"sanity": sanity, "type_detection": type_result}

    if type_result["classification"] == "website":
        response["sitemap"] = try_find_sitemap(sanity["final_url"])

    return jsonify(response), 200


@app.route("/api/generate-edge-cases", methods=["POST"])
def generate_edge_cases_endpoint():
    data = request.get_json(silent=True) or {}
    sample_input = data.get("sample_input")
    if not sample_input or not isinstance(sample_input, dict):
        return jsonify({"error": "sample_input (object) is required"}), 400
    cases = generate_edge_cases(sample_input)
    return jsonify({"total_cases": len(cases), "cases": cases}), 200


@app.route("/api/confirm-selection", methods=["POST"])
def confirm_selection_endpoint():
    data = request.get_json(silent=True) or {}
    sample_input = data.get("sample_input")
    selected_labels = data.get("selected_labels")

    if not sample_input or not isinstance(sample_input, dict):
        return jsonify({"error": "sample_input (object) is required"}), 400
    if not selected_labels or not isinstance(selected_labels, list):
        return jsonify({"error": "selected_labels (list) is required"}), 400

    all_cases = generate_edge_cases(sample_input)
    label_set = set(selected_labels)
    selected_cases = [c for c in all_cases if c["label"] in label_set]

    missing = label_set - {c["label"] for c in all_cases}
    if missing:
        return jsonify({"error": f"Unknown labels: {sorted(missing)}"}), 400
    if not selected_cases:
        return jsonify({"error": "No cases matched the selected labels"}), 400

    return jsonify({"confirmed_count": len(selected_cases), "confirmed_cases": selected_cases}), 200


def _validate_load_test_params(data):
    try:
        users = int(data.get("users", 5))
        spawn_rate = int(data.get("spawn_rate", 1))
        duration_seconds = int(data.get("duration_seconds", 30))
    except (TypeError, ValueError):
        return None, ("users, spawn_rate, duration_seconds must be integers", 400)

    if not (1 <= users <= MAX_USERS):
        return None, (f"users must be between 1 and {MAX_USERS}", 400)
    if not (1 <= spawn_rate <= MAX_SPAWN_RATE):
        return None, (f"spawn_rate must be between 1 and {MAX_SPAWN_RATE}", 400)
    if not (1 <= duration_seconds <= MAX_DURATION_SECONDS):
        return None, (f"duration_seconds must be between 1 and {MAX_DURATION_SECONDS}", 400)

    return (users, spawn_rate, duration_seconds), None


@app.route("/api/start-load-test", methods=["POST"])
def start_load_test_endpoint():
    data = request.get_json(silent=True) or {}
    target_url = data.get("url")
    confirmed_cases = data.get("confirmed_cases")

    if not target_url or not isinstance(target_url, str):
        return jsonify({"error": "url (string) is required"}), 400
    if not confirmed_cases or not isinstance(confirmed_cases, list):
        return jsonify({"error": "confirmed_cases (non-empty list) is required"}), 400

    params, err = _validate_load_test_params(data)
    if err:
        return jsonify({"error": err[0]}), err[1]
    users, spawn_rate, duration_seconds = params

    parsed = urlparse(target_url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return jsonify({"error": "url must be a valid http(s) URL"}), 400

    try:
        check_url(target_url, strict_dns=False)
    except UnsafeTarget as e:
        return jsonify({"error": str(e)}), 400

    host = f"{parsed.scheme}://{parsed.netloc}"
    path = parsed.path or "/"

    job_id, is_group = start_load_test(host, path, confirmed_cases, users, spawn_rate, duration_seconds)
    return jsonify({"job_id": job_id, "status": "started", "is_group": is_group}), 202


@app.route("/api/start-website-load-test", methods=["POST"])
def start_website_load_test_endpoint():
    data = request.get_json(silent=True) or {}
    target_url = data.get("url")
    sitemap_raw = data.get("sitemap_raw")

    if not target_url or not isinstance(target_url, str):
        return jsonify({"error": "url (string) is required"}), 400

    params, err = _validate_load_test_params(data)
    if err:
        return jsonify({"error": err[0]}), err[1]
    users, spawn_rate, duration_seconds = params

    parsed = urlparse(target_url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return jsonify({"error": "url must be a valid http(s) URL"}), 400

    try:
        check_url(target_url, strict_dns=False)
    except UnsafeTarget as e:
        return jsonify({"error": str(e)}), 400

    host = f"{parsed.scheme}://{parsed.netloc}"

    paths = []
    if sitemap_raw:
        paths = extract_paths_from_sitemap(sitemap_raw)
    if not paths:
        paths = [parsed.path or "/"]

    job_id, is_group = start_website_load_test(host, paths, users, spawn_rate, duration_seconds)
    return jsonify({"job_id": job_id, "status": "started", "is_group": is_group, "paths_used": paths}), 202


@app.route("/api/load-test-status/<job_id>", methods=["GET"])
def load_test_status_endpoint(job_id):
    # A split job's id is a group_id, not a single job_id — check that first.
    group_status = get_group_status(job_id)
    if group_status is not None:
        return jsonify(group_status), 200

    status = get_job_status(job_id)
    if status is None:
        return jsonify({"error": "job_id not found"}), 404
    return jsonify(status), 200


@app.route("/api/jobs", methods=["GET"])
def list_jobs_endpoint():
    return jsonify({"jobs": list_jobs(), "job_groups": list_job_groups()}), 200


@app.route("/api/compare-jobs", methods=["POST"])
def compare_jobs_endpoint():
    data = request.get_json(silent=True) or {}
    job_id_a = data.get("job_id_a")
    job_id_b = data.get("job_id_b")

    if not job_id_a or not job_id_b:
        return jsonify({"error": "job_id_a and job_id_b are required"}), 400

    job_a = get_group_status(job_id_a) or get_job_status(job_id_a)
    job_b = get_group_status(job_id_b) or get_job_status(job_id_b)

    if job_a is None:
        return jsonify({"error": f"job_id_a '{job_id_a}' not found"}), 404
    if job_b is None:
        return jsonify({"error": f"job_id_b '{job_id_b}' not found"}), 404

    return jsonify({"job_a": job_a, "job_b": job_b}), 200


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)