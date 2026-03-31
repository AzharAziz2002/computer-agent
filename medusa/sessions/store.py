"""Session persistence using JSONL transcripts + JSON index.

Storage layout (following OpenClaw's pattern):
    .sessions/
    ├── sessions.json                # {session_id: SessionMeta}
    └── transcripts/
        └── {session_id}.jsonl       # One JSON object per line

Transcript line types:
    {"type": "user",   "content": "...", "timestamp": "..."}
    {"type": "step",   "stepNumber": 1, "thought": "...", "action": {...}, "observation": "...", "isError": false, "timestamp": "..."}
    {"type": "result", "content": "...", "timestamp": "..."}
    {"type": "error",  "content": "...", "timestamp": "..."}
"""

import json
import os
from datetime import datetime
from pathlib import Path


SESSIONS_DIR = Path(".sessions")


class SessionStore:
    def __init__(self, base_dir: Path = SESSIONS_DIR):
        self.base_dir = base_dir
        self.transcripts_dir = base_dir / "transcripts"
        self.index_path = base_dir / "sessions.json"
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.transcripts_dir.mkdir(parents=True, exist_ok=True)

    # ── Index I/O ────────────────────────────────────────────

    def _load_index(self) -> dict[str, dict]:
        if self.index_path.exists():
            return json.loads(self.index_path.read_text(encoding="utf-8"))
        return {}

    def _save_index(self, index: dict[str, dict]):
        self.index_path.write_text(json.dumps(index, indent=2), encoding="utf-8")

    # ── Session CRUD ─────────────────────────────────────────

    def create(self, session_id: str, query: str, model: str | None = None) -> dict:
        now = datetime.now().isoformat()
        meta = {
            "id": session_id,
            "title": query[:60].strip(),
            "created_at": now,
            "updated_at": now,
            "status": "running",
            "model": model,
            "preview": query[:100],
        }
        index = self._load_index()
        index[session_id] = meta
        self._save_index(index)
        return meta

    def update(self, session_id: str, **kwargs):
        index = self._load_index()
        if session_id in index:
            index[session_id].update(kwargs)
            index[session_id]["updated_at"] = datetime.now().isoformat()
            self._save_index(index)

    def get(self, session_id: str) -> dict | None:
        return self._load_index().get(session_id)

    def list_sessions(self) -> list[dict]:
        index = self._load_index()
        return sorted(index.values(), key=lambda s: s.get("updated_at", ""), reverse=True)

    def delete(self, session_id: str):
        index = self._load_index()
        index.pop(session_id, None)
        self._save_index(index)
        transcript = self.transcripts_dir / f"{session_id}.jsonl"
        if transcript.exists():
            transcript.unlink()

    # ── Transcript I/O ───────────────────────────────────────

    def append(self, session_id: str, entry: dict):
        """Append a single JSON line to the session transcript."""
        transcript = self.transcripts_dir / f"{session_id}.jsonl"
        with open(transcript, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")

    def load_transcript(self, session_id: str) -> list[dict]:
        """Read all entries from a session transcript."""
        transcript = self.transcripts_dir / f"{session_id}.jsonl"
        if not transcript.exists():
            return []
        entries = []
        for line in transcript.read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return entries


# Singleton
session_store = SessionStore()
