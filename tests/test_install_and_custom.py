"""The final shape: one standalone .kbh per harness; `install` pushes config,
framing and a shipped custom/ out beside it and runs the hooks; custom/python
adds verbs and belay checks; a flavour can be bundled and handed over; a
tricks pack layers custom/ onto an installed carabiner."""
from __future__ import annotations

import json
import os
import subprocess
import sys

from kbh import cli

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

CUSTOM_VERB = '''
import os
def hello(carabiner, argv):
    print("hello from custom, carabiner=%s argv=%s" % (carabiner.name, argv))
    return 0
VERBS = {"hello": hello}

def BELAY_CHECKS(carabiner, argv):
    from kbh.belay import held
    return [lambda: held("custom", "on belay?", "hello", "the custom verb is loaded")]
'''


def _custom_tree(folder, hook_marker: str):
    (folder / "python").mkdir(parents=True)
    (folder / "python" / "hello.py").write_text(CUSTOM_VERB, encoding="utf-8")
    (folder / "extras").mkdir()
    (folder / "extras" / "bedtime.md").write_text("It is bedtime. {message}\n", encoding="utf-8")
    (folder / "pre_install").mkdir()
    (folder / "pre_install" / "10_mark.py").write_text(
        f"import os; open(os.path.join(os.environ['KBH_INTO'], '{hook_marker}-pre'), 'w').write(os.environ['KBH_CARABINER']); print('pre ran')\n",
        encoding="utf-8")
    (folder / "post_install").mkdir()
    (folder / "post_install" / "10_mark.py").write_text(
        f"import os; open(os.path.join(os.environ['KBH_INTO'], '{hook_marker}-post'), 'w').write(os.environ['KBH_CONFIG']); print('post ran')\n",
        encoding="utf-8")


def test_install_pushes_config_framing_and_runs_hooks_and_custom_adds_a_verb(tmp_path, capsys):
    into = tmp_path / "clip"
    into.mkdir()
    _custom_tree(into / "custom", "mark")                      # the box's own custom/, already there
    rc = cli.main(["claude", "install", "--into", str(into), "--project", str(tmp_path), "--python", "/v/py",
                   "--server", "wren-workbench=workbench.yaml", "--bookmark", "margin.yaml"])
    out = capsys.readouterr().out
    assert rc == 0, out
    assert (into / "claude.yaml").exists() and (into / "framing.md").exists()
    yaml_text = (into / "claude.yaml").read_text(encoding="utf-8")
    assert "how the Claude Code carabiner rolls on THIS box" in yaml_text, "the config.yaml template, not a Python string"
    assert "  wren-workbench: workbench.yaml" in yaml_text and "python: /v/py" in yaml_text
    assert (into / "mark-pre").read_text() == "claude" and (into / "mark-post").read_text().endswith("claude.yaml")
    assert "pre_install/10_mark.py: ok - pre ran" in out and "post_install/10_mark.py: ok - post ran" in out

    # a re-install keeps the edited yaml and framing
    (into / "framing.md").write_text("MINE {message}\n", encoding="utf-8")
    (into / "claude.yaml").write_text(yaml_text.replace("/v/py", "/other/py"), encoding="utf-8")
    assert cli.main(["claude", "install", "--into", str(into), "--project", "x"]) == 0
    assert "kept as it was" in capsys.readouterr().out
    assert "/other/py" in (into / "claude.yaml").read_text() and (into / "framing.md").read_text() == "MINE {message}\n"

    # custom/python adds a verb and a belay check, found via the config beside the .kbh
    cfg = str(into / "claude.yaml")
    assert cli.main(["claude", "hello", "--config", cfg, "one", "two"]) == 0
    said = capsys.readouterr().out
    assert "hello from custom, carabiner=claude" in said and said.rstrip().endswith("'one', 'two']"), "a custom verb gets the argv, --config and all"
    cli.main(["claude", "belay", "--config", cfg, "--json"])
    rep = json.loads(capsys.readouterr().out)
    assert any(c["verb"] == "custom" and c["name"] == "hello" and c["status"] == "held" for c in rep["checks"])
    cli.main(["claude", "manifest", "--config", cfg])
    assert json.loads(capsys.readouterr().out)["custom"]["verbs"] == ["hello"]
    assert cli.main(["claude", "nosuchverb", "--config", cfg]) == 64
    assert "custom/ adds: hello" in capsys.readouterr().err


def test_a_broken_custom_module_is_reported_not_fatal(tmp_path, capsys):
    into = tmp_path / "clip"
    (into / "custom" / "python").mkdir(parents=True)
    (into / "custom" / "python" / "bad.py").write_text("raise ValueError('half written')\n", encoding="utf-8")
    assert cli.main(["claude", "init", "--into", str(into), "--project", "x"]) == 0
    capsys.readouterr()
    cli.main(["claude", "belay", "--config", str(into / "claude.yaml"), "--json"])
    rep = json.loads(capsys.readouterr().out)
    bad = [c for c in rep["checks"] if c["verb"] == "custom"][0]
    assert bad["status"] == "LET GO" and "half written" in bad["why"]


def test_a_failing_pre_install_hook_stops_the_install(tmp_path, capsys):
    into = tmp_path / "clip"
    (into / "custom" / "pre_install").mkdir(parents=True)
    (into / "custom" / "pre_install" / "boom.py").write_text("import sys; print('no'); sys.exit(3)\n", encoding="utf-8")
    assert cli.main(["claude", "install", "--into", str(into), "--project", "x"]) == 1
    assert "boom.py failed" in capsys.readouterr().err
    assert not (into / "claude.yaml").exists(), "nothing pushed after a failed pre-install"


def _build(args, env=None):
    done = subprocess.run([sys.executable, os.path.join(ROOT, "build.py"), *args], cwd=ROOT,
                          capture_output=True, text=True, env=env)
    assert done.returncode == 0, done.stderr + done.stdout
    return done.stdout.strip().splitlines()[-1]


def test_a_flavour_is_one_file_and_install_pushes_its_custom_beside_the_zip(tmp_path):
    mine = tmp_path / "mine"
    _custom_tree(mine, "ship")
    env = dict(os.environ, KBH_DIST=str(tmp_path / "dist"))
    kbh = _build(["claude", "--with-custom", str(mine), "--as", "chads-claude"], env)
    assert kbh.endswith("chads-claude.kbh")
    clip = tmp_path / "clip"; clip.mkdir()
    # install from the zip itself, --into its own folder being the default: put the zip there first
    import shutil
    shutil.copy(kbh, clip / "chads-claude.kbh")
    done = subprocess.run([sys.executable, str(clip / "chads-claude.kbh"), "claude", "install", "--project", str(tmp_path),
                           "--python", sys.executable], capture_output=True, text=True, cwd=str(tmp_path),
                          env=dict(os.environ, SEREN_CLAUDE_JSON=str(tmp_path / "cj.json")))
    assert done.returncode == 0, done.stderr + done.stdout
    assert (clip / "custom" / "python" / "hello.py").exists() and (clip / "custom" / "extras" / "bedtime.md").exists()
    assert (clip / "claude.yaml").exists() and (clip / "ship-pre").exists() and (clip / "ship-post").exists()
    # the custom verb now works from the zip, config found beside it with no flags
    run = subprocess.run([sys.executable, str(clip / "chads-claude.kbh"), "claude", "hello"], capture_output=True, text=True,
                         cwd=str(tmp_path))
    assert "hello from custom" in run.stdout, run.stderr
    # a second install with a custom/ already there: the shipped one lands beside, nothing overwritten
    (clip / "custom" / "python" / "hello.py").write_text("VERBS = {}\n", encoding="utf-8")
    done = subprocess.run([sys.executable, str(clip / "chads-claude.kbh"), "claude", "install"], capture_output=True, text=True,
                          cwd=str(tmp_path))
    assert done.returncode == 0 and "custom.shipped" in done.stdout
    assert (clip / "custom" / "python" / "hello.py").read_text() == "VERBS = {}\n"
    assert (clip / "custom.shipped" / "python" / "hello.py").exists()


def test_a_tricks_pack_layers_custom_onto_an_installed_carabiner(tmp_path):
    tricks = tmp_path / "tricks"
    (tricks / "python").mkdir(parents=True)
    (tricks / "python" / "trick.py").write_text("VERBS = {'trick': lambda c, a: (print('tricked'), 0)[1]}\n", encoding="utf-8")
    env = dict(os.environ, KBH_DIST=str(tmp_path / "dist"))
    pack = _build(["--tricks", "wren-tricks", "--with-custom", str(tricks)], env)
    assert pack.endswith("wren-tricks.kbh")
    listed = subprocess.run([sys.executable, pack, "list"], capture_output=True, text=True)
    assert listed.stdout.strip() == "", "a tricks pack carries no carabiner"
    clip = tmp_path / "clip"; clip.mkdir()
    assert cli.main(["claude", "init", "--into", str(clip), "--project", "x"]) == 0
    done = subprocess.run([sys.executable, pack, "install", "--into", str(clip)], capture_output=True, text=True)
    assert done.returncode == 0 and (clip / "custom" / "python" / "trick.py").exists(), done.stderr
    # the installed claude (from source here) sees the trick via the config beside it
    import io, contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = cli.main(["claude", "trick", "--config", str(clip / "claude.yaml")])
    assert rc == 0 and "tricked" in buf.getvalue()
    empty = subprocess.run([sys.executable, pack, "claude", "manifest"], capture_output=True, text=True)
    assert empty.returncode == 64, "it has no claude to speak for"
