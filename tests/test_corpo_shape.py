"""The memory-only shape (10 Nov 2026, "Carabiners In Corpo hell"): a box with
Memory, Loci, the Corpus Callosum and the Hippocampus and nothing else. No
Workbench to be the one door, no Margin to hand over a bookmark, no Lodestar
or Observatory to carry a ripple: the harness is pointed at each service
direct, and the Hippocampus's own `script` ripple runs `kbh <harness> wake`.

What has to hold: install with four servers and no bookmark, register all
four, wake with all four pre-approved, and a belay that tries EVERY server,
because with no single door the one that is down is rarely the first."""
from __future__ import annotations

import json
import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from kbh import cli

SERVICES = ("memory", "loci", "corpus-callosum", "hippocampus")


@pytest.fixture
def brain():
    """A stand-in for a service's /mcp: answers initialize behind a bearer."""
    hits = []

    class H(BaseHTTPRequestHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers.get("Content-Length") or 0))
            hits.append((self.path, self.headers.get("Authorization")))
            if self.headers.get("Authorization") != "Bearer corpo-secret":
                self.send_response(401); self.end_headers(); return
            body = b'{"jsonrpc": "2.0", "id": 1, "result": {}}'
            self.send_response(200); self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body))); self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):  # quiet
            pass

    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    srv.hits = hits
    yield srv
    srv.shutdown()


def _install(carabiner, tmp_path, monkeypatch, capsys, port, down=""):
    """The clip for the memory-only shape; `down` names a service put on a dead port."""
    into = tmp_path / "clip"
    proj = tmp_path / "proj"; proj.mkdir(exist_ok=True)
    args = [carabiner, "install", "--into", str(into), "--project", str(proj)]
    for name in SERVICES:
        monkeypatch.setenv("KBH_TOKEN_" + name.replace("-", "_").upper(), "corpo-secret")
        args += ["--server", f"{name}=http://127.0.0.1:{9 if name == down else port}"]
    assert cli.main(args) == 0, capsys.readouterr().err
    capsys.readouterr()
    return str(into / f"{carabiner}.yaml"), proj


def _belay(carabiner, yaml_path, capsys, *more):
    rc = cli.main([carabiner, "belay", "--config", yaml_path, "--json", *more])
    return rc, json.loads(capsys.readouterr().out)


def test_claude_clips_onto_four_services_with_no_workbench_and_no_margin(tmp_path, own_settings, fake_claude, brain,
                                                                        monkeypatch, capsys):
    monkeypatch.setenv("SEREN_CLAUDE_BIN", fake_claude.path)
    yaml_path, proj = _install("claude", tmp_path, monkeypatch, capsys, brain.server_address[1])

    # register: one entry per service, each at its own /mcp, no token in any of them
    assert cli.main(["claude", "register", "apply", "--config", yaml_path]) == 0
    capsys.readouterr()
    registry = fake_claude.registry()
    assert sorted(registry) == sorted(SERVICES)
    for name in SERVICES:
        assert registry[name]["url"].endswith("/mcp") and f"#{name}" in registry[name]["headersHelper"]
    assert "corpo-secret" not in json.dumps(registry)

    # wake: what the Hippocampus's script ripple runs. All four pre-approved, nothing else needed.
    data = json.load(open(own_settings)); data["mcpServers"] = registry; json.dump(data, open(own_settings, "w"))
    assert cli.main(["claude", "wake", "--config", yaml_path, "--run", "review draft d1", "--event", "draft_submitted"]) == 0
    call = fake_claude.calls()[-1]
    assert call["argv"][:3] == ["-p", "--allowedTools", ",".join(f"mcp__{n}" for n in sorted(SERVICES))]
    assert "review draft d1" in call["stdin"] and os.path.samefile(call["cwd"], proj)
    capsys.readouterr()

    # belay: no bookmark is not a failure, and every service is tried, not only the first
    rc, rep = _belay("claude", yaml_path, capsys, "--dry-wake")
    assert rc == 0, rep
    by = {(c["verb"], c["name"]): c["status"] for c in rep["checks"]}
    assert by[("bookmark", "hook")] == "skipped"
    assert ("bookmark", "margin /health") not in by
    for name in SERVICES:
        assert by[("register", f"initialize: {name}")] == "held", by
        assert by[("register", f"headersHelper: {name}")] == "held", by
    assert len([h for h in brain.hits if h[1] == "Bearer corpo-secret"]) == len(SERVICES)


@pytest.mark.parametrize("down", ["loci", "hippocampus"])
def test_claude_belay_says_which_service_is_down_when_it_is_not_the_first(tmp_path, own_settings, fake_claude, brain,
                                                                          monkeypatch, capsys, down):
    monkeypatch.setenv("SEREN_CLAUDE_BIN", fake_claude.path)
    yaml_path, _ = _install("claude", tmp_path, monkeypatch, capsys, brain.server_address[1], down=down)
    data = json.load(open(own_settings)); data["mcpServers"] = {n: {"url": "x"} for n in SERVICES}
    json.dump(data, open(own_settings, "w"))
    rc, rep = _belay("claude", yaml_path, capsys)
    by = {(c["verb"], c["name"]): c["status"] for c in rep["checks"]}
    assert rc == 1 and by[("register", f"initialize: {down}")] == "LET GO", by
    assert all(by[("register", f"initialize: {n}")] == "held" for n in SERVICES if n != down), by


def test_one_server_keeps_the_check_names_an_upgrade_compares(tmp_path, own_settings, fake_claude, brain,
                                                             monkeypatch, capsys):
    """kbh.upgrade tells before from after by (verb, name): the single-door
    install must go on saying `connection`, `headersHelper`, `initialize`."""
    monkeypatch.setenv("SEREN_CLAUDE_BIN", fake_claude.path)
    monkeypatch.setenv("KBH_TOKEN_ADA_WORKBENCH", "corpo-secret")
    into = tmp_path / "clip"
    cli.main(["claude", "install", "--into", str(into), "--project", str(tmp_path),
              "--server", f"ada-workbench=http://127.0.0.1:{brain.server_address[1]}"])
    capsys.readouterr()
    _, rep = _belay("claude", str(into / "claude.yaml"), capsys)
    names = {c["name"] for c in rep["checks"] if c["verb"] == "register"}
    assert {"connection", "headersHelper", "initialize"} <= names, names


def test_codex_belay_tries_every_service_too(tmp_path, brain, monkeypatch, capsys):
    yaml_path, _ = _install("codex", tmp_path, monkeypatch, capsys, brain.server_address[1], down="hippocampus")
    _, rep = _belay("codex", yaml_path, capsys)
    by = {(c["verb"], c["name"]): c["status"] for c in rep["checks"]}
    assert by[("register", "initialize: hippocampus")] == "LET GO", by
    assert all(by[("register", f"initialize: {n}")] == "held" for n in SERVICES if n != "hippocampus"), by


# ── a wake approves only what the yaml names (the work box has the company's servers too) ──
def test_claude_wake_leaves_the_companys_servers_unapproved(tmp_path, own_settings, fake_claude, brain, monkeypatch, capsys):
    monkeypatch.setenv("SEREN_CLAUDE_BIN", fake_claude.path)
    yaml_path, proj = _install("claude", tmp_path, monkeypatch, capsys, brain.server_address[1])
    registered = {n: {"url": "x"} for n in SERVICES + ("jira", "company-github")}
    data = json.load(open(own_settings)); data["mcpServers"] = registered; json.dump(data, open(own_settings, "w"))

    assert cli.main(["claude", "wake", "--config", yaml_path, "--run", "review"]) == 0
    call = fake_claude.calls()[-1]
    assert call["argv"][2] == ",".join(f"mcp__{n}" for n in sorted(SERVICES)), call["argv"]
    assert "jira" not in call["stdin"] and "company-github" not in call["stdin"], "the framing names only its own"
    capsys.readouterr()

    # belay says what a wake would really approve
    _, rep = _belay("claude", yaml_path, capsys)
    project = [c for c in rep["checks"] if (c["verb"], c["name"]) == ("wake", "project")][0]
    assert project["status"] == "held" and "jira" not in project["why"], project

    # with no yaml the list is still every registered server, as it always was
    assert cli.main(["claude", "wake", "--project", str(proj), "--run", "review"]) == 0
    assert "mcp__jira" in fake_claude.calls()[-1]["argv"][2]


def test_claude_wake_refuses_when_none_of_the_yamls_servers_is_registered(tmp_path, own_settings, fake_claude, brain,
                                                                         monkeypatch, capsys):
    monkeypatch.setenv("SEREN_CLAUDE_BIN", fake_claude.path)
    yaml_path, _ = _install("claude", tmp_path, monkeypatch, capsys, brain.server_address[1])
    data = json.load(open(own_settings)); data["mcpServers"] = {"jira": {"url": "x"}}; json.dump(data, open(own_settings, "w"))
    assert cli.main(["claude", "wake", "--config", yaml_path, "--run", "review"]) == 2
    err = capsys.readouterr().err
    assert "none of them is registered" in err and "jira" in err
    assert not fake_claude.calls(), "nothing was started"


def test_codex_wake_approves_and_requires_only_the_yamls_servers(tmp_path, brain, monkeypatch, capsys):
    yaml_path, _ = _install("codex", tmp_path, monkeypatch, capsys, brain.server_address[1])
    home = tmp_path / "codex-home"; home.mkdir(exist_ok=True)
    (home / "config.toml").write_text("".join(f'[mcp_servers.{n}]\nurl = "http://x/mcp"\n\n' for n in SERVICES + ("jira",)),
                                      encoding="utf-8")
    cli.main(["codex", "wake", "--config", yaml_path, "--run", "review", "--dry"])
    plan = json.loads(capsys.readouterr().out)
    assert sorted(plan["servers"]) == sorted(SERVICES)
    assert not any("jira" in a for a in plan["argv"]), plan["argv"]
