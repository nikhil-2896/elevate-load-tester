"""Helpers for reading an OpenAPI document: resolving references, building
sample requests, matching responses, and comparing two versions."""
import copy
import re
from urllib.parse import quote

from jsonschema import Draft202012Validator

HTTP_METHODS = ("get", "put", "post", "delete", "options", "head", "patch", "trace")
WRITE_METHODS = ("post", "put", "patch")   # DELETE is never called


def deref(spec, node, _depth=0):
    """Follows local {"$ref": "#/a/b"} links until a real object is reached."""
    while isinstance(node, dict) and "$ref" in node and _depth < 10:
        target = spec
        for part in node["$ref"].lstrip("#/").split("/"):
            if not isinstance(target, dict) or part not in target:
                return {}
            target = target[part]
        node, _depth = target, _depth + 1
    return node


def operations(spec):
    """Every documented operation as {method, path, op, label}."""
    found = []
    for path, item in (spec.get("paths") or {}).items():
        item = deref(spec, item)
        if not isinstance(item, dict):
            continue
        for method in HTTP_METHODS:
            if isinstance(item.get(method), dict):
                found.append({"method": method, "path": path, "op": item[method],
                              "path_item": item, "label": f"{method.upper()} {path}"})
    return found


def parameters(spec, operation):
    """Path-level plus operation-level parameters (operation wins)."""
    merged = {}
    for source in (operation["path_item"].get("parameters", []),
                   operation["op"].get("parameters", [])):
        for p in source:
            p = deref(spec, p)
            if isinstance(p, dict) and "name" in p:
                merged[(p.get("in"), p["name"])] = p
    return list(merged.values())


def _convert_nullable(node):
    """OpenAPI 3.0's `nullable: true` becomes a JSON Schema type list."""
    if isinstance(node, list):
        return [_convert_nullable(n) for n in node]
    if not isinstance(node, dict):
        return node
    out = {k: _convert_nullable(v) for k, v in node.items()}
    if out.get("nullable") is True and isinstance(out.get("type"), str):
        out["type"] = [out["type"], "null"]
    return out


def make_validator(spec, schema):
    wrapper = dict(_convert_nullable(copy.deepcopy(schema)))
    wrapper["components"] = _convert_nullable(copy.deepcopy(spec.get("components", {})))
    return Draft202012Validator(wrapper)


def first_error(spec, schema, instance):
    """Returns a short description of the first schema violation, or None."""
    errors = sorted(make_validator(spec, schema).iter_errors(instance),
                    key=lambda e: [str(p) for p in e.path])
    if not errors:
        return None
    e = errors[0]
    where = "/".join(str(p) for p in e.path) or "(body)"
    return f"{where}: {e.message}"[:160]


# ---- sample data -----------------------------------------------------

def _merge_all_of(spec, schema):
    schema = deref(spec, schema)
    if not isinstance(schema, dict) or "allOf" not in schema:
        return schema
    merged = {k: v for k, v in schema.items() if k != "allOf"}
    props, required = dict(merged.get("properties", {})), list(merged.get("required", []))
    for part in schema["allOf"]:
        part = _merge_all_of(spec, part)
        if isinstance(part, dict):
            props.update(part.get("properties", {}))
            required += part.get("required", [])
            for k, v in part.items():
                if k not in ("properties", "required"):
                    merged.setdefault(k, v)
    merged["properties"], merged["required"] = props, required
    return merged


def sample(spec, schema, depth=0):
    """A small valid example value for a schema."""
    schema = _merge_all_of(spec, schema)
    if not isinstance(schema, dict) or depth > 6:
        return None
    for key in ("example", "default"):
        if key in schema:
            return schema[key]
    if schema.get("enum"):
        return schema["enum"][0]
    for key in ("oneOf", "anyOf"):
        if schema.get(key):
            return sample(spec, schema[key][0], depth + 1)
    kind = schema.get("type") or ("object" if "properties" in schema else "string")
    if isinstance(kind, list):
        kind = next((k for k in kind if k != "null"), "string")
    if kind == "object":
        props = schema.get("properties", {})
        names = schema.get("required") or list(props)
        return {n: sample(spec, props.get(n, {}), depth + 1) for n in names}
    if kind == "array":
        return [sample(spec, schema.get("items", {}), depth + 1)]
    if kind == "integer":
        return schema.get("minimum", 1)
    if kind == "number":
        return schema.get("minimum", 1.5)
    if kind == "boolean":
        return True
    fmt = schema.get("format")
    known = {"date-time": "2024-01-01T00:00:00Z", "date": "2024-01-01",
             "uuid": "00000000-0000-4000-8000-000000000000",
             "email": "user@example.com", "uri": "https://example.com"}
    if fmt in known:
        return known[fmt]
    return "string".ljust(schema.get("minLength", 0), "x")


def build_request(spec, operation):
    """Returns (path, query_params, json_body_or_None) for one operation."""
    path = operation["path"]
    query = {}
    for p in parameters(spec, operation):
        value = sample(spec, p.get("schema", {}))
        if p.get("in") == "path":
            path = path.replace("{" + p["name"] + "}", quote(str(value), safe=""))
        elif p.get("in") == "query" and p.get("required"):
            query[p["name"]] = value
    body = None
    schema = request_schema(spec, operation["op"])
    if schema is not None:
        body = sample(spec, schema)
    return path, query, body


def request_schema(spec, op):
    content = deref(spec, op.get("requestBody", {})).get("content", {})
    for media, entry in content.items():
        if "json" in media.lower() and isinstance(entry, dict) and "schema" in entry:
            return entry["schema"]
    return None


def required_fields(spec, schema):
    merged = _merge_all_of(spec, schema)
    return list(merged.get("required", [])) if isinstance(merged, dict) else []


# ---- responses -------------------------------------------------------

def find_response(spec, op, status):
    """Returns (key, response_object) declared for this status, or (None, None)."""
    responses = op.get("responses", {})
    for key in (str(status), f"{status // 100}XX", f"{status // 100}xx", "default"):
        if key in responses:
            return key, deref(spec, responses[key])
    return None, None


def response_json_schema(response):
    for media, entry in (response.get("content") or {}).items():
        if "json" in media.lower() and isinstance(entry, dict) and "schema" in entry:
            return entry["schema"]
    return None


def media_allowed(declared, content_type):
    base = content_type.split(";")[0].strip().lower()
    for d in declared:
        d = d.lower()
        if d == base or d == "*/*" or (d.endswith("/*") and base.startswith(d[:-1])):
            return True
    return False


# ---- comparing two versions of a spec --------------------------------

def _schema_props(spec, schema):
    merged = _merge_all_of(spec, schema)
    if not isinstance(merged, dict):
        return {}
    return {name: deref(spec, p).get("type") for name, p in merged.get("properties", {}).items()}


def _required_params(spec, operation):
    return {(p.get("in"), p["name"]) for p in parameters(spec, operation) if p.get("required")}


def diff_specs(old, new):
    """Lists the changes that would break existing clients."""
    problems = []
    new_ops = {(o["method"], o["path"]): o for o in operations(new)}
    for o in operations(old):
        key = (o["method"], o["path"])
        if key not in new_ops:
            problems.append(f"removed {o['label']}")
            continue
        n = new_ops[key]
        for loc, name in sorted(_required_params(new, n) - _required_params(old, o)):
            problems.append(f"{o['label']}: new required {loc} parameter '{name}'")
        old_req, new_req = request_schema(old, o["op"]), request_schema(new, n["op"])
        if new_req is not None:
            before = set(required_fields(old, old_req)) if old_req is not None else set()
            for field in sorted(set(required_fields(new, new_req)) - before):
                problems.append(f"{o['label']}: new required request field '{field}'")
        for status, response in (o["op"].get("responses") or {}).items():
            if not str(status).startswith("2"):
                continue
            if status not in (n["op"].get("responses") or {}):
                problems.append(f"{o['label']}: removed {status} response")
                continue
            old_s = response_json_schema(deref(old, response))
            new_s = response_json_schema(deref(new, n["op"]["responses"][status]))
            if old_s is None or new_s is None:
                continue
            before, after = _schema_props(old, old_s), _schema_props(new, new_s)
            for name, kind in before.items():
                if name not in after:
                    problems.append(f"{o['label']} {status}: response field '{name}' removed")
                elif kind != after[name]:
                    problems.append(f"{o['label']} {status}: response field '{name}' "
                                    f"changed type {kind} -> {after[name]}")
    return problems