import json, pathlib, sys, uuid
from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

d = pathlib.Path(sys.argv[1])
schemas = {}
for f in sorted(d.glob("*.schema.json")):
    s = json.loads(f.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(s)
    schemas[f.name] = s
print(f"metaschema (2020-12) check OK for {len(schemas)} schemas")
reg = Registry().with_resources([(s["$id"], Resource.from_contents(s)) for s in schemas.values()])
def v(name):
    return Draft202012Validator(schemas[name], registry=reg, format_checker=FormatChecker())

U = lambda: str(uuid.uuid4())
T = "2026-11-09T12:00:00Z"
def env(t, data, **kw):
    e = {"v": 1, "type": t, "id": U(), "ts": T, "data": data}; e.update(kw); return e
msg = {"id": U(), "conversation_id": U(), "seq": 42, "client_message_id": None, "sender": {"id": U(), "handle": "ana.rio", "display_name": "Ana", "avatar": None},
       "kind": "text", "body": "Meet at Arpoador at 6?", "attachments": [], "reply_to": None, "thread_root_id": None, "thread_reply_count": 0,
       "mentions": [], "reactions": [], "pinned": False, "moderation_state": "visible", "edited_at": None, "deleted_at": None, "created_at": T}
good = [
 ("client.auth.schema.json", env("auth", {"access_token": "eyJhbGciOiJFZERTQSJ9.x.y", "client": "ios"})),
 ("client.auth.schema.json", env("auth", {"ticket": "A"*43, "client": "web"})),
 ("client.message.send.schema.json", env("message.send", {"conversation_id": U(), "client_message_id": U(), "body": "hi"})),
 ("client.sync.request.schema.json", env("sync.request", {"conversations": [{"conversation_id": U(), "last_seq": 10}]})),
 ("server.auth.ok.schema.json", env("auth.ok", {"user_id": U(), "session_id": U(), "connection_id": U(), "server_time": T, "auth_expires_at": T,
   "heartbeat_interval_s": 25, "limits": {"max_inbound_frame_bytes": 32768, "message_send_per_minute": 30, "typing_min_interval_s": 3, "frames_per_minute": 120}}, reply_to=U())),
 ("server.message.ack.schema.json", env("message.ack", {"conversation_id": U(), "client_message_id": U(), "message_id": U(), "seq": 43, "created_at": T, "duplicate": False}, reply_to=U())),
 ("server.message.new.schema.json", env("message.new", {"message": msg})),
 ("server.receipt.updated.schema.json", env("receipt.updated", {"conversation_id": U(), "user_id": U(), "read_through_seq": 42})),
 ("server.sync.required.schema.json", env("sync.required", {"reason": "reconnect", "full_resync": False, "conversations": [{"conversation_id": U(), "from_seq": 10, "server_last_seq": 17}]})),
 ("server.error.schema.json", env("error", {"code": "connection_required", "message": "You need to be connected", "retryable": False}, reply_to=U())),
 ("server.conversation.updated.schema.json", env("conversation.updated", {"conversation_id": U(), "send_restriction": None, "can_send": True})),
]
bad = [
 ("client.auth.schema.json", env("auth", {"access_token": "eyJhbGciOiJFZERTQSJ9.x.y", "ticket": "A"*43}), "both credentials"),
 ("client.auth.schema.json", env("auth", {}), "no credentials"),
 ("client.auth.schema.json", env("auth", {"ticket": "short"}), "malformed ticket"),
 ("client.message.send.schema.json", env("message.send", {"conversation_id": U(), "client_message_id": U()}), "no body/attachments"),
 ("client.message.send.schema.json", env("message.send", {"conversation_id": U(), "client_message_id": U(), "body": "x"}, reply_to=U()), "client reply_to"),
 ("client.ping.schema.json", env("ping", {}, v=2), "wrong version"),
 ("server.message.new.schema.json", env("message.new", {"message": {**msg, "sender_location": {"lat": 1, "lng": 2}}}), "extra field on Message"),
 ("server.receipt.updated.schema.json", env("receipt.updated", {"conversation_id": U(), "user_id": U()}), "receipt without watermark"),
 ("server.typing.schema.json", env("message.new", {"conversation_id": U(), "user_id": U(), "state": "started", "expires_at": T}), "type mismatch"),
]
fail = 0
for name, inst in good:
    errs = list(v(name).iter_errors(inst))
    if errs: fail += 1; print("UNEXPECTED FAIL", name, [e.message for e in errs][:3])
for name, inst, why in bad:
    if v(name).is_valid(inst): fail += 1; print("UNEXPECTED PASS", name, why)
print(f"sample frames: {len(good)} valid accepted, {len(bad)} invalid rejected" if not fail else f"{fail} sample failures")
sys.exit(1 if fail else 0)
