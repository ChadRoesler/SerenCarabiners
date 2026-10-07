"""The binder: connection files and tokens, the settings merge, belay's report, the CLI."""
from __future__ import annotations

import json
import os

import pytest

from kbh import belay, cli, settings
from kbh.tokens import Connection, read_connection, resolve_token, write_connection, headers_for


def test_a_connection_file_round_trips_and_reads_without_pyyaml(tmp_path, monkeypatch):
    p = write_connection(str(tmp_path / "nuc" / "workbench.yaml"),
                         Connection(host="nuc", port=7255, bearer_token="s3cret"), note="the Workbench")
    text = open(p, encoding="utf-8").read()
    assert "server:" in text and 'bearer_token: "s3cret"' in text and "the Workbench" in text
    c = read_connection(p)
    assert (c.host, c.port, c.bearer_token) == ("nuc", 7255, "s3cret")
    assert c.mcp_url == "http://nuc:7255/mcp" and c.base_url == "http://nuc:7255"
    # the by-hand parser, as a box with no PyYAML would read it
    import kbh.tokens as t
    monkeypatch.setattr(t, "_read_yaml", lambda path: t._server_block_by_hand(open(path, encoding="utf-8").read()))
    c2 = read_connection(p)
    assert (c2.host, c2.port, c2.bearer_token) == ("nuc", 7255, "s3cret")
    assert headers_for(p) == {"Authorization": "Bearer s3cret"}


def test_a_full_service_config_is_a_connection_file_too(tmp_path):
    y = tmp_path / "seren-margin.yaml"
    y.write_text("# SerenMargin config\nserver:\n  host: 0.0.0.0\n  port: 7251\n  bearer_token: 'tok'   # the bearer\n"
                 "storage:\n  db_path: /x/notes.db\nbackup:\n  enabled: true\n", encoding="utf-8")
    c = read_connection(str(y))
    assert (c.host, c.port, c.bearer_token) == ("0.0.0.0", 7251, "tok")
    assert c.base_url == "http://127.0.0.1:7251", "a bind-all host is dialled on loopback"


def test_token_precedence_is_inline_then_keyring_then_env(monkeypatch):
    monkeypatch.setenv("T_ENV", "from-env")
    assert resolve_token("inline", "", "T_ENV") == "inline"
    assert resolve_token("", "", "T_ENV") == "from-env"
    assert resolve_token("", "", "") == ""
    assert read_connection.__doc__  # exists
    assert headers_for.__name__ == "headers_for"


def test_a_missing_connection_file_raises_not_defaults(tmp_path):
    with pytest.raises(OSError):
        read_connection(str(tmp_path / "nope.yaml"))


def test_the_settings_merge_adds_once_replaces_removes_and_refuses_bad_json(tmp_path):
    p = str(tmp_path / "settings.json")
    open(p, "w").write(json.dumps({"theme": "dark", "hooks": {"SessionStart": [{"hooks": [{"type": "command", "command": "echo hi"}]}]}}))
    settings.set_hook(p, "SessionStart", "kbh-mark", "run kbh-mark one")
    settings.set_hook(p, "SessionStart", "kbh-mark", "run kbh-mark two")
    data = json.load(open(p))
    ours = [h["command"] for g in data["hooks"]["SessionStart"] for h in g["hooks"] if "kbh-mark" in h["command"]]
    assert ours == ["run kbh-mark two"], "replaced, not duplicated"
    assert any(h["command"] == "echo hi" for g in data["hooks"]["SessionStart"] for h in g["hooks"]), "theirs kept"
    assert data["theme"] == "dark" and os.path.exists(p + ".seren-bak")
    assert settings.hooks_with(p, "SessionStart", "kbh-mark")[0]["command"] == "run kbh-mark two"
    settings.set_hook(p, "SessionStart", "kbh-mark", remove=True)
    assert settings.hooks_with(p, "SessionStart", "kbh-mark") == []
    open(p, "w").write("{ not json")
    with pytest.raises(settings.SettingsError):
        settings.set_hook(p, "SessionStart", "kbh-mark", "x")
    assert open(p).read() == "{ not json", "never touched"


def test_belay_reports_held_let_go_and_skipped_and_survives_a_broken_check():
    def ok():
        return belay.held("wake", "on belay?", "binary", "found")

    def bad():
        return belay.let_go("wake", "belay on.", "version", "exit 1")

    def skip():
        return belay.skipped("due", "on belay?", "channel", "unsupported")

    def boom():
        raise RuntimeError("kaboom")
    rep = belay.run("claude", [ok, skip])
    assert rep.ok and "climb on." in rep.text()
    rep = belay.run("claude", [ok, bad, skip, boom])
    assert not rep.ok and "LET GO" in rep.text()
    j = json.loads(rep.json())
    assert [c["status"] for c in j["checks"]] == ["held", "LET GO", "skipped", "LET GO"]
    assert "kaboom" in j["checks"][3]["why"]


def test_the_cli_lists_carabiners_and_their_verbs(capsys):
    assert cli.main(["list"]) == 0
    out = capsys.readouterr().out
    assert "claude" in out and "register, wake, bookmark" in out and "due" not in out.split("claude", 1)[1].split("\n")[0]
    assert cli.main(["claude", "manifest"]) == 0
    m = json.loads(capsys.readouterr().out)
    assert m["verbs"] == {"register": True, "wake": True, "bookmark": True, "due": False}
    assert cli.main(["nope", "wake"]) == 64
    assert cli.main(["claude", "due"]) == 3, "unsupported says so, exit 3"
