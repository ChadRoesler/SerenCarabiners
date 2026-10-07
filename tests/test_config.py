"""How a carabiner rolls on this box: claude.yaml beside the .kbh, the framing
as a file it points at, and every verb reading it."""
from __future__ import annotations

import json
import os

from kbh import cli, config
from kbh.tokens import Connection, write_connection


def _register_in_json(cj, user):
    data = json.load(open(cj)); data["mcpServers"] = user; json.dump(data, open(cj, "w"))


def test_the_by_hand_yaml_reader_handles_two_levels_quotes_and_comments():
    text = ('# how it rolls\ncarabiner: claude\nproject: "D:\\\\work"   # the folder\npython: /v/bin/python\n'
            'servers:\n  wren-workbench: workbench.yaml\n  other: "o.yaml"\nbookmark: margin.yaml\nframing: framing.md\n'
            'wake:\n  timeout_seconds: 900\n  dry: true\n')
    d = config._two_levels_by_hand(text)
    assert d["project"] == "D:\\\\work" and d["servers"] == {"wren-workbench": "workbench.yaml", "other": "o.yaml"}
    assert d["wake"] == {"timeout_seconds": 900, "dry": True} and d["bookmark"] == "margin.yaml"


def test_init_writes_the_yaml_and_the_framing_beside_it_and_never_overwrites(tmp_path, capsys):
    into = tmp_path / "kbh"
    rc = cli.main(["claude", "init", "--into", str(into), "--project", str(tmp_path / "proj"), "--python", "/v/py",
                   "--connections", str(tmp_path / "nuc"), "--server", "wren-workbench=workbench.yaml", "--bookmark", "margin.yaml"])
    assert rc == 0
    cfg = config.load(str(into / "claude.yaml"))
    assert cfg.carabiner == "claude" and cfg.python == "/v/py" and cfg.servers == {"wren-workbench": "workbench.yaml"}
    assert cfg.bookmark == "margin.yaml" and cfg.framing == "framing.md"
    assert cfg.connection("wren-workbench") == os.path.normpath(str(tmp_path / "nuc" / "workbench.yaml"))
    assert cfg.framing_path() == os.path.normpath(str(into / "framing.md"))
    assert "Nobody is in the room" in (into / "framing.md").read_text(encoding="utf-8"), "the default, copied to edit"
    capsys.readouterr()
    (into / "framing.md").write_text("MINE: {message}\n", encoding="utf-8")
    assert cli.main(["claude", "init", "--into", str(into), "--project", "x"]) == 1, "a yaml is never overwritten"
    assert (into / "framing.md").read_text() == "MINE: {message}\n", "and neither is an edited framing"


def test_every_verb_reads_the_config_and_the_framing_is_the_file_it_names(tmp_path, own_settings, fake_claude, margin, monkeypatch, capsys):
    monkeypatch.setenv("SEREN_CLAUDE_BIN", fake_claude.path)
    proj = tmp_path / "proj"; proj.mkdir()
    nuc = tmp_path / "nuc"
    write_connection(str(nuc / "workbench.yaml"), Connection(host="nuc", port=7255, bearer_token="wb"))
    write_connection(str(nuc / "margin.yaml"), Connection(host="127.0.0.1", port=margin.server_address[1], bearer_token="margin-secret"))
    into = tmp_path / "kbh"
    cli.main(["claude", "init", "--into", str(into), "--project", str(proj), "--python", "/v/py", "--connections", str(nuc),
              "--server", "wren-workbench=workbench.yaml", "--bookmark", "margin.yaml"])
    (into / "framing.md").write_text("Woken for {event}. Memory: {servers}.\n\n{message}\n", encoding="utf-8")
    yaml_path = str(into / "claude.yaml")
    capsys.readouterr()

    # register apply: every server in the config, with the config's python in the helper
    assert cli.main(["claude", "register", "apply", "--config", yaml_path]) == 0
    entry = fake_claude.registry()["wren-workbench"]
    assert entry["url"] == "http://nuc:7255/mcp" and entry["headersHelper"].startswith('"/v/py"' if os.name == "nt" else "/v/py")
    _register_in_json(own_settings, {"wren-workbench": entry})

    # bookmark install with no argument: the config's bookmark
    assert cli.main(["claude", "bookmark", "install", "--config", yaml_path]) == 0
    hook = json.load(open(os.environ["SEREN_CLAUDE_SETTINGS"]))["hooks"]["SessionStart"][0]["hooks"][0]["command"]
    assert "margin.yaml" in hook and ('"/v/py"' in hook or hook.startswith("/v/py"))
    capsys.readouterr()
    assert cli.main(["claude", "bookmark", "print", "--config", yaml_path]) == 0
    assert "climb on" in capsys.readouterr().out

    # wake --yaml: the command names the config, not a project or a framing
    assert cli.main(["claude", "wake", "--config", yaml_path, "--yaml", "2"]) == 0
    out = capsys.readouterr().out
    cmd = json.loads([l for l in out.splitlines() if l.startswith("  command:")][0].split(": ", 1)[1])
    assert cmd[0] == "/v/py" and "--config" in cmd and cmd[cmd.index("--config") + 1] == yaml_path and "--project" not in cmd
    # wake --run: project and framing from the config, the framing being OUR file
    assert cli.main(["claude", "wake", "--config", yaml_path, "--run", "do the thing", "--event", "draft_submitted"]) == 0
    call = fake_claude.calls()[-1]
    assert os.path.normcase(call["cwd"]) == os.path.normcase(str(proj))
    assert call["stdin"] == "Woken for draft_submitted. Memory: wren-workbench.\n\ndo the thing\n"
    # a named framing that is missing refuses, rather than waking unframed
    (into / "framing.md").unlink()
    assert cli.main(["claude", "wake", "--config", yaml_path, "--run", "x"]) == 2
    assert "no such file" in capsys.readouterr().err

    # belay from the config alone
    (into / "framing.md").write_text("{message} {servers} {event} {when}", encoding="utf-8")
    monkeypatch.setattr("kbh.carabiners.claude.register.entry_for",
                        lambda path, conn, python=None: {"type": "http", "url": conn.mcp_url,
                                                          "headersHelper": f"{fake_claude.path} --version"})
    rc = cli.main(["claude", "belay", "--config", yaml_path, "--json"])
    rep = json.loads(capsys.readouterr().out)
    by = {(c["verb"], c["name"]): c["status"] for c in rep["checks"]}
    assert by[("config", "claude.yaml")] == "held"
    assert by[("wake", "project")] == "held" and by[("wake", "framing file")] == "held" and by[("wake", "framing")] == "held"
    assert by[("bookmark", "hook")] == "held" and by[("bookmark", "margin /health")] == "held"
    assert by[("register", "connection")] == "held"
    assert by[("register", "initialize")] == "LET GO", "nothing listens at nuc:7255 in a test, and belay says so"


def test_the_config_is_found_beside_the_kbh_or_in_home(tmp_path, monkeypatch):
    assert config.find("claude") is None or isinstance(config.find("claude"), str)
    home = tmp_path / "home" / ".seren" / "kbh"; home.mkdir(parents=True)
    (home / "claude.yaml").write_text("carabiner: claude\n", encoding="utf-8")
    assert config.find("claude") == str(home / "claude.yaml")
    monkeypatch.setenv("KBH_CONFIG", str(tmp_path / "x.yaml"))
    assert config.find("claude") == str(tmp_path / "x.yaml")
    assert config.find("claude", str(tmp_path / "y.yaml")) == str(tmp_path / "y.yaml")
