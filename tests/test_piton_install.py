"""install and init make the piton: one per box, shared, filled in file by
file, never touched where it is there, and the yaml told where it is."""
from __future__ import annotations

import os

from kbh import cli, config
from kbh import piton as P


def _install(into, *extra):
    return cli.main(["claude", "install", "--into", str(into), "--project", str(into), "--python", "/v/py", *extra])


def _default():
    return os.path.abspath(os.path.join(os.path.expanduser("~"), ".seren", "piton"))


def test_install_makes_the_piton_and_the_yaml_says_where(tmp_path, capsys, monkeypatch):
    monkeypatch.delenv(P.ENV, raising=False)
    into = tmp_path / "clip"
    assert _install(into) == 0
    out = capsys.readouterr().out
    where = _default()
    assert f"piton: {where} made" in out
    p = P.Piton(where)
    assert os.path.isfile(p.yaml_path) and os.path.isfile(p.page_path("dedication"))
    text = (into / "claude.yaml").read_text(encoding="utf-8")
    assert "# The pages at the door" in text and text.count("\npiton: ") == 1
    assert config.load(str(into / "claude.yaml")).piton_dir() == where


def test_a_reinstall_keeps_everything(tmp_path, capsys, monkeypatch):
    monkeypatch.delenv(P.ENV, raising=False)
    into = tmp_path / "clip"
    _install(into)
    p = P.Piton(_default())
    p.set("dedication", "mine, not install's")
    yaml_before = (into / "claude.yaml").read_text(encoding="utf-8")
    capsys.readouterr()
    assert _install(into) == 0
    assert "kept as it was" in capsys.readouterr().out.split("piton:")[1]
    assert (into / "claude.yaml").read_text(encoding="utf-8") == yaml_before
    assert p.read("dedication")["text"] == "mine, not install's"


def test_a_half_made_piton_is_filled_in(tmp_path, capsys, monkeypatch):
    monkeypatch.delenv(P.ENV, raising=False)
    into = tmp_path / "clip"
    _install(into)
    p = P.Piton(_default())
    p.set("dedication", "keep me")
    os.remove(p.page_path("preface"))
    capsys.readouterr()
    assert _install(into) == 0
    assert "filled in: preface.md" in capsys.readouterr().out
    assert p.read("dedication")["text"] == "keep me"


def test_two_carabiners_on_one_box_share_one_piton(tmp_path, capsys, monkeypatch):
    monkeypatch.delenv(P.ENV, raising=False)
    assert _install(tmp_path / "claude-clip") == 0
    assert cli.main(["codex", "install", "--into", str(tmp_path / "codex-clip"), "--project", str(tmp_path),
                     "--python", "/v/py"]) == 0
    a = config.load(str(tmp_path / "claude-clip" / "claude.yaml")).piton_dir()
    b = config.load(str(tmp_path / "codex-clip" / "codex.yaml")).piton_dir()
    assert a == b == _default()


def test_piton_flag_picks_the_folder_and_moves_the_yaml(tmp_path, capsys, monkeypatch):
    monkeypatch.delenv(P.ENV, raising=False)
    into = tmp_path / "clip"
    _install(into)
    elsewhere = tmp_path / "pages"
    assert _install(into, "--piton", str(elsewhere)) == 0
    assert os.path.isfile(elsewhere / "piton.yaml")
    text = (into / "claude.yaml").read_text(encoding="utf-8")
    assert text.count("\npiton: ") == 1
    assert config.load(str(into / "claude.yaml")).piton_dir() == str(elsewhere)


def test_the_env_override_is_not_written_into_a_yaml_that_names_one(tmp_path, capsys, monkeypatch):
    monkeypatch.delenv(P.ENV, raising=False)
    into = tmp_path / "clip"
    _install(into)
    before = (into / "claude.yaml").read_text(encoding="utf-8")
    monkeypatch.setenv(P.ENV, str(tmp_path / "env-pages"))
    assert _install(into) == 0
    assert os.path.isfile(tmp_path / "env-pages" / "piton.yaml")
    assert (into / "claude.yaml").read_text(encoding="utf-8") == before


def test_init_makes_it_too(tmp_path, capsys, monkeypatch):
    monkeypatch.delenv(P.ENV, raising=False)
    assert cli.main(["claude", "init", "--into", str(tmp_path / "quiet"), "--project", str(tmp_path)]) == 0
    assert f"piton: {_default()} made" in capsys.readouterr().out
    assert config.load(str(tmp_path / "quiet" / "claude.yaml")).piton == _default()


def test_a_piton_that_cannot_be_made_stops_the_install(tmp_path, capsys, monkeypatch):
    monkeypatch.delenv(P.ENV, raising=False)
    blocker = tmp_path / "a-file"
    blocker.write_text("not a folder", encoding="utf-8")
    assert _install(tmp_path / "clip", "--piton", str(blocker)) == 1
    assert "piton: could not make" in capsys.readouterr().err
