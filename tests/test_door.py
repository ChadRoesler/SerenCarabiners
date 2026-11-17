"""kbh.door and the migration: what a session reads at the door, put together
from the piton and Margin; the pages taken over from Margin with every
version, once; nothing lost on the way across."""
from __future__ import annotations

import json
import os

import pytest

from kbh import cli, config, door
from kbh import piton as P
from kbh.tokens import Connection, write_connection


@pytest.fixture
def box(tmp_path, margin, monkeypatch):
    """A carabiner yaml with a piton and a `bookmark:` route to the stand-in Margin."""
    monkeypatch.delenv(P.ENV, raising=False)
    for v in P.SESSION_ENV + ("KBH_AS",):
        monkeypatch.delenv(v, raising=False)
    conn = write_connection(str(tmp_path / "routes" / "margin.yaml"),
                            Connection(host="127.0.0.1", port=margin.server_address[1], bearer_token="margin-secret"))
    clip = tmp_path / "clip"
    clip.mkdir()
    (clip / "claude.yaml").write_text(
        f"carabiner: claude\nproject: {json.dumps(str(tmp_path))}\nbookmark: {json.dumps(conn)}\n"
        f"piton: {json.dumps(str(tmp_path / 'piton'))}\n", encoding="utf-8")
    cfg = config.load(str(clip / "claude.yaml"))
    p = P.Piton(cfg.piton_dir())
    p.make()
    return cfg, p, conn


# ── the transition: no session walks in without its dedication ──

def test_before_the_import_margins_copy_is_shown_and_says_so(box):
    cfg, p, _ = box
    out = door.text(cfg, "claude")
    assert "climb on." in out and "still Margin's copy" in out and "piton import" in out
    assert "1 unread letter from your other sessions, the oldest from 2 hours ago" in out


def test_after_the_import_the_pitons_page_is_shown(box):
    cfg, p, conn = box
    lines, ok = door.import_from_margin(p, conn, "claude")
    assert ok, lines
    out = door.text(cfg, "claude")
    assert "Your dedication (version 2" in out and "climb on." in out and "Margin's copy" not in out
    assert "1 unread letter" in out


# ── the import ──

def test_every_version_comes_across_with_its_date_and_why(box):
    _, p, conn = box
    lines, ok = door.import_from_margin(p, conn, "claude")
    assert ok and "dedication: 2 versions from Margin; the page is version 2" in lines
    h = p.history("dedication")
    assert [v["text"] for v in h] == ["To whoever I am next time: climb on.", "To whoever I am next time."]
    assert [v["why"] for v in h] == ["the clock got built", "the first page"]
    assert [v["set_at"] for v in h] == [1791000000.0, 1790000000.0] and {v["by"] for v in h} == {"margin"}
    assert p.read("preface")["text"] == "You answer Chad in the room."
    assert P.is_locked(p.page_path("dedication"))


def test_the_import_runs_once_and_never_clobbers(box):
    _, p, conn = box
    door.import_from_margin(p, conn, "claude")
    p.set("dedication", "written since, on the piton")
    lines, ok = door.import_from_margin(p, conn, "claude")
    assert ok and any(line.startswith("dedication: kept") for line in lines)
    assert p.read("dedication")["text"] == "written since, on the piton"


def test_a_page_written_by_hand_before_the_import_is_kept(box):
    _, p, conn = box
    P._set_locked(p.page_path("dedication"), False)
    open(p.page_path("dedication"), "w", encoding="utf-8").write("typed in before the import")
    lines, _ = door.import_from_margin(p, conn, "claude")
    assert any(line.startswith("dedication: kept") for line in lines)
    assert p.read("dedication")["text"] == "typed in before the import"


def test_an_older_margin_imports_nothing_and_says_what_to_do(box, margin):
    _, p, conn = box
    margin.state["old"] = True
    lines, ok = door.import_from_margin(p, conn, "claude")
    assert not ok and p.latest("dedication") is None
    assert "older than its history routes" in lines[0] and "piton import" in lines[0]


def test_a_margin_that_is_down_imports_nothing(box, tmp_path):
    _, p, _ = box
    gone = write_connection(str(tmp_path / "routes" / "gone.yaml"), Connection(host="127.0.0.1", port=9, bearer_token="x"))
    lines, ok = door.import_from_margin(p, gone, "claude")
    assert not ok and p.latest("dedication") is None and "did not answer" in lines[0]


def test_the_verb_imports(box, capsys):
    cfg, p, _ = box
    assert cli.main(["claude", "piton", "import", "--config", cfg.path]) == 0
    assert "2 versions from Margin" in capsys.readouterr().out
    assert p.read("dedication")["version"] == 2


def test_install_imports_when_there_is_a_margin(tmp_path, margin, capsys, monkeypatch):
    monkeypatch.delenv(P.ENV, raising=False)
    conn = write_connection(str(tmp_path / "routes" / "margin.yaml"),
                            Connection(host="127.0.0.1", port=margin.server_address[1], bearer_token="margin-secret"))
    assert cli.main(["claude", "install", "--into", str(tmp_path / "clip"), "--project", str(tmp_path),
                     "--python", "/v/py", "--bookmark", conn]) == 0
    out = capsys.readouterr().out
    assert "piton: dedication: 2 versions from Margin" in out and "piton: preface: 1 version from Margin" in out
    capsys.readouterr()
    assert cli.main(["claude", "install", "--into", str(tmp_path / "clip"), "--project", "x"]) == 0
    assert "from Margin" not in capsys.readouterr().out          # once: a re-install leaves it be


def test_install_with_margin_down_still_installs(tmp_path, capsys, monkeypatch):
    monkeypatch.delenv(P.ENV, raising=False)
    gone = write_connection(str(tmp_path / "routes" / "gone.yaml"), Connection(host="127.0.0.1", port=9, bearer_token="x"))
    assert cli.main(["claude", "install", "--into", str(tmp_path / "clip"), "--project", str(tmp_path),
                     "--python", "/v/py", "--bookmark", gone]) == 0
    assert "piton import" in capsys.readouterr().out


# ── what the door shows ──

def test_no_margin_is_the_dedication_and_no_letters_line(tmp_path, monkeypatch):
    monkeypatch.delenv(P.ENV, raising=False)
    (tmp_path / "claude.yaml").write_text(f"carabiner: claude\npiton: {json.dumps(str(tmp_path / 'pt'))}\n",
                                          encoding="utf-8")
    cfg = config.load(str(tmp_path / "claude.yaml"))
    P.Piton(cfg.piton_dir()).set("dedication", "a box with no Margin")
    out = door.text(cfg, "claude")
    assert "a box with no Margin" in out and "letter" not in out


def test_margin_down_costs_the_letters_not_the_dedication(box, tmp_path):
    cfg, p, _ = box
    p.set("dedication", "still here")
    gone = write_connection(str(tmp_path / "routes" / "gone.yaml"), Connection(host="127.0.0.1", port=9, bearer_token="x"))
    out = door.text(cfg, "claude", margin=gone)
    assert "still here" in out and "letters are unavailable" in out


def test_the_preface_only_where_asked_and_never_on_a_wake(box):
    cfg, p, _ = box
    p.set("dedication", "me")
    p.set("preface", "the room", by="operator")
    assert "the room" not in door.text(cfg, "claude")
    cfg.extra["piton_preface"] = True
    out = door.text(cfg, "claude")
    assert "The room (preface, version 1):\nthe room" in out
    assert out.index("The room") < out.index("Your dedication"), "the room first, then who walks into it"
    assert "the room" not in door.text(cfg, "claude", woken=True)


def test_off_shows_no_dedication_not_even_margins(box):
    cfg, p, _ = box
    open(p.yaml_path, "w", encoding="utf-8").write("schema: 1\ndedication: off\n")
    out = door.text(cfg, "claude")
    assert "climb on" not in out and "No dedication yet" not in out and "1 unread letter" in out


def test_a_piton_problem_is_a_line_not_a_crash(box):
    cfg, p, _ = box
    p.set("dedication", "good")
    P._set_locked(p.page_path("dedication"), False)
    open(p.page_path("dedication"), "w", encoding="utf-8").write("x" * 3000)
    out = door.text(cfg, "claude")
    assert "good" in out and "(piton: dedication.md is 3000 characters" in out


# ── the hooks ──

def test_the_claude_hook_prints_the_door(box, capsys):
    cfg, p, _ = box
    p.set("dedication", "from the piton")
    assert cli.main(["claude", "bookmark", "print", "--config", cfg.path]) == 0
    out = capsys.readouterr().out
    assert "from the piton" in out and "1 unread letter" in out


def test_a_box_with_no_margin_still_gets_a_hook(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv(P.ENV, raising=False)
    (tmp_path / "claude.yaml").write_text(f"carabiner: claude\npiton: {json.dumps(str(tmp_path / 'pt'))}\n",
                                          encoding="utf-8")
    assert cli.main(["claude", "bookmark", "install", "--config", str(tmp_path / "claude.yaml")]) == 0
    hooks = json.load(open(os.environ["SEREN_CLAUDE_SETTINGS"]))["hooks"]["SessionStart"]
    cmd = hooks[0]["hooks"][0]["command"]
    assert "bookmark" in cmd and "print" in cmd and "--config" in cmd and "claude.yaml" in cmd


def test_a_codex_wake_carries_the_dedication_without_a_margin(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv(P.ENV, raising=False)
    (tmp_path / "codex.yaml").write_text(
        f"carabiner: codex\nproject: {json.dumps(str(tmp_path))}\npiton: {json.dumps(str(tmp_path / 'pt'))}\n",
        encoding="utf-8")
    P.Piton(str(tmp_path / "pt")).set("dedication", "a codex wake reads this")
    home = os.environ["CODEX_HOME"]
    os.makedirs(home, exist_ok=True)
    with open(os.path.join(home, "config.toml"), "w", encoding="utf-8") as f:
        f.write('[mcp_servers.ada-workbench]\nurl = "http://node-a:7255/mcp"\n')
    cli.main(["codex", "wake", "--config", str(tmp_path / "codex.yaml"), "--run", "do the review", "--dry"])
    out = capsys.readouterr().out
    stdin = json.loads(out)["stdin"]
    assert "a codex wake reads this" in stdin and "do the review" in stdin
