"""The .kbh as it ships: built by build.py, run from an empty folder with
nothing but python. Everything here reads through a zip, which no other test
does - `kbh new` once crashed only in a built .kbh (22 Oct 2026)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import zipfile

import build
import kbh


def _kbh(path, *args, cwd):
    # -I: no checkout on sys.path, no user site; only what is in the zip
    env = dict(os.environ, KBH_NO_DISCOVER="1")           # the model list from the shipped list, not Anthropic
    return subprocess.run([sys.executable, "-I", str(path), *args], cwd=str(cwd), env=env, capture_output=True,
                          text=True, encoding="utf-8", timeout=60)


def test_every_shipped_carabiner_builds_and_runs_from_an_empty_folder(tmp_path, monkeypatch):
    monkeypatch.setattr(build, "DIST", str(tmp_path / "dist"))
    run = tmp_path / "run"; run.mkdir()
    for name in build.shipped():
        out = build.build(name, [name], {})
        assert os.path.basename(out) == f"{name}.kbh", "the asset name is a contract with Starwright"
        names = zipfile.ZipFile(out).namelist()
        assert not any("__pycache__" in n or n.endswith(".pyc") for n in names)
        assert f"kbh/carabiners/{name}/framing.md" in names and f"kbh/carabiners/{name}/config.yaml" in names
        r = _kbh(out, "--version", cwd=run)
        assert r.returncode == 0 and kbh.__version__ in r.stdout, r.stderr
        r = _kbh(out, name, "manifest", cwd=run)
        assert r.returncode == 0 and name in r.stdout, r.stderr


def test_a_built_claude_kbh_inits_shows_its_settings_and_scaffolds(tmp_path, monkeypatch):
    monkeypatch.setattr(build, "DIST", str(tmp_path / "dist"))
    out = build.build("claude", ["claude"], {})
    run = tmp_path / "run"; (run / "proj").mkdir(parents=True)
    r = _kbh(out, "claude", "init", "--into", "k", "--project", "proj", cwd=run)
    assert r.returncode == 0, r.stderr
    assert "{message}" in (run / "k" / "framing.md").read_text(encoding="utf-8"), "the framing, read out of the zip"
    r = _kbh(out, "claude", "config", "show", "--json", "--config", str(run / "k" / "claude.yaml"), cwd=run)
    assert r.returncode == 0 and '"session.model"' in r.stdout, r.stderr
    r = _kbh(out, "new", "hermes", "--into", "mine", cwd=run)
    assert r.returncode == 0, r.stderr
    assert sorted(os.listdir(run / "mine" / "hermes")) == ["__init__.py", "config.yaml", "framing.md"]
    assert "class HermesCarabiner" in (run / "mine" / "hermes" / "__init__.py").read_text(encoding="utf-8")


def _sha(path):
    import hashlib
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def test_the_same_source_builds_the_same_file_and_says_which_build_it_is(tmp_path, monkeypatch):
    import re
    import time as _t
    monkeypatch.setattr(build, "DIST", str(tmp_path / "one"))
    first = build.build("claude", ["claude"], {})
    _t.sleep(1.1)                                       # a second later: a timestamp in the zip would show
    monkeypatch.setattr(build, "DIST", str(tmp_path / "two"))
    second = build.build("claude", ["claude"], {})
    assert _sha(first) == _sha(second), "one source, one sha256"
    r = _kbh(first, "--version", cwd=tmp_path)
    assert re.fullmatch(rf"kbh {re.escape(kbh.__version__)}\+[0-9a-z]+(\.dirty\.[0-9a-f]{{8}})?", r.stdout.strip()), r.stdout
    custom = tmp_path / "custom"; custom.mkdir(); (custom / "note.txt").write_text("mine")
    flavoured = build.build("flavour", ["claude"], {}, str(custom))
    assert ".dirty." in _kbh(flavoured, "--version", cwd=tmp_path).stdout, "a custom layer is not just the commit"


def test_build_refuses_what_it_does_not_understand(capsys):
    for argv in (["--all-in-on"], ["claude", "codex", "--as", "x"], ["--tricks"], ["claude", "--with-custom"],
                 ["--from", "./mine"], ["claude", "--all-in-one"]):
        assert build.main(argv) == 64, argv
    assert "no such flag: --all-in-on" in capsys.readouterr().err


def _box(tmp_path, monkeypatch):
    """dist/old.kbh installed as box/claude.kbh with a claude.yaml beside it,
    and a different build of the same version in new/."""
    monkeypatch.setattr(build, "DIST", str(tmp_path / "old"))
    old = build.build("claude", ["claude"], {})
    box = tmp_path / "box"; (box / "proj").mkdir(parents=True)
    installed = box / "claude.kbh"
    installed.write_bytes(open(old, "rb").read())
    assert _kbh(installed, "claude", "init", "--into", str(box), "--project", str(box / "proj"), cwd=box).returncode == 0
    return old, installed


def test_upgrade_swaps_in_a_checked_build_and_keeps_the_old_one(tmp_path, monkeypatch):
    old, installed = _box(tmp_path, monkeypatch)
    custom = tmp_path / "custom"; custom.mkdir(); (custom / "note.txt").write_text("v2")
    monkeypatch.setattr(build, "DIST", str(tmp_path / "new"))
    new = build.build("claude", ["claude"], {}, str(custom))
    r = _kbh(installed, "upgrade", "--from", new, "--sha256", _sha(new), "--json", cwd=tmp_path)
    res = json.loads(r.stdout)
    assert r.returncode == 0 and res["ok"] and res["changed"] and res["sha256_checked"], r.stdout + r.stderr
    assert _sha(installed) == _sha(new) and _sha(res["backup"]) == _sha(old)
    assert ".dirty." in res["now"] and res["belay"]["claude"]["lost"] == []
    r = _kbh(installed, "upgrade", "--from", new, "--json", cwd=tmp_path)
    assert r.returncode == 0 and json.loads(r.stdout)["changed"] is False, "the same build again: nothing to do"


def test_upgrade_refuses_a_bad_hash_or_the_wrong_carabiner_and_touches_nothing(tmp_path, monkeypatch):
    old, installed = _box(tmp_path, monkeypatch)
    monkeypatch.setattr(build, "DIST", str(tmp_path / "other"))
    codex = build.build("codex", ["codex"], {})
    r = _kbh(installed, "upgrade", "--from", codex, "--sha256", "0" * 64, cwd=tmp_path)
    assert r.returncode == 2 and "nothing of it was run" in r.stderr
    r = _kbh(installed, "upgrade", "--from", codex, cwd=tmp_path)
    assert r.returncode == 2 and "does not carry claude" in r.stderr
    assert _sha(installed) == _sha(old) and not [p for p in os.listdir(installed.parent) if ".bak-" in p]


def test_upgrade_puts_the_old_one_back_when_the_new_one_lets_go_of_what_held(tmp_path, monkeypatch):
    import shutil
    old, installed = _box(tmp_path, monkeypatch)
    mine = tmp_path / "mine" / "claude"
    shutil.copytree(os.path.join(build.PKG, "carabiners", "claude"), str(mine),
                    ignore=shutil.ignore_patterns("__pycache__"))
    with open(mine / "__init__.py", "a", encoding="utf-8") as f:
        f.write("\n\nfrom ...belay import let_go as _let_go\n_checks = CARABINER.belay_checks\n"
                "CARABINER.belay_checks = lambda self, argv: list(_checks(self, argv)) + "
                "[lambda: _let_go('config', 'on belay?', 'claude.yaml', 'broken on purpose')]\n")
    monkeypatch.setattr(build, "DIST", str(tmp_path / "broken"))
    broken = build.build("claude", [], {"claude": str(mine)})
    r = _kbh(installed, "upgrade", "--from", broken, "--json", cwd=tmp_path)
    res = json.loads(r.stdout)
    assert r.returncode == 1 and res["rolled_back"] and res["belay"]["claude"]["lost"] == ["config / claude.yaml"]
    assert _sha(installed) == _sha(old), "the old one is back"
