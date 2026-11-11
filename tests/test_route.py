"""route: a connection added, moved or dropped after the install, without
opening the yaml - what an "add service" button runs, and the whole of it on
a box with no Lodestar (10 Nov 2026)."""
from __future__ import annotations

import io
import json
import os
import sys

import pytest

from kbh import cli, config, route
from kbh.tokens import read_connection


@pytest.fixture
def clip(tmp_path, own_settings, fake_claude, monkeypatch, capsys):
    """An installed claude clip with one server, a fake claude, and nobody at the terminal."""
    monkeypatch.setenv("SEREN_CLAUDE_BIN", fake_claude.path)
    monkeypatch.setenv("KBH_TOKEN_ADA_WORKBENCH", "wb-secret")
    into = tmp_path / "clip"
    cli.main(["claude", "install", "--into", str(into), "--project", str(tmp_path),
              "--server", "ada-workbench=http://nuc:7255"])
    monkeypatch.delenv("KBH_TOKEN_ADA_WORKBENCH")
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))            # not a terminal
    capsys.readouterr()
    return str(into / "claude.yaml")


def _run(capsys, *argv):
    rc = cli.main(list(argv))
    got = capsys.readouterr()
    return rc, got.out, got.err


def test_add_a_server_writes_the_route_tells_the_harness_and_never_shows_the_token(clip, fake_claude, monkeypatch, capsys):
    before = open(clip, encoding="utf-8").read()
    monkeypatch.setenv("KBH_TOKEN_MEMORY", "mem-secret")
    rc, out, err = _run(capsys, "claude", "route", "add", "memory", "http://nuc:7420", "--config", clip)
    assert rc == 0, out + err
    assert "mem-secret" not in out + err and "added memory -> http://nuc:7420 (token: inline)" in out
    text = open(clip, encoding="utf-8").read()
    assert '  memory:\n    url: "http://nuc:7420"\n    bearer_token: mem-secret\n' in text, text
    assert all(line in text for line in before.split("\n") if line.startswith("#")), "every comment is still there"
    assert os.path.exists(clip + ".seren-bak")
    # the harness was told: both servers registered, no token in either entry
    reg = fake_claude.registry()
    assert reg["memory"]["url"] == "http://nuc:7420/mcp" and "ada-workbench" in reg
    assert "mem-secret" not in json.dumps(reg)
    assert "belay claude:" in out, "belay runs, because the yaml changed"
    # and it reads back by both readers
    assert read_connection(config.load(clip).connection("memory")).resolve_token() == "mem-secret"
    monkeypatch.setitem(sys.modules, "yaml", None)
    assert read_connection(config.load(clip).connection("memory")).resolve_token() == "mem-secret"
    assert read_connection(config.load(clip).connection("ada-workbench")).resolve_token() == "wb-secret"


def test_a_service_that_moved_keeps_its_token_and_its_place(clip, capsys):
    rc, out, _ = _run(capsys, "claude", "route", "add", "ada-workbench", "http://newbox:7255", "--config", clip, "--no-apply")
    assert rc == 0 and "changed ada-workbench" in out
    conn = read_connection(config.load(clip).connection("ada-workbench"))
    assert conn.base_url == "http://newbox:7255" and conn.resolve_token() == "wb-secret"
    assert open(clip, encoding="utf-8").read().count("\n  ada-workbench:") == 1


def test_no_token_and_nobody_to_ask_writes_nothing(clip, monkeypatch, capsys):
    before = open(clip, encoding="utf-8").read()
    rc, out, err = _run(capsys, "claude", "route", "add", "loci", "http://nuc:7422", "--config", clip)
    assert rc == 64 and "KBH_TOKEN_LOCI" in err and "--no-token" in err
    assert open(clip, encoding="utf-8").read() == before
    # a token in the url is refused the same way
    rc, _, err = _run(capsys, "claude", "route", "add", "loci", "http://me:pw@nuc:7422", "--config", clip, "--no-token")
    assert rc == 64 and "never rides in the url" in err and open(clip, encoding="utf-8").read() == before
    # the ways to say it: open, a pointer, a keyring, a person at the terminal
    assert _run(capsys, "claude", "route", "add", "loci", "http://nuc:7422", "--config", clip, "--no-token", "--no-apply")[0] == 0
    assert _run(capsys, "claude", "route", "add", "callosum", "http://nuc:7423", "--config", clip, "--token-env", "SCC_TOKEN", "--no-apply")[0] == 0
    assert _run(capsys, "claude", "route", "add", "hippo", "http://nuc:7424", "--config", clip, "--token-keyring", "seren/hippo", "--no-apply")[0] == 0
    monkeypatch.setattr(route, "_ask", lambda: "typed-secret")
    assert _run(capsys, "claude", "route", "add", "typed", "http://nuc:7999", "--config", clip, "--no-apply")[0] == 0
    cfg = config.load(clip)
    assert cfg.servers["loci"] == {"url": "http://nuc:7422"}
    assert cfg.servers["callosum"]["bearer_token_env"] == "SCC_TOKEN"
    assert cfg.servers["hippo"]["bearer_token_keyring"] == "seren/hippo"
    assert cfg.servers["typed"]["bearer_token"] == "typed-secret"


def test_list_names_how_a_token_is_kept_never_the_token(clip, capsys):
    _run(capsys, "claude", "route", "add", "loci", "http://nuc:7422", "--config", clip, "--token-env", "LOCI_T", "--no-apply")
    rc, out, _ = _run(capsys, "claude", "route", "list", "--config", clip, "--json")
    rows = {r["name"]: r for r in json.loads(out)["routes"]}
    assert rows["ada-workbench"] == {"name": "ada-workbench", "kind": "server", "where": "http://nuc:7255", "token": "inline"}
    assert rows["loci"]["token"] == "env" and "wb-secret" not in out


def test_remove_a_server_takes_it_out_of_the_yaml_and_the_harness(clip, fake_claude, monkeypatch, capsys):
    monkeypatch.setenv("KBH_TOKEN_MEMORY", "mem-secret")
    _run(capsys, "claude", "route", "add", "memory", "http://nuc:7420", "--config", clip)
    assert "memory" in fake_claude.registry()
    rc, out, _ = _run(capsys, "claude", "route", "remove", "memory", "--config", clip, "--json")
    answer = json.loads(out)
    assert rc == 0 and answer["did"] == "removed" and answer["applied"]["ok"] and "belay" in answer
    assert "memory" not in fake_claude.registry() and "ada-workbench" in fake_claude.registry()
    assert "memory" not in config.load(clip).servers and "mem-secret" not in open(clip, encoding="utf-8").read()
    assert _run(capsys, "claude", "route", "remove", "memory", "--config", clip)[0] == 1, "not there: say so"


def test_the_kitchen_and_the_bookmark_are_routes_too_and_get_their_hooks(clip, margin, monkeypatch, capsys):
    settings_file = os.environ["SEREN_CLAUDE_SETTINGS"]
    monkeypatch.setenv("KBH_TOKEN_KITCHEN", "kitchen-secret")
    assert _run(capsys, "claude", "route", "add", "kitchen", "http://nuc:7261", "--config", clip)[0] == 64, "whose sessions?"
    rc, out, _ = _run(capsys, "claude", "route", "add", "kitchen", "http://nuc:7261", "--config", clip, "--partner", "ada")
    assert rc == 0, out
    cfg = config.load(clip)
    assert cfg.partner() == "ada" and read_connection(cfg.kitchen_connection()).resolve_token() == "kitchen-secret"
    hooks = json.load(open(settings_file))["hooks"]
    assert "SessionStart" in hooks and "SessionEnd" in hooks
    # moved: the partner and the token stay
    monkeypatch.delenv("KBH_TOKEN_KITCHEN")
    assert _run(capsys, "claude", "route", "add", "kitchen", "http://nuc:9999", "--config", clip, "--hand", "desk")[0] == 0
    cfg = config.load(clip)
    assert cfg.kitchen == {"url": "http://nuc:9999", "bearer_token": "kitchen-secret", "partner": "ada", "hand": "desk"}

    monkeypatch.setenv("KBH_TOKEN_BOOKMARK", "margin-secret")
    assert _run(capsys, "claude", "route", "add", "bookmark", f"http://127.0.0.1:{margin.server_address[1]}", "--config", clip)[0] == 0
    start = [h["command"] for g in json.load(open(settings_file))["hooks"]["SessionStart"] for h in g["hooks"]]
    assert len(start) == 2 and any("#bookmark" in c for c in start)
    assert open(clip, encoding="utf-8").read().count("\nbookmark:") == 1, "the blank bookmark line was replaced, not doubled"

    assert _run(capsys, "claude", "route", "remove", "kitchen", "--config", clip)[0] == 0
    assert _run(capsys, "claude", "route", "remove", "bookmark", "--config", clip)[0] == 0
    assert "hooks" not in json.load(open(settings_file))
    cfg = config.load(clip)
    assert not cfg.kitchen and not cfg.bookmark and "ada-workbench" in cfg.servers


def test_codex_takes_a_route_the_same_way(tmp_path, monkeypatch, capsys):
    into = tmp_path / "clip"
    cli.main(["codex", "install", "--into", str(into), "--project", str(tmp_path)])
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))
    monkeypatch.setenv("KBH_TOKEN_MEMORY", "mem-secret")
    capsys.readouterr()
    y = str(into / "codex.yaml")
    rc, out, err = _run(capsys, "codex", "route", "add", "memory", "http://nuc:7420", "--config", y)
    assert rc == 0, out + err
    toml = open(os.path.join(os.environ["CODEX_HOME"], "config.toml"), encoding="utf-8").read()
    assert "[mcp_servers.memory]" in toml and "mem-secret" not in toml
    # codex has no presence: the kitchen is written, and it says nothing else was done
    rc, out, _ = _run(capsys, "codex", "route", "add", "kitchen", "http://nuc:7261", "--config", y, "--partner", "ada", "--no-token")
    assert rc == 0 and "has no presence" in out and config.load(y).partner() == "ada"
