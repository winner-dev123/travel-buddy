import sys, yaml, collections
spec = yaml.safe_load(open(sys.argv[1], encoding="utf-8"))
METHODS = ["get", "post", "put", "patch", "delete"]
TAG_TITLES = collections.OrderedDict()
for t in spec["tags"]:
    TAG_TITLES[t["name"]] = t["name"]
rows = collections.defaultdict(list)
def auth_of(op):
    sec = op.get("security", spec["security"])
    perm = op.get("x-platform-permission")
    if op.get("x-dev-only"):
        return "none (dev only)"
    if sec == []:
        if "webhooks" in op.get("operationId", "").lower() or op["operationId"].startswith("receive"):
            return "signature"
        return "none"
    names = [list(s.keys())[0] if s else "" for s in sec]
    if "" in names:
        return "optional"
    if "pubsubOidc" in names:
        return "Pub/Sub OIDC"
    return f"bearer + `{perm}`" if perm else "bearer"
for path, item in spec["paths"].items():
    for m in METHODS:
        op = item.get(m)
        if not op: continue
        tag = op["tags"][0]
        idem = "required" if op.get("x-idempotency") == "required" else ("natural" if m in ("put", "delete") else "—")
        ent = op.get("x-entitlement", "")
        rows[tag].append((op["x-phase"], f"`{m.upper()} {path}`", str(op["x-phase"]), auth_of(op), idem,
                          op["x-rate-limit-class"], ent and f"`{ent}`", ", ".join(op["x-requirements"])))
out = []
for tag in TAG_TITLES:
    if tag not in rows: continue
    out.append(f"\n#### {tag}\n")
    out.append("| Endpoint | Phase | Auth | Idempotency | Rate class | Entitlement | Requirements |")
    out.append("|---|---|---|---|---|---|---|")
    for r in sorted(rows[tag], key=lambda r: r[0]):
        out.append("| " + " | ".join(r[1:]) + " |")
print("\n".join(out))
