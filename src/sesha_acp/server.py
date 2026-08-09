"""ACP request handler — pure logic, no I/O on stdin/stdout.

The real server (stdio) feeds decoded JSON-RPC messages to `handle()` and
serializes the returned responses/notifications. Keeping this side-effect-light
makes it fully testable offline.
"""
from __future__ import annotations

import uuid
from collections.abc import Callable, Iterable
from pathlib import Path

from . import protocol as p

# JSON-RPC error codes
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603


class ACPServer:
    def __init__(
        self,
        agent_run: Callable[[str, dict], Iterable[dict]] | None = None,
        policy: Callable[[str], str] | None = None,
        root: Path | None = None,
    ) -> None:
        # agent_run(prompt, session) yields streaming ACP update dicts.
        self.agent_run = agent_run or self._default_agent_run
        # policy(kind) -> "allow" | "ask" | "deny"
        self.policy = policy or (lambda kind: "ask")
        self.root = root or Path.cwd()
        self.sessions: dict[str, p.Session] = {}

    # ── dispatch ──────────────────────────────────────────────────────────
    def handle(self, msg: dict) -> list[dict]:
        """Process one JSON-RPC message; return zero or more response/notification dicts."""
        if "method" not in msg:
            return [p.error(msg.get("id", 0), INVALID_REQUEST, "missing method")]
        method = msg["method"]
        mid = msg.get("id")
        params = msg.get("params") or {}

        handler = {
            "initialize": self.initialize,
            "session/new": self.session_new,
            "fs/read_text_file": self.fs_read,
            "fs/write_text_file": self.fs_write,
            "fs/list": self.fs_list,
            "session/prompt": self.session_prompt,
        }.get(method)

        if handler is None:
            if mid is not None:
                return [p.error(mid, METHOD_NOT_FOUND, f"unknown method {method}")]
            return []
        try:
            result = handler(params)
        except Exception as e:  # noqa: BLE001 - surface as JSON-RPC error
            if mid is not None:
                return [p.error(mid, INTERNAL_ERROR, str(e))]
            return []
        # Methods returning a list produce notifications (e.g. streaming prompt).
        if isinstance(result, list):
            return result
        if mid is not None:
            return [p.success(mid, result)]
        return []

    # ── methods ───────────────────────────────────────────────────────────
    def initialize(self, params: dict) -> dict:
        return {
            "protocolVersion": 1,
            "name": "sesha-acp",
            "version": "0.1.0",
            "capabilities": p.CAPABILITIES,
        }

    def session_new(self, params: dict) -> dict:
        cwd = params.get("cwd") or str(self.root)
        sid = params.get("id") or uuid.uuid4().hex[:12]
        self.sessions[sid] = p.Session(id=sid, cwd=cwd)
        return {"sessionId": sid, "cwd": cwd}

    def _resolve(self, session_id: str, path: str) -> Path:
        """Resolve a session-relative path, refusing escapes outside the cwd."""
        sess = self.sessions[session_id]
        root = Path(sess.cwd).resolve()
        pth = (root / path).resolve() if not Path(path).is_absolute() else Path(path).resolve()
        if root not in pth.parents and pth != root:
            raise PermissionError(f"path escapes session root: {path}")
        return pth

    def fs_read(self, params: dict) -> dict:
        sess = self.sessions[params["sessionId"]]
        target = self._resolve(sess.id, params["path"])
        return {"path": str(target), "text": target.read_text(errors="replace")}

    def fs_write(self, params: dict) -> dict:
        sess = self.sessions[params["sessionId"]]
        if not p.decide("fs.write", self.policy):
            return {"ok": False, "error": "permission denied"}
        target = self._resolve(sess.id, params["path"])
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(params.get("text", ""))
        return {"ok": True, "path": str(target)}

    def fs_list(self, params: dict) -> dict:
        sess = self.sessions[params["sessionId"]]
        target = self._resolve(sess.id, params.get("path", "."))
        entries = sorted(
            {"name": c.name, "dir": c.is_dir(), "size": c.stat().st_size if c.is_file() else 0}
            for c in target.iterdir()
        ) if target.exists() else []
        return {"path": str(target), "entries": entries}

    def session_prompt(self, params: dict) -> list[dict]:
        """Run an agent turn; yields streaming token updates + a final result."""
        sid = params["sessionId"]
        sess = self.sessions[sid]
        prompt = params.get("prompt", "")
        sess.history.append({"role": "user", "content": prompt})
        out: list[dict] = []
        for update in self.agent_run(prompt, {"session": sid, "cwd": sess.cwd}):
            out.append(p.notification("session/update", update))
        sess.history.append({"role": "assistant", "content": "".join(
            u.get("delta", "") for u in out if u["method"] == "session/update"
        )})
        return out

    @staticmethod
    def _default_agent_run(prompt: str, ctx: dict):
        # Echo/placeholder so the server is usable without an LLM wired in.
        yield {"type": "delta", "delta": f"(sesha-acp stub) received: {prompt}"}
        yield {"type": "done", "sessionId": ctx["session"]}
