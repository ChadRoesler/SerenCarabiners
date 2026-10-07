"""We ship a few carabiners and the template, and the world goes wild: `kbh new`
makes one, `--path` loads it from outside the repo, build.py bundles it as
<name>.kbh, and a bad one does not take the others down."""
from __future__ import annotations

import json
import os
import subprocess
import sys

from kbh import cli

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_new_makes_a_carabiner_from_the_template_that_loads_by_path(tmp_path, capsys):
    assert cli.main(["new", "hermes", "--into", str(tmp_path / "mine"), "--display", "Hermes Agent"]) == 0
    made = tmp_path / "mine" / "hermes"
    text = (made / "__init__.py").read_text(encoding="utf-8")
    assert 'name = "hermes"' in text and 'display = "Hermes Agent"' in text and "class HermesCarabiner" in text
    assert "__NAME__" not in text and "__HARNESS__" not in text
    assert (made / "framing.md").exists()
    capsys.readouterr()

    assert cli.main(["--path", str(tmp_path / "mine"), "list"]) == 0
    out = capsys.readouterr().out
    assert "hermes     Hermes Agent: nothing yet" in out and "claude" in out, "ours and theirs, side by side"
    assert cli.main(["--path", str(tmp_path / "mine"), "hermes", "manifest"]) == 0
    m = json.loads(capsys.readouterr().out)
    assert m["name"] == "hermes" and m["verbs"] == {"register": False, "wake": False, "bookmark": False, "due": False}
    assert cli.main(["--path", str(tmp_path / "mine"), "hermes", "wake", "--project", "."]) == 3, "unsupported, honestly"
    assert cli.main(["--path", str(tmp_path / "mine"), "hermes", "belay"]) == 0, "a template belays clean (all skipped)"

    assert cli.main(["new", "hermes", "--into", str(tmp_path / "mine")]) == 1, "never overwrites"
    assert cli.main(["new", "Not Valid!", "--into", str(tmp_path / "mine")]) == 1
    assert "template" not in [l.split()[0] for l in subprocess.run([sys.executable, "-m", "kbh", "list"], cwd=ROOT,
                                                                  capture_output=True, text=True).stdout.splitlines()], \
        "the template itself is not a carabiner"


def test_a_broken_external_carabiner_does_not_hide_the_rest(tmp_path, capsys):
    bad = tmp_path / "mine" / "broken"; bad.mkdir(parents=True)
    (bad / "__init__.py").write_text("raise RuntimeError('half written')\n", encoding="utf-8")
    assert cli.main(["--path", str(tmp_path / "mine"), "list"]) == 0
    got = capsys.readouterr()
    assert "claude" in got.out and "did not load" in got.err and "half written" in got.err


def test_build_bundles_an_external_carabiner_as_its_own_kbh(tmp_path):
    assert cli.main(["new", "hermes", "--into", str(tmp_path / "mine")]) == 0
    env = dict(os.environ, KBH_DIST=str(tmp_path / "dist"))
    # build.py writes to <repo>/dist; run it in a copy-free way by pointing cwd at the repo and checking the output path
    done = subprocess.run([sys.executable, os.path.join(ROOT, "build.py"), "hermes", "--from", str(tmp_path / "mine")],
                          cwd=ROOT, capture_output=True, text=True, env=env)
    assert done.returncode == 0, done.stderr
    out = done.stdout.strip().splitlines()[-1]
    assert out.endswith("hermes.kbh") and os.path.isfile(out)
    try:
        run = subprocess.run([sys.executable, out, "list"], capture_output=True, text=True)
        assert "hermes" in run.stdout and "claude" not in run.stdout, "a hermes.kbh carries hermes and the binder, not us"
        run = subprocess.run([sys.executable, out, "hermes", "manifest"], capture_output=True, text=True)
        assert json.loads(run.stdout)["name"] == "hermes"
    finally:
        os.remove(out)
    done = subprocess.run([sys.executable, os.path.join(ROOT, "build.py"), "nope"], cwd=ROOT, capture_output=True, text=True)
    assert done.returncode == 1 and "--from DIR" in done.stderr
