import hashlib
import json
from datetime import datetime, timezone


def make_trace_id(payload: dict) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()[:24]


def make_snapshot_id(payload: dict) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return "SNAP-" + hashlib.sha256(raw).hexdigest()[:20]


def now_utc() -> datetime:
    return datetime.now(timezone.utc)
