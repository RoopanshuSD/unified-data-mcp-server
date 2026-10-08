"""Append-only JSONL audit log. Arguments are stored as a SHA-256 hash (queries can contain sensitive literals)."""
from __future__ import annotations

import hashlib
import json
import threading
import time
from pathlib import Path


class AuditLog:
    def __init__(self, path: str | Path | None):
        self.path = Path(path) if path else None
        self.records: list[dict] = []  # in-memory copy (tests, /metrics)
        self._lock = threading.Lock()

    def write(self, *, subject: str, role: str, tool: str, args: dict, decision: str, reason: str = "",
              latency_ms: float = 0.0, rows: int | None = None) -> dict:
        rec = {"ts": round(time.time(), 3), "sub": subject, "role": role, "tool": tool,
               "args_sha256": hashlib.sha256(json.dumps(args, sort_keys=True, default=str).encode()).hexdigest(),
               "decision": decision, "reason": reason, "latency_ms": round(latency_ms, 3), "rows": rows}
        with self._lock:
            self.records.append(rec)
            if self.path:
                with self.path.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(rec) + "\n")
        return rec
