"""presence: a session tells the kitchen it is here, and gone, from a hook -
so a magnet never depends on the model remembering its first minute
(10 Nov 2026: the second session of one partner walked in blind)."""
from __future__ import annotations

import io
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from kbh import cli, config
from kbh.carabiners.claude import presence


@pytest.fixture
def kitchen():
    """A stand-in kitchen: /health, and /api/sessions behind a bearer. `mode`
    makes it an older kitchen (404) or a broken one (500)."""
    got = []

    class H(BaseHTTPRequestHandler):
        def _send(self, code, obj):
            body = json.dumps(obj).encode()
            self.send_response(code); self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)

        def do_GET(self):
            self._send(200 if self.path == "/health" else 404, {"ok": True})

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
            if srv.mode == "old":
                return self._send(404, {"detail": "Not Found"})
            if srv.mode == "broken":
                return self._send(500, {"detail": "boom"})
            if self.headers.get("Authorization") != "Bearer kitchen-secret":
                return self._send(401, {"detail": "no"})
            got.append((self.path, body))
            hand = body.get("hand") or "carabiner"
            self._send(200, {"ok": True, "label": f"{body['partner']}·{hand}", "hand": hand, "on": None, "state": "live",
                             **({"say": srv.say} if srv.say else {})})

        def log_message(self, *a):  # quiet
            pass

    srv = HTTPServer(("127.0.0.1", 0), H)
    srv.mode, srv.say, srv.got = "", "", got
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv
    srv.shutdown()


def _clip(tmp_path, capsys, kitchen=None, extra=""):
    into = tmp_path / "clip"
    cli.main(["claude", "init", "--into", str(into), "--project", str(tmp_path)])
    y = into / "claude.yaml"
    if kitchen is not None:
        y.write_text(y.read_text(encoding="utf-8") + f"kitchen:\n  url: http://127.0.0.1:{kitchen.server_address[1]}\n"
                     f"  bearer_token: kitchen-secret\n  partner: ada\n{extra}", encoding="utf-8")
    capsys.readouterr()
    return str(y)


def _hook(monkeypatch, capsys, which, yaml_path, **event):
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(event)))
    rc = cli.main(["claude", "presence", which, "--config", yaml_path])
    return rc, capsys.readouterr().out


def test_a_start_tells_the_kitchen_and_the_session_is_told_its_hand(tmp_path, kitchen, monkeypatch, capsys):
    y = _clip(tmp_path, capsys, kitchen)
    rc, out = _hook(monkeypatch, capsys, "start", y, session_id="abc-123", cwd=r"D:\work\SerenCarabiners", source="startup")
    assert rc == 0
    path, body = kitchen.got[-1]
    assert path == "/api/sessions"
    assert body["event"] == "start" and body["partner"] == "ada" and body["harness"] == "claude"
    assert body["session"] == "abc-123" and body["cwd"] == r"D:\work\SerenCarabiners" and body["source"] == "startup"
    assert body["box"] and "hand" not in body, "the hand is the kitchen's to name unless the yaml pins one"
    assert "ada·carabiner" in out and 'hand="carabiner"' in out

    kitchen.say = "You are ada·carabiner. Mind the cheese."
    _, out = _hook(monkeypatch, capsys, "start", y, session_id="abc-123", cwd="x", source="resume")
    assert out.strip() == "You are ada·carabiner. Mind the cheese.", "the kitchen's own words win"


def test_an_end_passes_the_reason_through_and_says_nothing(tmp_path, kitchen, monkeypatch, capsys):
    y = _clip(tmp_path, capsys, kitchen, extra="  hand: carabiner-2\n")
    rc, out = _hook(monkeypatch, capsys, "end", y, session_id="abc-123", reason="prompt_input_exit")
    assert rc == 0 and out == ""
    body = kitchen.got[-1][1]
    assert body == {"event": "end", "partner": "ada", "harness": "claude", "session": "abc-123",
                    "reason": "prompt_input_exit", "hand": "carabiner-2"}
    # an end with no session id names no magnet: nothing is sent
    n = len(kitchen.got)
    assert _hook(monkeypatch, capsys, "end", y)[0] == 0 and len(kitchen.got) == n


def test_it_never_fails_or_stalls_a_session(tmp_path, kitchen, monkeypatch, capsys):
    ev = dict(session_id="abc", cwd="x", source="startup")
    # no kitchen in the yaml (a corpo box): silent
    assert _hook(monkeypatch, capsys, "start", _clip(tmp_path / "a", capsys), **ev) == (0, "")
    # no config at all, or one that is not there: silent, exit 0
    assert _hook(monkeypatch, capsys, "start", str(tmp_path / "nope.yaml"), **ev) == (0, "")
    y = _clip(tmp_path / "b", capsys, kitchen)
    # a woken session holds no repo and says nothing
    monkeypatch.setenv("SEREN_KBH_WAKE", "1")
    n = len(kitchen.got)
    assert _hook(monkeypatch, capsys, "start", y, **ev) == (0, "") and len(kitchen.got) == n
    monkeypatch.delenv("SEREN_KBH_WAKE")
    # an older kitchen without the route: silent
    kitchen.mode = "old"
    assert _hook(monkeypatch, capsys, "start", y, **ev) == (0, "")
    # a kitchen that answers badly: one line, exit 0; and an end stays silent
    kitchen.mode = "broken"
    rc, out = _hook(monkeypatch, capsys, "start", y, **ev)
    assert rc == 0 and out.count("\n") == 1 and "HTTP 500" in out
    assert _hook(monkeypatch, capsys, "end", y, session_id="abc", reason="other") == (0, "")
    # a kitchen that is gone
    text = open(y, encoding="utf-8").read().replace(f":{kitchen.server_address[1]}", ":9")
    open(y, "w", encoding="utf-8").write(text)
    rc, out = _hook(monkeypatch, capsys, "start", y, **ev)
    assert rc == 0 and "did not answer" in out
    # a start with no session id (run by hand) has nothing to carry
    assert _hook(monkeypatch, capsys, "start", y) == (0, "")


def test_install_adds_both_hooks_beside_the_bookmark_and_remove_takes_only_ours(tmp_path, kitchen, margin, capsys):
    y = _clip(tmp_path, capsys, kitchen)
    settings_file = os.environ["SEREN_CLAUDE_SETTINGS"]
    from kbh.tokens import Connection, write_connection
    mconn = write_connection(str(tmp_path / "margin.yaml"), Connection(host="127.0.0.1", port=margin.server_address[1],
                                                                       bearer_token="margin-secret"))
    cli.main(["claude", "bookmark", "install", mconn])
    assert cli.main(["claude", "presence", "install", "--config", y]) == 0
    assert cli.main(["claude", "presence", "install", "--config", y]) == 0, "twice is once"
    hooks = json.load(open(settings_file))["hooks"]
    start = [h["command"] for g in hooks["SessionStart"] for h in g["hooks"]]
    end = [h["command"] for g in hooks["SessionEnd"] for h in g["hooks"]]
    assert len(start) == 2 and sum(presence.marker_in("start", c) for c in start) == 1
    assert len(end) == 1 and presence.marker_in("end", end[0]) and "kitchen-secret" not in end[0]
    capsys.readouterr()

    cli.main(["claude", "belay", "--config", y, "--json"])
    by = {(c["verb"], c["name"]): c["status"] for c in json.loads(capsys.readouterr().out)["checks"]}
    assert by[("presence", "hooks")] == "held" and by[("presence", "kitchen /health")] == "held"

    assert cli.main(["claude", "presence", "remove"]) == 0
    hooks = json.load(open(settings_file))["hooks"]
    assert "SessionEnd" not in hooks and len(hooks["SessionStart"]) == 1, "the bookmark hook is still there"
    capsys.readouterr()
    cli.main(["claude", "belay", "--config", y, "--json"])
    by = {(c["verb"], c["name"]): c for c in json.loads(capsys.readouterr().out)["checks"]}
    assert by[("presence", "hooks")]["status"] == "LET GO" and "presence install" in by[("presence", "hooks")]["why"]


def test_install_refuses_without_a_kitchen_or_a_partner_and_belay_is_silent_without_one(tmp_path, kitchen, capsys):
    bare = _clip(tmp_path / "a", capsys)
    assert cli.main(["claude", "presence", "install", "--config", bare]) == 64
    assert "kitchen" in capsys.readouterr().err
    cli.main(["claude", "belay", "--config", bare, "--json"])
    assert not [c for c in json.loads(capsys.readouterr().out)["checks"] if c["verb"] == "presence"]
    y = _clip(tmp_path / "b", capsys, kitchen)
    text = open(y, encoding="utf-8").read().replace("  partner: ada\n", "")
    open(y, "w", encoding="utf-8").write(text)
    assert cli.main(["claude", "presence", "install", "--config", y]) == 64
    assert "partner" in capsys.readouterr().err


def test_the_kitchen_block_reads_without_pyyaml_and_makes_the_yaml_a_secret(tmp_path, kitchen, monkeypatch, capsys):
    y = _clip(tmp_path, capsys, kitchen, extra="  hand: carabiner\n")
    monkeypatch.setitem(sys.modules, "yaml", None)                 # the stdlib reader
    cfg = config.load(y)
    assert cfg.partner() == "ada" and cfg.kitchen_hand() == "carabiner" and cfg.has_inline_token()
    from kbh.tokens import read_connection
    conn = read_connection(cfg.kitchen_connection())
    assert conn.resolve_token() == "kitchen-secret" and conn.port == kitchen.server_address[1]
