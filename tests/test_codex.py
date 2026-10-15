"""The Codex carabiner, verb by verb: the second harness, held to what the
first one learned - and to what codex-cli 0.162.1 does with its config."""
from __future__ import annotations

import json
import os
import sys

import pytest

from kbh import cli
from kbh.carabiners.codex import common, run_like_codex, wake
from kbh.tokens import Connection, write_connection

USER_CONFIG = '''# Codex, as a person left it
model = "gpt-5.3-codex"
approval_policy = "on-request"

[mcp_servers.someone-elses]
command = "npx"
args = ["-y", "their-server"]

[mcp_servers.someone-elses.env]
A = "1"

[profiles.fast]
model = "gpt-5.3-codex-mini"
'''


@pytest.fixture
def fake_codex(tmp_path):
    """A stand-in `codex` that records how it was started."""
    out = tmp_path / "codex-calls.json"
    script = tmp_path / "fake_codex.py"
    script.write_text(f'''
import json, os, sys
argv = sys.argv[1:]
calls = json.load(open({str(out)!r})) if os.path.exists({str(out)!r}) else []
entry = {{"argv": argv, "cwd": os.getcwd(), "wake_env": os.environ.get("SEREN_KBH_WAKE")}}
if argv[:1] == ["exec"]:
    entry["stdin"] = sys.stdin.read()
    print("woken ok")
elif argv[:1] == ["--version"]:
    print("codex-cli 0.0.0-fake")
calls.append(entry)
json.dump(calls, open({str(out)!r}, "w"))
''', encoding="utf-8")
    if os.name == "nt":
        bin_ = tmp_path / "bin" / "codex.cmd"
        bin_.parent.mkdir()
        bin_.write_text(f'@"{sys.executable}" "{script}" %*\r\n', encoding="utf-8")
    else:
        bin_ = tmp_path / "bin" / "codex"
        bin_.parent.mkdir()
        bin_.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{script}" "$@"\n', encoding="utf-8")
        bin_.chmod(0o755)

    class Fake:
        path = str(bin_)

        def calls(self):
            return json.load(open(out)) if out.exists() else []
    return Fake()


def _config_toml():
    return os.path.join(os.environ["CODEX_HOME"], "config.toml")


def _write_user_config(text=USER_CONFIG):
    os.makedirs(os.environ["CODEX_HOME"], exist_ok=True)
    with open(_config_toml(), "w", encoding="utf-8", newline="") as f:
        f.write(text)


# ── register ─────────────────────────────────────────────────────────────
def test_register_writes_a_table_with_a_headers_helper_keeps_the_rest_and_replaces_not_duplicates(tmp_path):
    _write_user_config()
    conn = write_connection(str(tmp_path / "node-a" / "workbench.yaml"),
                            Connection(host="node-a", port=7255, bearer_token="s3cret"))
    assert cli.main(["codex", "register", "add", "wren-workbench", "--connection", conn]) == 0
    assert cli.main(["codex", "register", "add", "wren-workbench", "--connection", conn]) == 0, "a re-register is safe"
    text = open(_config_toml(), encoding="utf-8").read()
    assert "s3cret" not in text, "never a token in Codex's config"
    assert text.count("[mcp_servers.wren-workbench]") == 1, "replaced, not duplicated"
    assert text.count("# written by kbh codex register") == 1, "our note goes with our table"
    for kept in ('model = "gpt-5.3-codex"', "[mcp_servers.someone-elses]", "[mcp_servers.someone-elses.env]",
                 'A = "1"', "[profiles.fast]"):
        assert kept in text, f"someone else's line went: {kept}"
    servers = common.parse_servers(text)
    assert servers["wren-workbench"]["url"] == "http://node-a:7255/mcp"
    assert servers["wren-workbench"]["startup_timeout_sec"] == 30
    helper = servers["wren-workbench"]["http_headers_helper"]
    assert "codex" in helper and "headers" in helper and "workbench.yaml" in helper
    assert os.path.exists(_config_toml() + ".seren-bak")

    # the helper, run the way Codex runs it (a shell, the environment cut down), prints the header
    done = run_like_codex(helper)
    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout) == {"Authorization": "Bearer s3cret"}

    assert cli.main(["codex", "register", "remove", "wren-workbench"]) == 0
    text = open(_config_toml(), encoding="utf-8").read()
    assert "wren-workbench" not in text and "kbh codex" not in text
    assert "[mcp_servers.someone-elses.env]" in text and "[profiles.fast]" in text


def test_register_from_the_yaml_with_an_inline_route_points_the_helper_at_the_yaml(tmp_path, monkeypatch):
    monkeypatch.setenv("KBH_TOKEN_WREN_WORKBENCH", "r0ute")
    into = tmp_path / "clip"
    assert cli.main(["codex", "install", "--into", str(into), "--project", str(tmp_path), "--python", sys.executable,
                     "--server", "wren-workbench=http://192.0.2.10:7255"]) == 0
    yaml = str(into / "codex.yaml")
    assert cli.main(["codex", "register", "apply", "--config", yaml]) == 0
    entry = common.servers_in(_config_toml())["wren-workbench"]
    assert entry["url"] == "http://192.0.2.10:7255/mcp"
    assert "codex.yaml#wren-workbench" in entry["http_headers_helper"]
    assert "r0ute" not in open(_config_toml(), encoding="utf-8").read()
    done = run_like_codex(entry["http_headers_helper"])
    assert json.loads(done.stdout) == {"Authorization": "Bearer r0ute"}, done.stderr


def test_a_bearer_token_env_route_cannot_reach_the_helper_and_belay_says_why(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("WB_TOKEN", "from-env")
    conn = tmp_path / "workbench.yaml"
    conn.write_text('server:\n  host: "node-a"\n  port: 7255\n  bearer_token_env: "WB_TOKEN"\n', encoding="utf-8")
    assert cli.main(["codex", "register", "add", "wren-workbench", "--connection", str(conn)]) == 0
    capsys.readouterr()
    cli.main(["codex", "belay", "--connection", str(conn), "--json"])
    rep = json.loads(capsys.readouterr().out)
    helper = [c for c in rep["checks"] if c["name"] == "headers helper"][0]
    assert helper["status"] == "LET GO" and "clears the helper's environment" in helper["why"]


def test_register_refuses_a_config_it_cannot_edit_safely(tmp_path, capsys):
    conn = write_connection(str(tmp_path / "w.yaml"), Connection(host="node-a", port=7255, bearer_token="t"))
    _write_user_config('mcp_servers.other.url = "http://192.0.2.1/mcp"\n')
    before = open(_config_toml(), encoding="utf-8").read()
    assert cli.main(["codex", "register", "add", "wren-workbench", "--connection", conn]) == 2
    assert "inline table or dotted keys" in capsys.readouterr().err
    assert open(_config_toml(), encoding="utf-8").read() == before, "not touched"
    if common._toml is not None:
        _write_user_config('model = "unterminated\n')
        assert cli.main(["codex", "register", "add", "wren-workbench", "--connection", conn]) == 2
        assert "not valid TOML" in capsys.readouterr().err
    assert cli.main(["codex", "register", "add", "wren.workbench", "--connection", conn]) == 64


def test_the_hand_parser_reads_what_tomllib_reads(monkeypatch):
    text = USER_CONFIG + '\n[mcp_servers.w]\nurl = "http://x/mcp"\nenabled = false\nstartup_timeout_sec = 30\n'
    real = common.parse_servers(text)
    monkeypatch.setattr(common, "_toml", None)
    by_hand = common.parse_servers(text)
    assert set(by_hand) == set(real) == {"someone-elses", "w"}
    assert by_hand["w"] == real["w"] == {"url": "http://x/mcp", "enabled": False, "startup_timeout_sec": 30}


def test_register_list_says_how_each_server_authenticates(tmp_path, capsys):
    _write_user_config(USER_CONFIG + '\n[mcp_servers.leaky]\nurl = "http://192.0.2.2/mcp"\nhttp_headers = { Authorization = "Bearer x" }\n')
    conn = write_connection(str(tmp_path / "w.yaml"), Connection(host="node-a", port=7255, bearer_token="t"))
    cli.main(["codex", "register", "add", "wren-workbench", "--connection", conn])
    capsys.readouterr()
    assert cli.main(["codex", "register", "list"]) == 0
    out = capsys.readouterr().out
    assert "headers helper" in out and "INLINE headers" in out and "stdio" in out


# ── wake ─────────────────────────────────────────────────────────────────
def test_wake_reads_the_servers_now_approves_them_for_the_run_only_and_frames_the_message(tmp_path, fake_codex, monkeypatch):
    proj = tmp_path / "proj"; proj.mkdir()
    _write_user_config(USER_CONFIG + '\n[mcp_servers.wren-workbench]\nurl = "http://node-a:7255/mcp"\n'
                       '\n[mcp_servers.parked]\nurl = "http://192.0.2.3/mcp"\nenabled = false\n')
    monkeypatch.setenv("SEREN_CODEX_BIN", fake_codex.path)
    monkeypatch.setenv("SEREN_RIPPLE_EVENT", "draft_submitted")
    before = open(_config_toml(), encoding="utf-8").read()
    rc = cli.main(["codex", "wake", "--project", str(proj), "--run", 'review "draft 15" & say why'])
    assert rc == 0
    call = fake_codex.calls()[-1]
    argv = call["argv"]
    assert argv[:2] == ["exec", "--skip-git-repo-check"] and argv[-1] == "-", "the message goes on stdin"
    assert os.path.normcase(argv[argv.index("-C") + 1]) == os.path.normcase(str(proj))
    sets = [argv[i + 1] for i, a in enumerate(argv) if a == "-c"]
    assert "mcp_servers.wren-workbench.default_tools_approval_mode=approve" in sets
    assert "mcp_servers.wren-workbench.required=true" in sets
    assert not any("parked" in s for s in sets), "a disabled server is not asked for"
    assert "--sandbox" not in argv, "exec's read-only default stands"
    assert 'review "draft 15" & say why' in call["stdin"] and "Nobody is in the room" in call["stdin"]
    assert "draft_submitted" in call["stdin"] and "someone-elses" in call["stdin"]
    assert call["wake_env"] == "1"
    assert open(_config_toml(), encoding="utf-8").read() == before, "approval is for the run, config.toml untouched"


def test_wake_refuses_to_start_a_model_with_no_memory_or_no_binary(tmp_path, capsys):
    proj = tmp_path / "proj"; proj.mkdir()
    assert cli.main(["codex", "wake", "--project", str(proj), "--run", "hi"]) == 2
    assert "no Codex config" in capsys.readouterr().err
    _write_user_config('model = "m"\n')
    assert cli.main(["codex", "wake", "--project", str(proj), "--run", "hi"]) == 2
    assert "no MCP servers are enabled" in capsys.readouterr().err
    _write_user_config('[mcp_servers.wren-workbench]\nurl = "http://node-a:7255/mcp"\n')
    assert cli.main(["codex", "wake", "--project", str(proj), "--run", "hi"]) == 2
    assert "no `codex` for this account" in capsys.readouterr().err


def test_wake_puts_the_bookmark_in_the_message_and_the_hook_stays_quiet(tmp_path, fake_codex, margin, monkeypatch, capsys):
    proj = tmp_path / "proj"; proj.mkdir()
    _write_user_config('[mcp_servers.wren-workbench]\nurl = "http://node-a:7255/mcp"\n')
    port = margin.server_address[1]
    mconn = write_connection(str(tmp_path / "node-a" / "margin.yaml"),
                             Connection(host="127.0.0.1", port=port, bearer_token="margin-secret"))
    into = tmp_path / "clip"
    assert cli.main(["codex", "install", "--into", str(into), "--project", str(proj), "--python", sys.executable,
                     "--bookmark", mconn]) == 0
    monkeypatch.setenv("SEREN_CODEX_BIN", fake_codex.path)
    assert cli.main(["codex", "wake", "--config", str(into / "codex.yaml"), "--run", "the job"]) == 0
    stdin = fake_codex.calls()[-1]["stdin"]
    assert stdin.index("climb on") < stdin.index("Nobody is in the room") < stdin.index("the job")
    capsys.readouterr()
    monkeypatch.setenv("SEREN_KBH_WAKE", "1")
    assert cli.main(["codex", "bookmark", "print", mconn]) == 0
    assert capsys.readouterr().out == "", "inside a wake the hook prints nothing: the bookmark is already there"


def test_wake_yaml_writes_a_command_that_is_this_carabiner_not_a_server_list(tmp_path, capsys):
    proj = tmp_path / "proj"; proj.mkdir()
    _write_user_config('[mcp_servers.wren-workbench]\nurl = "http://node-a:7255/mcp"\n')
    assert cli.main(["codex", "wake", "--project", str(proj), "--yaml", "2", "--python", "/venv/bin/python"]) == 0
    out = capsys.readouterr().out
    cmd = json.loads([l for l in out.splitlines() if l.startswith("  command: ")][0].split(": ", 1)[1])
    assert cmd[0] == "/venv/bin/python" and cmd[-2:] == ["--run", "{message}"] and cmd[cmd.index("wake") - 1] == "codex"
    assert "wren-workbench" not in out


def test_an_npm_shim_is_followed_to_the_binary(tmp_path, monkeypatch):
    if os.name != "nt":
        pytest.skip("the .cmd shim is Windows'")
    npm = tmp_path / "home" / "AppData" / "Roaming" / "npm"
    exe = npm / "node_modules" / "@openai" / "codex" / "node_modules" / "@openai" / "codex-win32-x64" / "vendor" / \
        "x86_64-pc-windows-msvc" / "bin" / "codex.exe"
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"")
    (npm / "codex.cmd").write_text("@node codex.js %*\r\n", encoding="utf-8")
    assert os.path.normcase(wake.find_codex()) == os.path.normcase(str(exe))


# ── bookmark ─────────────────────────────────────────────────────────────
def test_bookmark_installs_one_session_start_hook_with_a_matcher_and_never_fails(tmp_path, margin, capsys):
    port = margin.server_address[1]
    conn = write_connection(str(tmp_path / "node-a" / "margin.yaml"),
                            Connection(host="127.0.0.1", port=port, bearer_token="margin-secret"))
    assert cli.main(["codex", "bookmark", "print", conn]) == 0
    assert "climb on" in capsys.readouterr().out
    gone = write_connection(str(tmp_path / "gone.yaml"), Connection(host="127.0.0.1", port=9, bearer_token="x"))
    assert cli.main(["codex", "bookmark", "print", gone]) == 0
    assert "did not answer" in capsys.readouterr().out

    hooks = os.path.join(os.environ["CODEX_HOME"], "hooks.json")
    os.makedirs(os.environ["CODEX_HOME"], exist_ok=True)
    json.dump({"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "theirs"}]}]}}, open(hooks, "w"))
    assert cli.main(["codex", "bookmark", "install", conn]) == 0
    assert cli.main(["codex", "bookmark", "install", conn]) == 0
    assert "trust it under /hooks" in capsys.readouterr().out
    data = json.load(open(hooks))
    groups = data["hooks"]["SessionStart"]
    assert len(groups) == 1 and groups[0]["matcher"] == "startup|resume"
    h = groups[0]["hooks"][0]
    assert "bookmark" in h["command"] and "margin.yaml" in h["command"] and h["timeout"] == 15
    assert data["hooks"]["Stop"][0]["hooks"][0]["command"] == "theirs", "someone else's hook stays"
    # the hook, run the way Codex runs a command, prints the bookmark
    done = run_like_codex(h["command"])
    assert "climb on" in done.stdout, done.stderr
    assert cli.main(["codex", "bookmark", "remove"]) == 0
    assert "SessionStart" not in json.load(open(hooks))["hooks"]


# ── belay ────────────────────────────────────────────────────────────────
def test_belay_lets_go_with_nothing_and_holds_when_it_is_all_there(tmp_path, fake_codex, margin, monkeypatch, capsys):
    proj = tmp_path / "proj"; proj.mkdir()
    port = margin.server_address[1]
    mconn = write_connection(str(tmp_path / "node-a" / "margin.yaml"),
                             Connection(host="127.0.0.1", port=port, bearer_token="margin-secret"))
    rc = cli.main(["codex", "belay", "--project", str(proj), "--margin", mconn, "--json"])
    rep = json.loads(capsys.readouterr().out)
    by = {(c["verb"], c["name"]): c["status"] for c in rep["checks"]}
    assert rc == 1 and by[("register", "entries")] == "LET GO" and by[("wake", "codex binary")] == "LET GO"
    assert by[("bookmark", "hook")] == "skipped" and by[("due", "channel")] == "skipped"

    monkeypatch.setenv("SEREN_CODEX_BIN", fake_codex.path)
    _write_user_config('[mcp_servers.wren-workbench]\nurl = "http://node-a:7255/mcp"\nhttp_headers_helper = "x"\n')
    cli.main(["codex", "bookmark", "install", mconn])
    capsys.readouterr()
    rc = cli.main(["codex", "belay", "--project", str(proj), "--margin", mconn, "--dry-wake", "--json"])
    rep = json.loads(capsys.readouterr().out)
    by = {(c["verb"], c["name"]): c["status"] for c in rep["checks"]}
    assert rc == 0, rep
    assert by[("register", "entries")] == by[("wake", "project")] == by[("wake", "codex --version")] == "held"
    assert by[("bookmark", "hook")] == by[("bookmark", "margin /health")] == "held"
    assert fake_codex.calls()[-1]["argv"] == ["--version"]

    _write_user_config('[mcp_servers.wren-workbench]\nurl = "http://node-a:7255/mcp"\nbearer_token = "oops"\n')
    cli.main(["codex", "belay", "--json"])
    rep = json.loads(capsys.readouterr().out)
    entries = [c for c in rep["checks"] if c["name"] == "entries"][0]
    assert entries["status"] == "LET GO" and "token written into config.toml" in entries["why"]
