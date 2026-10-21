"""A small web app with deliberately good and bad behaviour.

It has two jobs: tests of the testing platform run against it (so the right
verdict is known in advance), and it is a safe thing to point the platform at
in a demo. Never deploy it anywhere public.
"""
import json
import threading
import time
from contextlib import contextmanager

from flask import Flask, jsonify, request
from werkzeug.serving import make_server

LIMIT = 5            # /limited allows this many requests ...
WINDOW_SECONDS = 2   # ... per window, then answers 429


def create_app():
    app = Flask(__name__)
    state = {"hits": 0, "window_start": time.monotonic()}

    # ---- good behaviour -------------------------------------------------

    @app.get("/good")
    def good():
        return jsonify({"status": "ok"})

    @app.post("/items")
    def items():
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return jsonify({"error": "invalid_json"}), 400
        if "name" not in data:
            return jsonify({"error": "validation_error", "field": "name"}), 422
        if not isinstance(data["name"], str):
            return jsonify({"error": "validation_error", "field": "name"}), 422
        return jsonify({"id": 1, "name": data["name"]}), 201

    @app.get("/unlimited")
    def unlimited():
        return jsonify({"status": "ok"})

    @app.get("/limited")
    def limited():
        now = time.monotonic()
        if now - state["window_start"] >= WINDOW_SECONDS:
            state["window_start"], state["hits"] = now, 0
        state["hits"] += 1
        if state["hits"] > LIMIT:
            retry = max(1, int(WINDOW_SECONDS - (now - state["window_start"])) + 1)
            resp = jsonify({"error": "rate_limited"})
            resp.status_code = 429
            resp.headers["Retry-After"] = str(retry)
            return resp
        return jsonify({"status": "ok"})

    # ---- bad behaviour (on purpose) ---------------------------------------

    @app.post("/crash")
    def crash():
        # Unhandled error on bad JSON: answers 500 instead of 400.
        data = json.loads(request.get_data())
        return jsonify(data)

    @app.get("/leaky")
    def leaky():
        body = ('Traceback (most recent call last):\n'
                '  File "/srv/app/main.py", line 42, in handler\n'
                'sqlalchemy.exc.OperationalError: SELECT * FROM users')
        return body, 500, {"Content-Type": "text/plain"}

    @app.get("/spec-lies")
    def spec_lies():
        # The OpenAPI document says "count" is an integer. It is a string.
        return jsonify({"count": "three"})

    # ---- API description --------------------------------------------------

    @app.get("/openapi.json")
    def openapi():
        ok_object = {"type": "object", "required": ["status"],
                     "properties": {"status": {"type": "string"}}}
        return jsonify({
            "openapi": "3.0.3",
            "info": {"title": "Demo target", "version": "1.0.0"},
            "paths": {
                "/good": {"get": {"responses": {"200": {
                    "description": "ok",
                    "content": {"application/json": {"schema": ok_object}}}}}},
                "/spec-lies": {"get": {"responses": {"200": {
                    "description": "counts",
                    "content": {"application/json": {"schema": {
                        "type": "object", "required": ["count"],
                        "properties": {"count": {"type": "integer"}}}}}}}}},
            },
        })

    # ---- test helper ------------------------------------------------------

    @app.post("/__reset")
    def reset():
        state["hits"], state["window_start"] = 0, time.monotonic()
        return jsonify({"status": "reset"})

    return app


@contextmanager
def serve(app=None, port=0):
    """Runs the app on 127.0.0.1 in a background thread and yields its base
    URL, e.g. 'http://127.0.0.1:54321'. Port 0 picks a free port."""
    server = make_server("127.0.0.1", port, app or create_app(), threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        thread.join(timeout=5)


if __name__ == "__main__":
    create_app().run(host="127.0.0.1", port=8100)