"""The Claude Code carabiner, verb by verb, against the failures of 6-7 Oct 2026."""
from __future__ import annotations

import json
import os
import shutil

import pytest

from kbh import cli
from kbh.carabiners.claude import wake
from kbh.tokens import Connection, write_connection


def _register_in_json(cj, user=None, local=None):
    data = json.load(open(cj))
    data["mcpServers"] = user or {}
    data["projects"] = local or {}
    json.dump(data, open(cj, "w"))


# ── wake ─────────────────────────────────────────────────────────────────
def test_wake_reads_the_registration_now_frames_the_message_and_finds_claude_off_path(tmp_path, own_settings, fake_claude, monkeypatch, capsys):
    proj = tmp_path / "proj"; proj.mkdir()
    _register_in_json(own_settings, user={"wren-workbench": {"type": "http", "url": "http://nuc:7255/mcp"}})
    # claude is NOT on PATH (conftest emptied it); it sits in ~/.local/bin like the installer puts it
    home_bin = tmp_path / "home" / ".local" / "bin"; home_bin.mkdir(parents=True)
    shutil.copy(fake_claude.path, home_bin / os.path.basename(fake_claude.path))
    assert wake.find_claude() and wake.find_claude().startswith(str(home_bin))

    monkeypatch.setenv("SEREN_RIPPLE_EVENT", "draft_submitted")
    rc = cli.main(["claude", "wake", "--project", str(proj), "--run", 'review "draft 15" & say why'])
    assert rc == 0
    call = fake_claude.calls()[-1]
    assert call["argv"][:3] == ["-p", "--allowedTools", "mcp__wren-workbench"]
    assert os.path.normcase(call["cwd"]) == os.path.normcase(str(proj))
    assert 'review "draft 15" & say why' in call["stdin"], "the message reaches claude on stdin, quotes and all"
    assert "Nobody is in the room" in call["stdin"] and "draft_submitted" in call["stdin"], "framed"
    assert "mcp__" not in call["stdin"] and "wren-workbench" in call["stdin"]

    # the servers change: five become one, nothing reinstalled
    _register_in_json(own_settings, user={"a": {"url": "x"}, "b": {"url": "y"}})
    cli.main(["claude", "wake", "--project", str(proj), "--run", "again", "--no-framing"])
    call = fake_claude.calls()[-1]
    assert call["argv"][2] == "mcp__a,mcp__b" and call["stdin"] == "again\n"


def test_wake_refuses_to_start_a_model_with_no_memory_or_no_binary(tmp_path, own_settings, capsys):
    proj = tmp_path / "proj"; proj.mkdir()
    assert cli.main(["claude", "wake", "--project", str(proj), "--run", "hi"]) == 2
    assert "no MCP servers" in capsys.readouterr().err
    _register_in_json(own_settings, user={"wren-workbench": {"url": "x"}})
    assert cli.main(["claude", "wake", "--project", str(proj), "--run", "hi"]) == 2
    assert "no `claude` for this account" in capsys.readouterr().err
    assert cli.main(["claude", "wake", "--project", str(tmp_path / "missing"), "--run", "hi"]) == 2


def test_wake_yaml_writes_a_command_that_is_this_carabiner_not_a_server_list(tmp_path, own_settings, capsys):
    proj = tmp_path / "proj"; proj.mkdir()
    _register_in_json(own_settings, user={"wren-workbench": {"url": "x"}})
    assert cli.main(["claude", "wake", "--project", str(proj), "--yaml", "2", "--python", "/venv/bin/python"]) == 0
    out = capsys.readouterr().out
    cmd_line = [l for l in out.splitlines() if l.startswith("  command: ")][0]
    cmd = json.loads(cmd_line.split(": ", 1)[1])
    assert cmd[0] == "/venv/bin/python" and cmd[-2:] == ["--run", "{message}"] and "claude" in cmd and "wake" in cmd
    assert "wren-workbench" not in out, "no server name frozen into the yaml"
    assert "  cwd: " in out


def test_the_framing_fills_every_slot():
    text = wake.frame("the job", ["wren-workbench"], "wake-test", when="now")
    for slot in ("{message}", "{servers}", "{event}", "{when}"):
        assert slot not in text
    assert text.rstrip().endswith("the job") and "wren-workbench" in text and "wake-test" in text


# ── register ─────────────────────────────────────────────────────────────
def test_register_writes_a_user_scope_entry_with_a_headers_helper_and_no_token(tmp_path, own_settings, fake_claude, monkeypatch, capsys):
    monkeypatch.setenv("SEREN_CLAUDE_BIN", fake_claude.path)
    conn = write_connection(str(tmp_path / "nuc" / "workbench.yaml"), Connection(host="nuc", port=7255, bearer_token="s3cret"))
    assert cli.main(["claude", "register", "add", "wren-workbench", "--connection", conn]) == 0
    reg = fake_claude.registry()
    entry = reg["wren-workbench"]
    assert entry["type"] == "http" and entry["url"] == "http://nuc:7255/mcp"
    assert "s3cret" not in json.dumps(entry), "never a token in the harness's registry"
    assert "headers" in entry["headersHelper"] and conn.replace("\\", "\\\\")[-14:] in json.dumps(entry) or "workbench.yaml" in entry["headersHelper"]
    # the helper, run the way the harness runs it, prints the header
    import shlex, subprocess
    parts = shlex.split(entry["headersHelper"], posix=(os.name != "nt"))
    if os.name == "nt":
        parts = [p.strip('"') for p in parts]
    done = subprocess.run(parts, capture_output=True, text=True)
    assert json.loads(done.stdout) == {"Authorization": "Bearer s3cret"}, done.stderr
    # and remove
    assert cli.main(["claude", "register", "remove", "wren-workbench"]) == 0
    assert "wren-workbench" not in fake_claude.registry()


def test_register_bundle_from_a_folder_of_the_brain_boxs_yamls_chads_trick(tmp_path, own_settings, fake_claude, monkeypatch):
    monkeypatch.setenv("SEREN_CLAUDE_BIN", fake_claude.path)
    src = tmp_path / "from-nuc"; src.mkdir()
    for name, port in (("seren-workbench", 7255), ("seren-margin", 7251), ("seren-memory", 7250)):
        (src / f"{name}.yaml").write_text(f"server:\n  host: 0.0.0.0\n  port: {port}\n  bearer_token: 't-{port}'\nother:\n  x: 1\n",
                                           encoding="utf-8")
    (src / "seren-margin.yaml.bak.123").write_text("server:\n  port: 1\n", encoding="utf-8")
    into = tmp_path / "nuc"
    rc = cli.main(["claude", "register", "bundle", "--from-yamls", str(src), "--host", "nuc", "--into", str(into),
                   "--prefix", "wren-", "--only", "workbench"])
    assert rc == 0
    files = sorted(p.name for p in into.glob("*.yaml"))
    assert files == ["margin.yaml", "memory.yaml", "workbench.yaml"], "a connection file per service, the .bak left out"
    assert "host: \"nuc\"" in (into / "margin.yaml").read_text() and "t-7251" in (into / "margin.yaml").read_text()
    assert list(fake_claude.registry()) == ["wren-workbench"], "only the Workbench is registered: the single door"
    assert fake_claude.registry()["wren-workbench"]["url"] == "http://nuc:7255/mcp"


def test_register_bundle_from_json(tmp_path, own_settings, fake_claude, monkeypatch):
    monkeypatch.setenv("SEREN_CLAUDE_BIN", fake_claude.path)
    b = tmp_path / "bundle.json"
    b.write_text(json.dumps({"instance": "wren", "services": {"workbench": {"host": "nuc", "port": 7255, "bearer_token_env": "WB_TOKEN"}}}))
    assert cli.main(["claude", "register", "bundle", "--from", str(b), "--into", str(tmp_path / "c"), "--prefix", "wren-"]) == 0
    assert "bearer_token_env: \"WB_TOKEN\"" in (tmp_path / "c" / "workbench.yaml").read_text()
    assert fake_claude.registry()["wren-workbench"]["url"] == "http://nuc:7255/mcp"


def test_register_list_flags_the_duplicate_across_scopes(own_settings, capsys):
    _register_in_json(own_settings, user={"wren-memory": {"url": "http://nuc:7250/mcp", "headersHelper": "x"}},
                      local={"C:/Users/alice": {"mcpServers": {"wren-memory": {"url": "http://127.0.0.1:7267/mcp", "headers": {"Authorization": "Bearer t"}}}}})
    assert cli.main(["claude", "register", "list"]) == 0
    out = capsys.readouterr().out
    assert "DUPLICATE: wren-memory" in out and "shadows" in out


# ── bookmark ─────────────────────────────────────────────────────────────
def test_bookmark_prints_from_margin_never_fails_a_session_and_installs_once(tmp_path, own_settings, margin, capsys):
    port = margin.server_address[1]
    conn = write_connection(str(tmp_path / "nuc" / "margin.yaml"), Connection(host="127.0.0.1", port=port, bearer_token="margin-secret"))
    assert cli.main(["claude", "bookmark", "print", conn]) == 0
    out = capsys.readouterr().out
    assert "picking up where you left off" in out and "climb on" in out and "1 unread letter" in out
    # wrong token: one line, exit 0, the session goes on
    bad = write_connection(str(tmp_path / "nuc" / "bad.yaml"), Connection(host="127.0.0.1", port=port, bearer_token="nope"))
    assert cli.main(["claude", "bookmark", "print", bad]) == 0
    assert "HTTP 401" in capsys.readouterr().out
    # a Margin that moved: nothing listens
    gone = write_connection(str(tmp_path / "nuc" / "gone.yaml"), Connection(host="127.0.0.1", port=9, bearer_token="x"))
    assert cli.main(["claude", "bookmark", "print", gone]) == 0
    assert "did not answer" in capsys.readouterr().out

    settings_file = os.environ["SEREN_CLAUDE_SETTINGS"]
    # the Starwright-era hook is there; ours replaces it and is installed once
    json.dump({"hooks": {"SessionStart": [{"hooks": [{"type": "command", "command": '"py" "seren-margin-bookmark.py" "old.yaml"'}]}]}},
              open(settings_file, "w"))
    assert cli.main(["claude", "bookmark", "install", conn]) == 0
    assert cli.main(["claude", "bookmark", "install", conn]) == 0
    data = json.load(open(settings_file))
    cmds = [h["command"] for g in data["hooks"]["SessionStart"] for h in g["hooks"]]
    assert len(cmds) == 1 and "bookmark" in cmds[0] and "print" in cmds[0] and "margin.yaml" in cmds[0]
    assert cli.main(["claude", "bookmark", "install", str(tmp_path / "missing.yaml")]) == 1, "refuses to install a dead hook"
    assert cli.main(["claude", "bookmark", "remove"]) == 0
    assert "hooks" not in json.load(open(settings_file))


# ── belay ────────────────────────────────────────────────────────────────
def test_belay_catches_every_failure_of_the_cutover(tmp_path, own_settings, fake_claude, margin, monkeypatch, capsys):
    proj = tmp_path / "proj"; proj.mkdir()
    port = margin.server_address[1]
    mconn = write_connection(str(tmp_path / "nuc" / "margin.yaml"), Connection(host="127.0.0.1", port=port, bearer_token="margin-secret"))

    # 1. nothing registered, no binary, no hook: let go on register and wake
    rc = cli.main(["claude", "belay", "--project", str(proj), "--margin", mconn, "--json"])
    rep = json.loads(capsys.readouterr().out)
    assert rc == 1 and rep["ok"] is False
    by = {(c["verb"], c["name"]): c for c in rep["checks"]}
    assert by[("register", "entries")]["status"] == "LET GO"
    assert by[("wake", "claude binary")]["status"] == "LET GO"
    assert by[("bookmark", "hook")]["status"] == "skipped"
    assert by[("bookmark", "margin /health")]["status"] == "held"
    assert by[("due", "channel")]["status"] == "skipped"

    # 2. the duplicate-scope mistake of 6 Oct
    _register_in_json(own_settings, user={"wren-workbench": {"url": "x"}},
                      local={str(proj): {"mcpServers": {"wren-workbench": {"url": "y"}}}})
    cli.main(["claude", "belay", "--project", str(proj), "--json"])
    rep = json.loads(capsys.readouterr().out)
    entries = [c for c in rep["checks"] if c["name"] == "entries"][0]
    assert entries["status"] == "LET GO" and "more than one scope" in entries["why"]

    # 2b. the Starwright-era hook is still a hook, and belay says what replaces it
    json.dump({"hooks": {"SessionStart": [{"hooks": [{"type": "command", "command": '"py" "seren-margin-bookmark.py" "old.yaml"'}]}]}},
              open(os.environ["SEREN_CLAUDE_SETTINGS"], "w"))
    cli.main(["claude", "belay", "--json"])
    rep = json.loads(capsys.readouterr().out)
    hook = [c for c in rep["checks"] if c["name"] == "hook"][0]
    assert hook["status"] == "held" and "Starwright-era" in hook["why"]

    # 3. everything right: one entry, a binary, a hook once, Margin answering
    monkeypatch.setenv("SEREN_CLAUDE_BIN", fake_claude.path)
    _register_in_json(own_settings, user={"wren-workbench": {"url": "x"}})
    cli.main(["claude", "bookmark", "install", mconn])
    capsys.readouterr()
    rc = cli.main(["claude", "belay", "--project", str(proj), "--margin", mconn, "--dry-wake", "--json"])
    rep = json.loads(capsys.readouterr().out)
    assert rc == 0, rep
    statuses = {(c["verb"], c["name"]): c["status"] for c in rep["checks"]}
    assert statuses[("register", "entries")] == "held"
    assert statuses[("wake", "claude binary")] == "held" and statuses[("wake", "project")] == "held"
    assert statuses[("wake", "framing")] == "held" and statuses[("wake", "claude --version")] == "held"
    assert statuses[("bookmark", "hook")] == "held" and statuses[("bookmark", "margin /health")] == "held"
    assert fake_claude.calls()[-1]["argv"] == ["--version"], "a dry wake runs the binary once and nothing else"

    # 4. the Margin moved: hook still there, Margin gone
    moved = write_connection(str(tmp_path / "nuc" / "moved.yaml"), Connection(host="127.0.0.1", port=9, bearer_token="x"))
    cli.main(["claude", "belay", "--margin", moved, "--json"])
    rep = json.loads(capsys.readouterr().out)
    assert [c for c in rep["checks"] if c["name"] == "margin /health"][0]["status"] == "LET GO"
