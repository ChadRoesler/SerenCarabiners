"""A connection is a route: the url and the token dropped into the carabiner's
yaml, nothing copied from the brain box. Files stay the on-box form."""
from __future__ import annotations

import json
import os

import pytest

from kbh import cli, config
from kbh.tokens import connection_from_route, read_connection


def test_a_route_from_a_url_and_from_host_port_and_what_it_refuses():
    c = connection_from_route({"url": "http://nuc:7255/", "bearer_token": "t"})
    assert (c.host, c.port, c.url, c.base_url, c.mcp_url) == ("nuc", 7255, "http://nuc:7255", "http://nuc:7255", "http://nuc:7255/mcp")
    assert c.to_server_block() == {"url": "http://nuc:7255", "bearer_token": "t"}
    c2 = connection_from_route({"host": "0.0.0.0", "port": 7251, "bearer_token_env": "M"})
    assert c2.base_url == "http://127.0.0.1:7251" and c2.where == "0.0.0.0:7251"
    with pytest.raises(ValueError):
        connection_from_route({"url": "http://user:pw@nuc:7255"})
    with pytest.raises(ValueError):
        connection_from_route({"url": "ftp://nuc"})
    with pytest.raises(ValueError):
        connection_from_route({"host": "nuc"})


def test_inline_routes_in_the_yaml_are_read_by_reference_with_and_without_pyyaml(tmp_path, monkeypatch):
    y = tmp_path / "claude.yaml"
    y.write_text("carabiner: claude\nproject: /p\nservers:\n  wren-workbench:\n    url: http://nuc:7255\n    bearer_token: \"wb\"\n"
                 "  other: other.yaml\nbookmark:\n  url: http://nuc:7251\n  bearer_token_env: MARGIN_TOKEN\nframing: framing.md\n",
                 encoding="utf-8")
    for by_hand in (False, True):
        if by_hand:
            monkeypatch.setattr(config, "read_yaml", lambda p: config._two_levels_by_hand(open(p, encoding="utf-8").read()))
        cfg = config.load(str(y))
        assert cfg.servers["wren-workbench"] == {"url": "http://nuc:7255", "bearer_token": "wb"}
        assert cfg.servers["other"] == "other.yaml"
        assert cfg.bookmark == {"url": "http://nuc:7251", "bearer_token_env": "MARGIN_TOKEN"}
        assert cfg.connection("wren-workbench") == f"{cfg.path}#wren-workbench"
        assert cfg.connection("bookmark") == f"{cfg.path}#bookmark"
        assert cfg.connection("other").endswith("other.yaml")
        assert cfg.has_inline_token()
        conn = read_connection(cfg.connection("wren-workbench"))
        assert conn.mcp_url == "http://nuc:7255/mcp" and conn.resolve_token() == "wb"
        monkeypatch.setenv("MARGIN_TOKEN", "from-env")
        assert read_connection(cfg.connection("bookmark")).resolve_token() == "from-env"
        with pytest.raises(KeyError):
            read_connection(f"{cfg.path}#nope")


def test_install_takes_urls_and_tokens_from_the_environment_never_argv(tmp_path, capsys, monkeypatch):
    into = tmp_path / "clip"
    monkeypatch.setenv("KBH_TOKEN_WREN_WORKBENCH", "wb-secret")
    rc = cli.main(["claude", "install", "--into", str(into), "--project", str(tmp_path), "--python", "/v/py",
                   "--server", "wren-workbench=http://nuc:7255", "--server", "loci=loci.yaml",
                   "--bookmark", "http://nuc:7251", "--bookmark-token-env", "WREN_MARGIN_TOKEN"])
    out = capsys.readouterr()
    assert rc == 0, out.out + out.err
    text = (into / "claude.yaml").read_text(encoding="utf-8")
    assert "  wren-workbench:\n    url: http://nuc:7255\n    bearer_token: wb-secret" in text, text
    assert "  loci: loci.yaml" in text
    assert "bookmark: \n  url: http://nuc:7251\n  bearer_token_env: WREN_MARGIN_TOKEN" in text, text
    assert "wb-secret" not in out.out, "the token is in the file, never in what install prints"
    if os.name != "nt":
        assert oct(os.stat(into / "claude.yaml").st_mode & 0o777) == "0o600", "an inline token makes the yaml a secret"
    cfg = config.load(str(into / "claude.yaml"))
    assert read_connection(cfg.connection("wren-workbench")).resolve_token() == "wb-secret"
    assert read_connection(cfg.connection("bookmark")).base_url == "http://nuc:7251"


def test_register_apply_and_the_headers_helper_work_from_an_inline_route(tmp_path, own_settings, fake_claude, monkeypatch, capsys):
    monkeypatch.setenv("SEREN_CLAUDE_BIN", fake_claude.path)
    monkeypatch.setenv("KBH_TOKEN_WREN_WORKBENCH", "wb-secret")
    into = tmp_path / "clip"
    cli.main(["claude", "init", "--into", str(into), "--project", str(tmp_path), "--python", "/v/py",
              "--server", "wren-workbench=http://nuc:7255"])
    monkeypatch.delenv("KBH_TOKEN_WREN_WORKBENCH")
    capsys.readouterr()
    yaml_path = str(into / "claude.yaml")
    assert cli.main(["claude", "register", "apply", "--config", yaml_path]) == 0
    entry = fake_claude.registry()["wren-workbench"]
    assert entry["url"] == "http://nuc:7255/mcp"
    assert "#wren-workbench" in entry["headersHelper"] and "wb-secret" not in json.dumps(entry)
    # the helper, run as the harness runs it, reads the route out of the yaml
    import shlex, subprocess, sys
    parts = shlex.split(entry["headersHelper"], posix=(os.name != "nt"))
    if os.name == "nt":
        parts = [p.strip('"') for p in parts]
    parts[0] = sys.executable                                   # the yaml names /v/py; this box has this one
    done = subprocess.run(parts, capture_output=True, text=True, cwd=str(tmp_path.parent.parent),
                          env={**os.environ, "PYTHONPATH": os.path.dirname(os.path.dirname(os.path.abspath(cli.__file__)))})
    assert json.loads(done.stdout) == {"Authorization": "Bearer wb-secret"}, done.stderr


def test_bookmark_and_belay_read_the_route_from_the_yaml(tmp_path, own_settings, margin, capsys):
    into = tmp_path / "clip"
    port = margin.server_address[1]
    cli.main(["claude", "init", "--into", str(into), "--project", str(tmp_path), "--bookmark", f"http://127.0.0.1:{port}"])
    # the token for the bookmark route goes in by hand here (an inline value)
    y = into / "claude.yaml"
    y.write_text(y.read_text(encoding="utf-8").replace(f"  url: http://127.0.0.1:{port}", f"  url: http://127.0.0.1:{port}\n  bearer_token: margin-secret"), encoding="utf-8")
    capsys.readouterr()
    assert cli.main(["claude", "bookmark", "print", "--config", str(y)]) == 0
    assert "climb on" in capsys.readouterr().out
    assert cli.main(["claude", "bookmark", "install", "--config", str(y)]) == 0
    hook = json.load(open(os.environ["SEREN_CLAUDE_SETTINGS"]))["hooks"]["SessionStart"][0]["hooks"][0]["command"]
    assert "#bookmark" in hook and "margin-secret" not in hook
    capsys.readouterr()
    cli.main(["claude", "belay", "--config", str(y), "--json"])
    rep = json.loads(capsys.readouterr().out)
    by = {(c["verb"], c["name"]): c for c in rep["checks"]}
    assert by[("bookmark", "margin /health")]["status"] == "held"
    assert by[("bookmark", "hook")]["status"] == "held"
