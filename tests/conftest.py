"""
Fixtures: a fake `claude` the carabiner can start, a settings file and a
claude.json of our own, and a stand-in Margin. No test touches the real
~/.claude.json, ~/.claude/settings.json or any live service.
"""
from __future__ import annotations

import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


@pytest.fixture(autouse=True)
def own_settings(tmp_path, monkeypatch):
    """Every test gets its own claude.json and settings.json, and no real
    claude on PATH unless it puts one there."""
    cj = tmp_path / "claude.json"
    cj.write_text(json.dumps({"mcpServers": {}, "projects": {}}), encoding="utf-8")
    monkeypatch.setenv("SEREN_CLAUDE_JSON", str(cj))
    monkeypatch.setenv("SEREN_CLAUDE_SETTINGS", str(tmp_path / "settings.json"))
    monkeypatch.delenv("SEREN_CLAUDE_BIN", raising=False)
    # And Codex's: its own CODEX_HOME, never ~/.codex (where a real config.toml and auth.json live).
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "codex-home"))
    for var in ("SEREN_CODEX_BIN", "SEREN_CODEX_CONFIG", "SEREN_CODEX_HOOKS", "SEREN_KBH_WAKE"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("PATH", str(tmp_path / "nothing-here"))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "home"))
    # find_claude's last resort on Windows is C:\Users\<USERNAME>\.local\bin -
    # which is the REAL claude on a developer's box. The first run of this
    # suite started it headless (it said "Not logged in", because HOME was
    # already redirected). No test may reach the real binary.
    monkeypatch.setenv("USERNAME", "kbh-test-nobody")
    (tmp_path / "home").mkdir()
    return cj


@pytest.fixture
def fake_claude(tmp_path):
    """A stand-in `claude` that records how it was started. Returns its path
    and the file it writes. `claude mcp add-json/remove` are recorded into a
    tiny registry file so register can be checked without the real CLI."""
    out = tmp_path / "claude-calls.json"
    reg = tmp_path / "claude-registry.json"
    script = tmp_path / "fake_claude.py"
    script.write_text(f'''
import json, os, sys
argv = sys.argv[1:]
calls = json.load(open({str(out)!r})) if os.path.exists({str(out)!r}) else []
entry = {{"argv": argv, "cwd": os.getcwd(), "wake_env": os.environ.get("SEREN_KBH_WAKE")}}
if argv[:1] == ["-p"]:
    entry["stdin"] = sys.stdin.read()
    print("woken ok")
elif argv[:1] == ["mcp"]:
    registry = json.load(open({str(reg)!r})) if os.path.exists({str(reg)!r}) else {{}}
    if argv[1] == "add-json":
        registry[argv[4]] = json.loads(argv[5])
    elif argv[1] == "remove":
        registry.pop(argv[4], None)
    json.dump(registry, open({str(reg)!r}, "w"))
elif argv[:1] == ["--version"]:
    print("fake claude 0.0")
calls.append(entry)
json.dump(calls, open({str(out)!r}, "w"))
''', encoding="utf-8")
    if os.name == "nt":
        bin_ = tmp_path / "bin" / "claude.cmd"
        bin_.parent.mkdir()
        bin_.write_text(f'@"{sys.executable}" "{script}" %*\r\n', encoding="utf-8")
    else:
        bin_ = tmp_path / "bin" / "claude"
        bin_.parent.mkdir()
        bin_.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{script}" "$@"\n', encoding="utf-8")
        bin_.chmod(0o755)

    class Fake:
        path = str(bin_)
        calls_file = str(out)
        registry_file = str(reg)

        def calls(self):
            return json.load(open(out)) if out.exists() else []

        def registry(self):
            return json.load(open(reg)) if reg.exists() else {}
    return Fake()


MARGIN_DEDICATIONS = [
    {"version": 1, "text": "To whoever I am next time.", "set_at": 1790000000.0, "why": "the first page"},
    {"version": 2, "text": "To whoever I am next time: climb on.", "set_at": 1791000000.0, "why": "the clock got built"},
]
MARGIN_PREFACES = [{"version": 1, "text": "You answer Chad in the room.", "set_at": 1790500000.0, "why": "first room"}]


@pytest.fixture
def margin():
    """A stand-in Margin, shaped like the real one, behind a bearer: /health;
    /bookmark as JSON (the dedication and a COUNT of letters) and as text;
    /dedication and /preface with ?history=N, newest first. srv.state["old"]
    makes it a Margin from before the history routes (404, no history)."""
    hits = []
    state = {"old": False}

    class H(BaseHTTPRequestHandler):
        def _send(self, body, kind="application/json"):
            self.send_response(200); self.send_header("Content-Type", kind); self.end_headers()
            self.wfile.write(body if isinstance(body, bytes) else json.dumps(body).encode())

        def do_GET(self):
            hits.append((self.path, self.headers.get("Authorization")))
            if self.headers.get("Authorization") != "Bearer margin-secret":
                self.send_response(401); self.end_headers(); return
            path, _, query = self.path.partition("?")
            history = "history=" in query and not state["old"]
            ded = MARGIN_DEDICATIONS[-1]
            if path == "/health":
                return self._send({"ok": True})
            if path == "/bookmark" and "format=text" in query:
                return self._send(b"To whoever I am next time: climb on.\n\n1 unread letter.", "text/plain")
            if path == "/bookmark":
                return self._send({"dedication": ded, "unread_letters": 1, "oldest_unread_age": "2 hours ago",
                                   "text": "..."})
            if path == "/dedication" and not state["old"]:
                return self._send({"dedication": ded, **({"history": MARGIN_DEDICATIONS[::-1]} if history else {})})
            if path == "/preface":
                pf = MARGIN_PREFACES[-1]
                return self._send({"preface": pf, "version": pf["version"], "text": pf["text"],
                                   **({"history": MARGIN_PREFACES[::-1]} if history else {})})
            self.send_response(404); self.end_headers()

        def log_message(self, *a):  # quiet
            pass

    srv = HTTPServer(("127.0.0.1", 0), H)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    srv.hits = hits
    srv.state = state
    yield srv
    srv.shutdown()
