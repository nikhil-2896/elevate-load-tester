"""T10: the API-contract module, tested against apps whose right answer is
known in advance."""
import copy

import pytest
from flask import Flask, jsonify, request

from demo_target.app import create_app, serve
from testkit import executor, registry, store
from testkit.models import Status, Target
from testkit.modules.api_contract import spec as sp
from testkit.modules.api_contract.module import ApiContract
from testkit.selector import build_plan


@pytest.fixture(autouse=True)
def _allow_local(monkeypatch):
    monkeypatch.setenv("TESTKIT_ALLOW_PRIVATE", "true")


def spec_of(paths, components=None):
    doc = {"openapi": "3.0.3", "info": {"title": "t", "version": "1"}, "paths": paths}
    if components:
        doc["components"] = components
    return doc


def ok_response(schema=None, status="200", headers=None, media="application/json"):
    resp = {"description": "ok"}
    if schema is not None:
        resp["content"] = {media: {"schema": schema}}
    if headers:
        resp["headers"] = headers
    return {status: resp}


def serve_spec(spec, routes=None):
    """An app that publishes `spec` and has extra routes added by `routes(app)`."""
    app = Flask("contract")

    @app.get("/openapi.json")
    def doc():
        return jsonify(spec)

    if routes:
        routes(app)
    return app


def run_module(base, **options):
    target = Target(base_url=base, openapi_url=base + "/openapi.json")
    result = ApiContract().run(target, options)
    return {f.check_id: f for f in result.findings}, result


GET_PING = {"/ping": {"get": {"responses": ok_response({"type": "object"})}}}


def ping_app(spec=None, body=None):
    def routes(app):
        @app.get("/ping")
        def ping():
            return jsonify(body if body is not None else {"ok": True})
    return serve_spec(spec or spec_of(GET_PING), routes)


# ---- T10.1 spec validity ----------------------------------------------

def test_t10_1_valid_description_passes():
    with serve(create_app()) as base:
        f, _ = run_module(base)
    assert f["T10.1"].status == Status.PASS


def test_t10_1_invalid_description_fails_and_stops():
    broken = {"openapi": "3.0.3", "paths": {}}          # no "info"
    with serve(serve_spec(broken)) as base:
        f, result = run_module(base)
    assert f["T10.1"].status == Status.FAIL
    assert list(f) == ["T10.1"]


def test_t10_1_unfetchable_or_non_json_description_fails():
    app = Flask("nodoc")
    with serve(app) as base:
        f, _ = run_module(base)
    assert f["T10.1"].status == Status.FAIL and "404" in f["T10.1"].detail
    yaml_app = Flask("yaml")

    @yaml_app.get("/openapi.json")
    def doc():
        return "openapi: 3.0.3\n", 200, {"Content-Type": "text/yaml"}

    with serve(yaml_app) as base:
        f, _ = run_module(base)
    assert "not JSON" in f["T10.1"].detail


# ---- T10.2 - T10.6 -----------------------------------------------------

def test_t10_2_documented_but_missing_operation_fails():
    paths = {"/ghost": {"get": {"responses": ok_response()}}}
    with serve(serve_spec(spec_of(paths))) as base:
        f, _ = run_module(base)
    assert f["T10.2"].status == Status.FAIL


def test_t10_2_wrong_method_fails_and_param_404_only_warns():
    paths = {"/only-post": {"get": {"responses": ok_response()}},
             "/things/{id}": {"get": {"parameters": [{"name": "id", "in": "path", "required": True,
                                                       "schema": {"type": "integer"}}],
                                      "responses": ok_response()}}}

    def routes(app):
        @app.post("/only-post")
        def p():
            return "x"

        @app.get("/things/<int:i>")
        def t(i):
            return jsonify({}), 404

    with serve(serve_spec(spec_of(paths), routes)) as base:
        f, _ = run_module(base)
    ops = {o["operation"]: o["rating"] for o in f["T10.2"].evidence["operations"]}
    assert ops["GET /only-post"] == "fail"
    assert ops["GET /things/{id}"] == "warn"


def test_t10_3_undeclared_status_fails_but_ranges_and_default_are_accepted():
    paths = {"/a": {"get": {"responses": ok_response(status="201")}},
             "/b": {"get": {"responses": ok_response(status="2XX")}},
             "/c": {"get": {"responses": {"default": {"description": "any"}}}}}

    def routes(app):
        for name in "abc":
            app.add_url_rule(f"/{name}", name, lambda: jsonify({}))

    with serve(serve_spec(spec_of(paths), routes)) as base:
        f, _ = run_module(base)
    assert f["T10.3"].status == Status.FAIL
    bad = [o["operation"] for o in f["T10.3"].evidence["operations"]]
    assert bad == ["GET /a"]


def test_t10_4_schema_violation_fails_and_conforming_body_passes():
    with serve(create_app()) as base:          # /spec-lies says count is an integer
        f, _ = run_module(base)
    assert f["T10.4"].status == Status.FAIL
    bad = f["T10.4"].evidence["operations"]
    assert [o["operation"] for o in bad] == ["GET /spec-lies"]
    assert "count" in bad[0]["problem"]
    with serve(ping_app(spec_of({"/ping": {"get": {"responses": ok_response(
            {"type": "object", "required": ["ok"], "properties": {"ok": {"type": "boolean"}}})}}}))) as base:
        f, _ = run_module(base)
    assert f["T10.4"].status == Status.PASS


def test_t10_4_handles_refs_nullable_and_arrays():
    components = {"schemas": {"Item": {"type": "object", "required": ["id"],
                                       "properties": {"id": {"type": "integer"},
                                                      "note": {"type": "string", "nullable": True}}}}}
    paths = {"/items": {"get": {"responses": ok_response(
        {"type": "array", "items": {"$ref": "#/components/schemas/Item"}})}}}

    def routes(app):
        @app.get("/items")
        def items():
            return jsonify([{"id": 1, "note": None}, {"id": 2, "note": "x"}])

    with serve(serve_spec(spec_of(paths, components), routes)) as base:
        f, _ = run_module(base)
    assert f["T10.4"].status == Status.PASS

    def bad_routes(app):
        @app.get("/items")
        def items():
            return jsonify([{"id": "one"}])

    with serve(serve_spec(spec_of(paths, components), bad_routes)) as base:
        f, _ = run_module(base)
    assert f["T10.4"].status == Status.FAIL


def test_t10_4_a_non_json_body_where_json_is_promised_fails():
    app = ping_app(body=None)
    spec = spec_of(GET_PING)

    def routes(a):
        @a.get("/ping")
        def ping():
            return "<html>oops</html>"

    with serve(serve_spec(spec, routes)) as base:
        f, _ = run_module(base)
    assert f["T10.4"].status == Status.FAIL and "not valid JSON" in f["T10.4"].detail


def test_t10_5_content_type_mismatch_fails_and_wildcards_pass():
    def routes(app):
        @app.get("/ping")
        def ping():
            return "plain", 200, {"Content-Type": "text/plain"}

    with serve(serve_spec(spec_of(GET_PING), routes)) as base:
        f, _ = run_module(base)
    assert f["T10.5"].status == Status.FAIL
    wild = spec_of({"/ping": {"get": {"responses": ok_response(None, media="text/*") | {}}}})
    wild["paths"]["/ping"]["get"]["responses"]["200"]["content"] = {"text/*": {}}
    with serve(serve_spec(wild, routes)) as base:
        f, _ = run_module(base)
    assert f["T10.5"].status == Status.PASS


def test_t10_6_required_header_must_be_sent():
    hdr = {"X-Request-Id": {"required": True, "schema": {"type": "string"}}}
    spec = spec_of({"/ping": {"get": {"responses": ok_response({"type": "object"}, headers=hdr)}}})
    with serve(ping_app(spec)) as base:
        f, _ = run_module(base)
    assert f["T10.6"].status == Status.FAIL and "X-Request-Id" in f["T10.6"].detail

    def routes(app):
        @app.get("/ping")
        def ping():
            return jsonify({}), 200, {"x-request-id": "abc"}

    with serve(serve_spec(spec, routes)) as base:
        f, _ = run_module(base)
    assert f["T10.6"].status == Status.PASS


# ---- T10.7 and safety of calls -----------------------------------------

def write_spec():
    body = {"type": "object", "required": ["name"], "properties": {"name": {"type": "string"}}}
    return spec_of({"/items": {
        "post": {"requestBody": {"content": {"application/json": {"schema": body}}},
                 "responses": {**ok_response({"type": "object"}, status="201"),
                               **ok_response({"type": "object"}, status="422")}},
        "delete": {"responses": ok_response()}}})


def counting_app(spec, reject_with=422):
    hits = []

    def routes(app):
        @app.post("/items")
        def create():
            hits.append("POST")
            if not (request.get_json(silent=True) or {}).get("name"):
                return jsonify({"error": "bad"}), reject_with
            return jsonify({"id": 1}), 201

        @app.delete("/items")
        def delete():
            hits.append("DELETE")
            return jsonify({})

    return serve_spec(spec, routes), hits


def test_t10_7_write_operations_are_not_called_by_default():
    app, hits = counting_app(write_spec())
    with serve(app) as base:
        f, result = run_module(base)
    assert hits == []
    assert f["T10.7"].status == Status.SKIPPED
    assert result.metrics["operations_called"] == 0


def test_t10_7_post_is_called_when_allowed_but_delete_never_is():
    app, hits = counting_app(write_spec())
    with serve(app) as base:
        f, _ = run_module(base, allow_write_calls=True)
    assert "POST" in hits and "DELETE" not in hits
    assert f["T10.7"].status == Status.PASS


def test_t10_7_accepting_an_invalid_body_fails_and_undocumented_4xx_warns():
    def lax_routes(app):
        @app.post("/items")
        def create():
            return jsonify({"id": 1}), 201

    with serve(serve_spec(write_spec(), lax_routes)) as base:
        f, _ = run_module(base, allow_write_calls=True)
    assert f["T10.7"].status == Status.FAIL
    app, _ = counting_app(write_spec(), reject_with=400)
    with serve(app) as base:
        f, _ = run_module(base, allow_write_calls=True)
    assert f["T10.7"].status == Status.WARN


def test_t10_7_path_and_required_query_parameters_are_filled_in():
    seen = []
    paths = {"/users/{uid}/posts": {"get": {
        "parameters": [{"name": "uid", "in": "path", "required": True, "schema": {"type": "integer"}},
                       {"name": "page", "in": "query", "required": True, "schema": {"type": "integer"}}],
        "responses": ok_response({"type": "object"})}}}

    def routes(app):
        @app.get("/users/<int:uid>/posts")
        def posts(uid):
            seen.append((uid, request.args.get("page")))
            return jsonify({})

    with serve(serve_spec(spec_of(paths), routes)) as base:
        run_module(base)
    assert seen == [(1, "1")]


# ---- T10.8 breaking changes --------------------------------------------

OLD = spec_of({
    "/a": {"get": {"parameters": [{"name": "q", "in": "query", "schema": {"type": "string"}}],
                   "responses": ok_response({"type": "object", "properties": {
                       "id": {"type": "integer"}, "name": {"type": "string"}}})}},
    "/b": {"get": {"responses": ok_response()}, "post": {"responses": ok_response()}},
})


def changed(mutator):
    doc = copy.deepcopy(OLD)
    mutator(doc)
    return doc


def test_t10_8_diff_detects_each_kind_of_breaking_change():
    assert sp.diff_specs(OLD, changed(lambda d: d["paths"].pop("/b"))) == [
        "removed GET /b", "removed POST /b"]
    assert sp.diff_specs(OLD, changed(lambda d: d["paths"]["/b"].pop("post"))) == ["removed POST /b"]
    assert any("new required query parameter 'q2'" in p for p in sp.diff_specs(OLD, changed(
        lambda d: d["paths"]["/a"]["get"]["parameters"].append(
            {"name": "q2", "in": "query", "required": True, "schema": {"type": "string"}}))))
    assert any("'name' removed" in p for p in sp.diff_specs(OLD, changed(
        lambda d: d["paths"]["/a"]["get"]["responses"]["200"]["content"]["application/json"][
            "schema"]["properties"].pop("name"))))
    assert any("'id' changed type integer -> string" in p for p in sp.diff_specs(OLD, changed(
        lambda d: d["paths"]["/a"]["get"]["responses"]["200"]["content"]["application/json"][
            "schema"]["properties"]["id"].update(type="string"))))
    assert any("removed 200 response" in p for p in sp.diff_specs(OLD, changed(
        lambda d: d["paths"]["/b"]["get"].update(responses=ok_response(status="204")))))


def test_t10_8_diff_detects_a_newly_required_request_field():
    schema = lambda req: {"type": "object", "required": req, "properties": {"x": {"type": "string"}}}
    body = lambda req: {"content": {"application/json": {"schema": schema(req)}}}
    old = spec_of({"/c": {"post": {"requestBody": body([]), "responses": ok_response()}}})
    new = spec_of({"/c": {"post": {"requestBody": body(["x"]), "responses": ok_response()}}})
    assert sp.diff_specs(old, new) == ["POST /c: new required request field 'x'"]


def test_t10_8_additive_changes_are_not_breaking():
    def add(d):
        d["paths"]["/new"] = {"get": {"responses": ok_response()}}
        d["paths"]["/a"]["get"]["responses"]["200"]["content"]["application/json"][
            "schema"]["properties"]["extra"] = {"type": "string"}
        d["paths"]["/a"]["get"]["parameters"].append(
            {"name": "opt", "in": "query", "schema": {"type": "string"}})
    assert sp.diff_specs(OLD, changed(add)) == []


def test_t10_8_module_uses_the_baseline_when_given():
    with serve(ping_app()) as base:
        f, _ = run_module(base)
        assert f["T10.8"].status == Status.SKIPPED
        baseline = spec_of({**GET_PING, "/removed": {"get": {"responses": ok_response()}}})
        f, _ = run_module(base, baseline_spec=baseline)
        assert f["T10.8"].status == Status.FAIL and "removed GET /removed" in f["T10.8"].detail
        f, _ = run_module(base, baseline_spec=spec_of(GET_PING))
        assert f["T10.8"].status == Status.PASS


# ---- sample data ---------------------------------------------------------

def test_t10_9_sample_values_respect_schema_hints():
    doc = spec_of({}, {"schemas": {"P": {"type": "object", "required": ["id", "tag"], "properties": {
        "id": {"type": "string", "format": "uuid"}, "tag": {"enum": ["a", "b"]},
        "skip": {"type": "string"}}}}})
    assert sp.sample(doc, {"$ref": "#/components/schemas/P"}) == {
        "id": "00000000-0000-4000-8000-000000000000", "tag": "a"}
    assert sp.sample(doc, {"type": "integer", "minimum": 5}) == 5
    assert sp.sample(doc, {"type": "string", "minLength": 3}) == "string"
    assert sp.sample(doc, {"type": "array", "items": {"type": "boolean"}}) == [True]
    both = {"allOf": [{"type": "object", "required": ["a"], "properties": {"a": {"type": "integer"}}},
                      {"type": "object", "required": ["b"], "properties": {"b": {"type": "string"}}}]}
    assert sp.sample(doc, both) == {"a": 1, "b": "string"}


# ---- whole-module behaviour ---------------------------------------------

def test_t10_10_unreachable_operations_are_reported():
    spec = spec_of(GET_PING)
    f, result = run_module("http://127.0.0.1:9", spec=spec)
    assert f["T10.2"].status == Status.FAIL and "no response" in f["T10.2"].detail


def test_t10_11_private_targets_are_refused_unless_allowed(monkeypatch):
    monkeypatch.delenv("TESTKIT_ALLOW_PRIVATE")
    f, result = run_module("http://127.0.0.1:8100")
    assert result.status == Status.SKIPPED and "public" in f["T10.0"].detail


def test_t10_12_budget_exhaustion_gives_partial_results_and_a_warning():
    paths = {f"/p{i}": {"get": {"responses": ok_response()}} for i in range(5)}

    def routes(app):
        for i in range(5):
            app.add_url_rule(f"/p{i}", f"p{i}", lambda: jsonify({}))

    with serve(serve_spec(spec_of(paths), routes)) as base:
        f, result = run_module(base, max_requests=3)
    assert f["T10.0"].status == Status.WARN and "partial" in f["T10.0"].detail
    assert result.metrics["requests"] == 3


def test_t10_13_findings_come_back_in_check_order():
    with serve(create_app()) as base:
        _, result = run_module(base)
    numbers = [int(f.check_id.split(".")[1]) for f in result.findings]
    assert numbers == sorted(numbers)


def test_t10_14_selected_only_when_a_spec_is_supplied():
    assert "api_contract" in [m.id for m in registry.discover()]
    with_spec = build_plan({"api-correctness"}, Target(base_url="http://x", openapi_url="http://x/o"))
    assert "api_contract" in [i.module_id for i in with_spec.selected]
    without = build_plan({"api-correctness"}, Target(base_url="http://x"))
    assert "api_contract" not in [i.module_id for i in without.selected]
    skipped = {s.module_id: s.reason for s in without.skipped}
    assert skipped["api_contract"] == "missing input: openapi"


def test_t10_15_runs_end_to_end_through_the_executor_and_store():
    with serve(create_app()) as base:
        target = Target(base_url=base, openapi_url=base + "/openapi.json")
        plan = build_plan({"api-correctness"}, target)
        run_id = executor.start_run({"api-correctness"}, target, plan, background=False)
    run = store.get_run(run_id)
    contract = next(r for r in run["results"] if r["module"] == "api_contract")
    findings = {f["check_id"]: f for f in contract["findings"]}
    assert run["status"] == "done"
    assert findings["T10.1"]["status"] == "pass" and findings["T10.4"]["status"] == "fail"