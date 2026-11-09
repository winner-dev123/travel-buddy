import sys, re, json, collections
import yaml
from openapi_spec_validator import validate
from openapi_spec_validator.readers import read_from_filename

path = sys.argv[1]
spec_dict, base_uri = read_from_filename(path)
validate(spec_dict)
print("openapi-spec-validator: OK")

spec = spec_dict
text = open(path, encoding="utf-8").read()
refs = set(re.findall(r"#/components/(\w+)/([\w.-]+)", text))
problems = []
for kind, name in refs:
    if name not in spec.get("components", {}).get(kind, {}):
        problems.append(f"unresolved ref: {kind}/{name}")
defined = {(k, n) for k, v in spec["components"].items() if k != "securitySchemes" for n in v}
unused = sorted(f"{k}/{n}" for k, n in defined - refs)

ops = []
opids = collections.Counter()
phases = collections.Counter()
METHODS = {"get", "put", "post", "patch", "delete"}
for p, item in spec["paths"].items():
    for m, op in item.items():
        if m not in METHODS:
            continue
        ops.append((m.upper(), p))
        opids[op["operationId"]] += 1
        if "x-phase" not in op:
            problems.append(f"missing x-phase: {m} {p}")
        else:
            phases[op["x-phase"]] += 1
        if "x-requirements" not in op:
            problems.append(f"missing x-requirements: {m} {p}")
        if "x-rate-limit-class" not in op:
            problems.append(f"missing x-rate-limit-class: {m} {p}")
        params = [x.get("$ref", "") for x in op.get("parameters", [])]
        has_idem = any(r.endswith("/IdempotencyKey") for r in params)
        if (op.get("x-idempotency") == "required") != has_idem:
            problems.append(f"idempotency mismatch: {m} {p}")
        has_ifmatch = any(r.endswith("/IfMatch") for r in params)
        rsp = op.get("responses", {})
        if has_ifmatch and ("412" not in rsp or "428" not in rsp):
            problems.append(f"If-Match without 412/428: {m} {p}")
        # path params declared
        for name in re.findall(r"{(\w+)}", p):
            declared = any(r.endswith("/" + name[0].upper() + name[1:]) for r in params) or any(
                x.get("name") == name for x in op.get("parameters", []) if "name" in x)
            if not declared:
                problems.append(f"path param {name} not declared: {m} {p}")
for k, v in opids.items():
    if v > 1:
        problems.append(f"duplicate operationId {k}")

# privacy lint: schemas for other users must not carry sensitive props
SENSITIVE = {"email", "birth_date", "birth_year", "lat", "lng", "latitude", "longitude", "distance", "distance_km", "distance_m", "last_seen", "last_seen_at", "ip"}
def props(schema, seen=None):
    seen = seen or set()
    out = set()
    if "$ref" in schema:
        n = schema["$ref"].split("/")[-1]
        if n in seen: return out
        seen.add(n)
        return props(spec["components"]["schemas"][n], seen)
    for key in ("allOf", "anyOf", "oneOf"):
        for s in schema.get(key, []):
            out |= props(s, seen)
    for name, s in schema.get("properties", {}).items():
        out.add(name)
        if isinstance(s, dict) and name not in ("location", "centroid"):  # public-place GeoPoint is allowed
            out |= props(s, seen)
        if isinstance(s, dict) and s.get("type") == "array" and isinstance(s.get("items"), dict):
            out |= props(s["items"], seen)
    return out
for n in ["PublicProfile", "UserSummary", "TravelerCard", "TravelerPresence", "DiscoverySession", "PublicPost", "Post", "Comment", "Message", "Conversation", "GroupMember", "ConnectionRequest"]:
    bad = props({"$ref": f"#/components/schemas/{n}"}) & SENSITIVE
    if bad:
        problems.append(f"privacy lint: {n} exposes {sorted(bad)}")
# challenge member views must not carry answers
for n in ["Challenge", "ChallengeManagerView", "ChallengePage", "SubmissionResult"]:
    bad = {p for p in props({"$ref": f"#/components/schemas/{n}"}) if "answer" in p and p not in ("answer_count",)}
    if bad:
        problems.append(f"answer lint: {n} exposes {sorted(bad)}")

print(f"operations: {len(ops)}  by phase: {dict(sorted(phases.items()))}")
print(f"schemas: {len(spec['components']['schemas'])}")
print("unused components:", unused if unused else "none")
if problems:
    print("PROBLEMS:"); [print("  -", x) for x in problems]; sys.exit(1)
print("lint: OK")

# keyword sanity: detect junk keys produced by YAML flow-mapping comma splits
KNOWN = {"type","format","description","enum","const","default","example","examples","items","properties","required",
 "additionalProperties","minLength","maxLength","pattern","minimum","maximum","minItems","maxItems","uniqueItems",
 "allOf","anyOf","oneOf","not","$ref","nullable","readOnly","writeOnly","discriminator","propertyNames","minProperties",
 "maxProperties","contentEncoding","title","deprecated","exclusiveMinimum","exclusiveMaximum","multipleOf","unevaluatedProperties"}
junk = []
def walk_schema(o, path):
    if isinstance(o, dict):
        if ("type" in o or "$ref" in o) and not path.endswith("/properties") and "/properties/" not in path[-12:]:
            for k in o:
                if k not in KNOWN and not str(k).startswith("x-"):
                    junk.append(f"{path}: {k}")
        for k, v in o.items():
            walk_schema(v, f"{path}/{k}")
    elif isinstance(o, list):
        for i, v in enumerate(o): walk_schema(v, f"{path}[{i}]")
walk_schema(spec["components"]["schemas"], "#/components/schemas")
for p, item in spec["paths"].items():
    walk_schema(item, p)
# filter false positives where a property is literally named like a keyword container
junk = [j for j in junk if not j.split(": ")[0].endswith("/properties")]
print("schema keyword junk:", junk[:30] if junk else "none")
if junk: sys.exit(2)
