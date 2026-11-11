"""The GitHub Copilot carabiner: one file (~/.copilot/mcp-config.json) for the
Copilot CLI and Copilot in VS Code, no headers helper, and a wake only where
there is a CLI. No test touches the real ~/.copilot."""
from __future__ import annotations

import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from kbh import cli, config
from kbh.carabiners.copilot import wake
from kbh.tokens import Connection, write_connection

SOMEONE_ELSES = {"theme": "dark", "mcpServers": {"company-jira": {"type": "http", "url": "https://jira.example/mcp",
                                                                 "headers": {"X-Key": "theirs"}, "tools": ["*"]}}}


@pytest.fixture(autouse=True)
def copilot_home(tmp_path, monkeypatch):
    home = tmp_path / "copilot-home"
    home.mkdir()
    monkeypatch.setenv("SEREN_COPILOT_HOME", str(home))
    monkeypatch.delenv("SEREN_COPILOT_BIN", raising=False)
    return home


def _mcp(home):
    return json.load(open(home / "mcp-config.json", encoding="utf-8"))


@pytest.fixture
def brain():
    class H(BaseHTTPRequestHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers.get("Content-Length") or 0))
            ok = self.headers.get("Authorization") == "Bearer s3cret"
            body = b'{"jsonrpc": "2.0", "id": 1, "result": {}}'
            self.send_response(200 if ok else 401); self.send_header("Content-Length", str(len(body) if ok else 0))
            self.end_headers()
            if ok:
                self.wfile.write(body)

        def log_message(self, *a):
            pass
    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv
    srv.shutdown()


@pytest.fixture
def fake_copilot(tmp_path):
    """A stand-in `copilot` that records how it was started. A real program
    (python + script), not a .cmd: a shim is what wake refuses."""
    out = tmp_path / "copilot-calls.json"
    script = tmp_path / "fake_copilot.py"
    script.write_text(f'''
import json, os, sys
calls = json.load(open({str(out)!r})) if os.path.exists({str(out)!r}) else []
calls.append({{"argv": sys.argv[1:], "cwd": os.getcwd(), "wake_env": os.environ.get("SEREN_KBH_WAKE")}})
json.dump(calls, open({str(out)!r}, "w"))
print("copilot 0.0-fake" if sys.argv[1:] == ["--version"] else "woken ok")
''', encoding="utf-8")

    class Fake:
        script_path = str(script)

        def calls(self):
            return json.load(open(out)) if out.exists() else []
    return Fake()


def _clip(tmp_path, monkeypatch, capsys, port=7420, token="s3cret", names=("memory",)):
    into = tmp_path / "clip"
    proj = tmp_path / "proj"; proj.mkdir(exist_ok=True)
    args = ["copilot", "install", "--into", str(into), "--project", str(proj)]
    for n in names:
        if token:
            monkeypatch.setenv("KBH_TOKEN_" + n.replace("-", "_").upper(), token)
        args += ["--server", f"{n}=http://127.0.0.1:{port}"]
    assert cli.main(args) == 0
    capsys.readouterr()
    return str(into / "copilot.yaml"), proj


# ── register ─────────────────────────────────────────────────────────────
def test_register_writes_one_entry_keeps_everyone_elses_and_never_prints_the_token(tmp_path, copilot_home, capsys):
    (copilot_home / "mcp-config.json").write_text(json.dumps(SOMEONE_ELSES), encoding="utf-8")
    conn = write_connection(str(tmp_path / "memory.yaml"), Connection(host="node-a", port=7420, bearer_token="s3cret"))
    assert cli.main(["copilot", "register", "add", "memory", "--connection", conn]) == 0
    assert cli.main(["copilot", "register", "add", "memory", "--connection", conn]) == 0, "a re-register is safe"
    out = capsys.readouterr().out
    assert "s3cret" not in out and "written into that file" in out
    data = _mcp(copilot_home)
    assert data["theme"] == "dark" and data["mcpServers"]["company-jira"] == SOMEONE_ELSES["mcpServers"]["company-jira"]
    assert data["mcpServers"]["memory"] == {"type": "http", "url": "http://node-a:7420/mcp",
                                            "headers": {"Authorization": "Bearer s3cret"}, "tools": ["*"]}
    assert os.path.exists(str(copilot_home / "mcp-config.json") + ".seren-bak")
    if os.name != "nt":
        assert oct(os.stat(copilot_home / "mcp-config.json").st_mode & 0o777) == "0o600", "a token makes the file a secret"

    assert cli.main(["copilot", "register", "add", "memory", "--connection", conn, "--dry"]) == 0
    assert "s3cret" not in capsys.readouterr().out, "a dry run shows the entry, not the token"
    assert cli.main(["copilot", "register", "list"]) == 0
    assert "token in the file" in capsys.readouterr().out

    assert cli.main(["copilot", "register", "remove", "memory"]) == 0
    assert list(_mcp(copilot_home)["mcpServers"]) == ["company-jira"]


def test_a_token_kept_in_the_environment_never_reaches_copilots_file(tmp_path, copilot_home, capsys):
    conn = write_connection(str(tmp_path / "memory.yaml"), Connection(host="node-a", port=7420, bearer_token_env="SEREN_MEMORY_TOKEN"))
    assert cli.main(["copilot", "register", "add", "memory", "--connection", conn]) == 0
    assert _mcp(copilot_home)["mcpServers"]["memory"]["headers"] == {"Authorization": "Bearer ${SEREN_MEMORY_TOKEN}"}
    open_conn = write_connection(str(tmp_path / "loci.yaml"), Connection(host="node-a", port=7422))
    assert cli.main(["copilot", "register", "add", "loci", "--connection", open_conn]) == 0
    assert "headers" not in _mcp(copilot_home)["mcpServers"]["loci"], "an open service gets no header at all"


def test_register_never_touches_a_file_that_is_not_json(tmp_path, copilot_home, capsys):
    (copilot_home / "mcp-config.json").write_text("{ not json", encoding="utf-8")
    conn = write_connection(str(tmp_path / "memory.yaml"), Connection(host="node-a", port=7420))
    assert cli.main(["copilot", "register", "add", "memory", "--connection", conn]) == 2
    assert (copilot_home / "mcp-config.json").read_text(encoding="utf-8") == "{ not json"


# ── belay ────────────────────────────────────────────────────────────────
def test_belay_holds_on_an_editor_only_box_and_catches_a_stale_token_and_a_moved_service(tmp_path, copilot_home, brain,
                                                                                       monkeypatch, capsys):
    monkeypatch.setenv("PATH", str(tmp_path / "nothing"))
    y, _ = _clip(tmp_path, monkeypatch, capsys, port=brain.server_address[1])

    def belay():
        rc = cli.main(["copilot", "belay", "--config", y, "--json"])
        rep = json.loads(capsys.readouterr().out)
        return rc, {(c["verb"], c["name"]): c for c in rep["checks"]}

    rc, by = belay()                                   # nothing registered yet
    assert rc == 1 and by[("register", "entry")]["status"] == "LET GO"

    assert cli.main(["copilot", "register", "apply", "--config", y]) == 0
    capsys.readouterr()
    rc, by = belay()
    assert rc == 0, by
    assert by[("register", "entry")]["status"] == "held" and by[("register", "initialize")]["status"] == "held"
    assert by[("wake", "copilot binary")]["status"] == "skipped", "no CLI is not a failure: the editor is the install"
    assert "cannot be woken" in by[("wake", "copilot binary")]["why"]

    # the token was rotated in the yaml: the copy in Copilot's file is stale
    text = open(y, encoding="utf-8").read().replace("bearer_token: s3cret", "bearer_token: r0tated")
    open(y, "w", encoding="utf-8").write(text)
    rc, by = belay()
    assert rc == 1 and "not the one the yaml has now" in by[("register", "entry")]["why"]
    assert "r0tated" not in json.dumps(list(by.values())) and "s3cret" not in json.dumps(list(by.values()))

    # the service moved: the entry points at the old place
    text = text.replace("bearer_token: r0tated", "bearer_token: s3cret").replace(f":{brain.server_address[1]}", ":9")
    open(y, "w", encoding="utf-8").write(text)
    rc, by = belay()
    assert rc == 1 and "points at" in by[("register", "entry")]["why"]


def test_belay_says_when_the_tokens_variable_is_not_set(tmp_path, copilot_home, brain, monkeypatch, capsys):
    y, _ = _clip(tmp_path, monkeypatch, capsys, port=brain.server_address[1], token="")
    text = open(y, encoding="utf-8").read().replace(f"    url: http://127.0.0.1:{brain.server_address[1]}",
                                                    f"    url: http://127.0.0.1:{brain.server_address[1]}\n    bearer_token_env: SEREN_MEMORY_TOKEN")
    open(y, "w", encoding="utf-8").write(text)
    cli.main(["copilot", "register", "apply", "--config", y])
    capsys.readouterr()
    monkeypatch.delenv("SEREN_MEMORY_TOKEN", raising=False)
    cli.main(["copilot", "belay", "--config", y, "--json"])
    by = {(c["verb"], c["name"]): c for c in json.loads(capsys.readouterr().out)["checks"]}
    assert by[("register", "entry")]["status"] == "LET GO" and "SEREN_MEMORY_TOKEN" in by[("register", "entry")]["why"]
    monkeypatch.setenv("SEREN_MEMORY_TOKEN", "s3cret")
    cli.main(["copilot", "belay", "--config", y, "--json"])
    by = {(c["verb"], c["name"]): c for c in json.loads(capsys.readouterr().out)["checks"]}
    assert by[("register", "entry")]["status"] == "held" and by[("register", "initialize")]["status"] == "held"


# ── wake ─────────────────────────────────────────────────────────────────
def test_wake_allows_only_the_yamls_servers_and_carries_the_whole_message(tmp_path, copilot_home, fake_copilot, monkeypatch, capsys):
    y, proj = _clip(tmp_path, monkeypatch, capsys, names=("memory", "hippocampus"))
    (copilot_home / "mcp-config.json").write_text(json.dumps(SOMEONE_ELSES), encoding="utf-8")
    cli.main(["copilot", "register", "apply", "--config", y])
    capsys.readouterr()
    # the stand-in is python + a script; wake starts whatever SEREN_COPILOT_BIN names
    monkeypatch.setenv("SEREN_COPILOT_BIN", sys.executable)
    monkeypatch.setattr(wake, "command_for", lambda copilot, text, servers, model="":
                        [copilot, fake_copilot.script_path, "-p", text] + [a for s in servers for a in ("--allow-tool", s)]
                        + (["--model", model] if model else []))
    assert cli.main(["copilot", "wake", "--config", y, "--run", "review draft d1 & then nudge | done", "--event", "draft_submitted"]) == 0
    call = fake_copilot.calls()[-1]
    assert call["argv"][0] == "-p" and call["wake_env"] == "1" and os.path.samefile(call["cwd"], proj)
    message = call["argv"][1]
    assert "review draft d1 & then nudge | done" in message and "\n" in message, "the framed message arrives whole"
    assert call["argv"][2:] == ["--allow-tool", "hippocampus", "--allow-tool", "memory"], "the company's server is not allowed"


def test_wake_refuses_a_cmd_shim_no_binary_and_no_memory(tmp_path, copilot_home, monkeypatch, capsys):
    y, _ = _clip(tmp_path, monkeypatch, capsys)
    assert cli.main(["copilot", "wake", "--config", y, "--run", "x"]) == 2
    assert "kbh copilot register first" in capsys.readouterr().err
    cli.main(["copilot", "register", "apply", "--config", y])
    capsys.readouterr()
    monkeypatch.setenv("PATH", str(tmp_path / "nothing"))
    assert cli.main(["copilot", "wake", "--config", y, "--run", "x"]) == 2
    assert "only the CLI can" in capsys.readouterr().err
    monkeypatch.setattr(wake, "is_shim", lambda b: True)
    monkeypatch.setenv("SEREN_COPILOT_BIN", str(tmp_path / "copilot.cmd"))
    assert cli.main(["copilot", "wake", "--config", y, "--run", "x"]) == 2
    assert "shim" in capsys.readouterr().err
    assert wake.command_for("copilot", "hi", ["a", "b"], "m") == ["copilot", "-p", "hi", "--allow-tool", "a", "--allow-tool", "b", "--model", "m"]


def test_the_binder_knows_copilot_and_route_registers_with_it(tmp_path, copilot_home, monkeypatch, capsys):
    assert cli.main(["list"]) == 0
    assert "copilot    GitHub Copilot: register, wake" in capsys.readouterr().out
    y, _ = _clip(tmp_path, monkeypatch, capsys)
    monkeypatch.setenv("KBH_TOKEN_LOCI", "s3cret")
    import io
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))
    assert cli.main(["copilot", "route", "add", "loci", "http://127.0.0.1:7422", "--config", y]) in (0, 1)
    assert sorted(_mcp(copilot_home)["mcpServers"]) == ["loci", "memory"]
    assert cli.main(["copilot", "presence", "start"]) == 3 and cli.main(["copilot", "bookmark", "print"]) == 3
