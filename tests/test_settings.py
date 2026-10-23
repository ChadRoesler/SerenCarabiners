"""`kbh <carabiner> config`: the settings a carabiner says it has, read and
changed in its yaml without losing a word of the comments around them - what
Lodestar's Rack asks a box's Observatory to run (22 Oct 2026)."""
from __future__ import annotations

import json
import os
import shutil

import pytest

from kbh import cli, config, yamledit
from kbh.carabiners.claude import wake


@pytest.fixture(autouse=True)
def no_discovery(monkeypatch):
    """No test asks Anthropic for its model list."""
    monkeypatch.setenv("KBH_NO_DISCOVER", "1")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)


@pytest.fixture
def clipped(tmp_path, capsys):
    """claude.yaml and framing.md from the shipped template, the way install
    leaves them, with an inline token in the bookmark route."""
    into = tmp_path / "kbh"
    proj = tmp_path / "proj"; proj.mkdir()
    assert cli.main(["claude", "init", "--into", str(into), "--project", str(proj), "--python", "/v/py",
                     "--server", "wren-workbench=workbench.yaml"]) == 0
    y = into / "claude.yaml"
    y.write_text(y.read_text(encoding="utf-8").replace(
        'bookmark: ""', 'bookmark:\n  url: http://nuc:7251\n  bearer_token: SECRET-margin-token'), encoding="utf-8")
    capsys.readouterr()
    return y


def _run(capsys, *argv, env=None):
    rc = cli.main(list(argv))
    out = capsys.readouterr()
    return rc, out.out, out.err


# ── the line editor ──────────────────────────────────────────────────────
def test_a_set_rewrites_only_its_line_and_keeps_that_lines_comment():
    text = "# top\nproject: /a   # the folder\nwake:\n  # how long\n  timeout_seconds: 900\nframing: framing.md\n"
    out = yamledit.set(text, "project", "/b")
    assert out == text.replace("/a   # the folder", "/b  # the folder")
    out = yamledit.set(text, "wake.timeout_seconds", 600)
    assert "  timeout_seconds: 600\n" in out and "  # how long\n" in out and out.startswith("# top\n")


def test_a_set_adds_a_key_to_its_block_or_a_new_block_at_the_end():
    text = "carabiner: claude\nwake:\n  timeout_seconds: 900\n# a comment after the block\nframing: f.md\n"
    out = yamledit.set(text, "wake.dry", True)
    assert "  timeout_seconds: 900\n  dry: true\n# a comment after the block\n" in out
    out = yamledit.set(text, "session.model", "claude-haiku-5-5")
    assert out.endswith("framing: f.md\nsession:\n  model: claude-haiku-5-5\n")
    assert config._two_levels_by_hand(out)["session"] == {"model": "claude-haiku-5-5"}


def test_a_block_list_is_replaced_by_one_comma_line_both_readers_read():
    text = "session:\n  allowed_tools:\n    - Read\n    - Bash(git:*)\n  permission_mode: plan\n"
    out = yamledit.set(text, "session.allowed_tools", ["mcp__wren-workbench__*", "Bash(git status:*)"])
    assert "    - Read" not in out and "  permission_mode: plan" in out
    by_hand = config.HarnessConfig(session=config._two_levels_by_hand(out)["session"])
    assert by_hand.session_allowed_tools() == ["mcp__wren-workbench__*", "Bash(git status:*)"]


def test_unset_takes_the_key_and_an_emptied_block_with_it():
    text = "a: 1\nsession:\n  model: x\nb: 2\n"
    assert yamledit.unset(text, "session.model") == "a: 1\nb: 2\n"
    assert yamledit.unset(text, "session.nothing") == text


def test_values_that_would_change_type_are_quoted():
    for v in ("true", "no", "900", "1.5", "", "has space", "-dash"):
        assert yamledit.scalar(v).startswith('"'), v
    assert yamledit.scalar("claude-opus-5-5") == "claude-opus-5-5" and yamledit.scalar(900) == "900"
    with pytest.raises(ValueError):
        yamledit.set("servers:\n  wb: wb.yaml\n", "servers", "x")


# ── the verb ─────────────────────────────────────────────────────────────
def test_set_writes_the_yaml_keeps_its_comments_and_belays(clipped, capsys):
    before = clipped.read_text(encoding="utf-8")
    rc, out, err = _run(capsys, "claude", "config", "set", "session.permission_mode=plan",
                        "session.allowed_tools=Read, Edit", "--config", str(clipped), "--json")
    res = json.loads(out)
    assert rc == 0 and res["ok"], err
    assert res["applied"] == ["session.permission_mode", "session.allowed_tools"]
    assert res["applies"] == {"session.permission_mode": "next_session", "session.allowed_tools": "next_session"}
    assert res["belay"] and all({"check", "ok", "said"} <= set(line) for line in res["belay"])
    after = clipped.read_text(encoding="utf-8")
    kept = [line for line in before.splitlines() if line.startswith("#")]
    assert all(line in after for line in kept), "every comment the file had is still there"
    cfg = config.load(str(clipped))
    assert cfg.session_mode() == "plan" and cfg.session_allowed_tools() == ["Read", "Edit"]
    assert (clipped.parent / "claude.yaml.seren-bak").read_text(encoding="utf-8") == before


def test_one_bad_value_and_nothing_is_written(clipped, capsys):
    before = clipped.read_text(encoding="utf-8")
    rc, out, _ = _run(capsys, "claude", "config", "set", "session.permission_mode=plan", "wake.timeout_seconds=5",
                      "project=" + str(clipped.parent / "not-there"), "nonsense=1", "--config", str(clipped), "--json")
    res = json.loads(out)
    assert rc == 1 and not res["ok"] and res["applied"] == []
    assert set(res["refused"]) == {"wake.timeout_seconds", "project", "nonsense"}
    assert "no such folder" in res["refused"]["project"] and "between 60" in res["refused"]["wake.timeout_seconds"]
    assert clipped.read_text(encoding="utf-8") == before


def test_never_ask_is_taken_only_when_the_change_says_expert(clipped, capsys):
    rc, out, _ = _run(capsys, "claude", "config", "set", "session.permission_mode=bypassPermissions",
                      "--config", str(clipped), "--json")
    assert rc == 1 and "expert" in json.loads(out)["refused"]["session.permission_mode"]
    rc, out, _ = _run(capsys, "claude", "config", "set", "session.permission_mode=bypassPermissions",
                      "--expert", "--config", str(clipped), "--json")
    assert rc == 0 and config.load(str(clipped)).session_mode() == "bypassPermissions"


def test_apply_takes_the_request_from_the_environment_and_answers_json(clipped, capsys, monkeypatch):
    """How the Observatory runs it: no stdin in another person's Windows session."""
    monkeypatch.setenv("KBH_SETTINGS_REQUEST", json.dumps({
        "values": {"session.model": "claude-haiku-5-5", "framing": "Just this:\n{message}\n"},
        "unset": ["wake.timeout_seconds"]}))
    rc, out, _ = _run(capsys, "claude", "config", "apply", "--config", str(clipped))
    res = json.loads(out)
    assert rc == 0 and res["ok"] and set(res["applied"]) == {"session.model", "framing", "wake.timeout_seconds"}
    assert res["applies"]["framing"] == "next_wake"
    cfg = config.load(str(clipped))
    assert cfg.session.get("model") == "claude-haiku-5-5" and "timeout_seconds" not in cfg.wake
    assert open(cfg.framing_path(), encoding="utf-8").read() == "Just this:\n{message}\n"


def test_a_wake_note_that_loses_the_message_is_refused(clipped, capsys, monkeypatch):
    monkeypatch.setenv("KBH_SETTINGS_REQUEST", json.dumps({"values": {"framing": "no placeholder at all"}}))
    rc, out, _ = _run(capsys, "claude", "config", "apply", "--config", str(clipped))
    assert rc == 1 and "{message}" in json.loads(out)["refused"]["framing"]


def test_show_says_how_a_token_is_kept_and_never_the_token(clipped, capsys):
    rc, out, _ = _run(capsys, "claude", "config", "show", "--json", "--config", str(clipped))
    m = json.loads(out)
    assert rc == 0 and "SECRET" not in out
    assert {"name": "bookmark", "where": "http://nuc:7251", "token": "inline"} in m["connections"]
    by_key = {f["key"]: f for f in m["fields"]}
    assert {"project", "wake.timeout_seconds", "framing", "session.permission_mode",
            "session.allowed_tools", "session.model"} <= set(by_key)
    assert "python" not in by_key and "servers" not in by_key, "how it was clipped on is not a form's business"
    assert by_key["wake.timeout_seconds"]["value"] == 900 and "Nobody is in the room" in by_key["framing"]["value"]
    assert "bypassPermissions" not in [c["value"] for c in by_key["session.permission_mode"]["choices"]]
    assert {"value": "mcp__wren-workbench__*", "label": "Seren's tools (wren-workbench)"} in by_key["session.allowed_tools"]["suggestions"]
    assert by_key["session.model"]["free_text"] and any(c["value"] == "claude-haiku-5-5" for c in by_key["session.model"]["choices"])


def test_no_yaml_on_this_box_is_a_json_answer_not_a_traceback(tmp_path, capsys):
    rc, out, _ = _run(capsys, "claude", "config", "apply", "--config", str(tmp_path / "nope.yaml"))
    assert rc == 1 and "install the carabiner first" in json.loads(out)["error"]


def test_a_wake_runs_on_the_boxes_model(clipped, own_settings, fake_claude, tmp_path, capsys):
    """The case it was built for: Haiku with a bare note for one box's hippocampus."""
    json.dump({"mcpServers": {"wren-workbench": {"type": "http", "url": "http://nuc:7255/mcp"}}, "projects": {}},
              open(own_settings, "w"))
    home_bin = tmp_path / "home" / ".local" / "bin"; home_bin.mkdir(parents=True)
    shutil.copy(fake_claude.path, home_bin / os.path.basename(fake_claude.path))
    yaml = str(clipped)
    assert cli.main(["claude", "config", "set", "session.model=claude-haiku-5-5", "--config", yaml]) == 0
    assert cli.main(["claude", "wake", "--config", yaml, "--run", "brief please"]) == 0
    call = fake_claude.calls()[-1]
    assert call["argv"][3:5] == ["--model", "claude-haiku-5-5"]
    assert cli.main(["claude", "config", "unset", "session.model", "--config", yaml]) == 0
    assert cli.main(["claude", "wake", "--config", yaml, "--run", "again"]) == 0
    assert "--model" not in fake_claude.calls()[-1]["argv"]


# ── what the review of 22 Oct 2026 found ─────────────────────────────────
def test_a_typed_model_id_cannot_carry_a_command(clipped, capsys):
    """On Windows `claude` is claude.cmd, and cmd.exe would run `&calc.exe`."""
    for bad in ("x&calc.exe", "x|y", "a b", "x;rm", '"q"', "%PATH%"):
        rc, out, _ = _run(capsys, "claude", "config", "set", f"session.model={bad}", "--config", str(clipped), "--json")
        assert rc == 1 and "command line" in json.loads(out)["refused"]["session.model"], bad
    for ok in ("claude-opus-5-5", "claude-opus-4-6[1m]", "us.anthropic.claude-x-v1:0", "opus"):
        rc, out, _ = _run(capsys, "claude", "config", "set", f"session.model={ok}", "--config", str(clipped), "--json")
        assert rc == 0, (ok, out)


def test_what_the_writer_quotes_the_by_hand_reader_reads_back_unchanged():
    values = (r"C:\Users\José x\proj", 'Bash(grep "a":*)', "it's", "1:30", "0x10", "C:", ".5", "1e3", r"C:\work\proj")
    texts = {v: yamledit.set("carabiner: claude\n", "project", v) for v in values}
    for v, text in texts.items():
        assert config._two_levels_by_hand(text)["project"] == v, (v, text)
    assert yamledit.scalar(r"C:\work\proj") == r"C:\work\proj", "a Windows path stays as people write it"
    yaml = pytest.importorskip("yaml")
    for v, text in texts.items():
        assert yaml.safe_load(text)["project"] == v, (v, text)


def test_a_list_at_the_keys_own_indent_goes_with_the_key():
    text = "session:\n  allowed_tools:\n  - Read\n  - Bash\n  permission_mode: plan\n"
    out = yamledit.set(text, "session.allowed_tools", ["Edit"])
    assert out == 'session:\n  allowed_tools: "Edit"\n  permission_mode: plan\n'
    assert yamledit.unset(text, "session.allowed_tools") == "session:\n  permission_mode: plan\n"


def test_nan_is_not_a_number_of_seconds(clipped, capsys):
    rc, out, _ = _run(capsys, "claude", "config", "set", "wake.timeout_seconds=nan", "--config", str(clipped), "--json")
    assert rc == 1 and json.loads(out)["refused"]["wake.timeout_seconds"] == "not a number"


def test_flags_may_come_before_the_subcommand(clipped, capsys, monkeypatch):
    monkeypatch.setenv("KBH_SETTINGS_REQUEST", json.dumps({"values": {"session.permission_mode": "plan"}}))
    rc, out, _ = _run(capsys, "claude", "config", "--config", str(clipped), "apply")
    assert rc == 0 and json.loads(out)["applied"] == ["session.permission_mode"]
    rc, out, err = _run(capsys, "claude", "config", "--config", str(clipped), "frobnicate")
    assert rc == 1 and "usage" in err


def test_the_folder_a_wake_needs_cannot_be_unset(clipped, capsys):
    rc, out, _ = _run(capsys, "claude", "config", "unset", "project", "--config", str(clipped), "--json")
    assert rc == 1 and "no default" in json.loads(out)["refused"]["project"]
    assert config.load(str(clipped)).project


def test_the_model_counts_from_the_next_wake(clipped, capsys):
    rc, out, _ = _run(capsys, "claude", "config", "set", "session.model=claude-haiku-5-5", "--config", str(clipped), "--json")
    assert json.loads(out)["applies"] == {"session.model": "next_wake"}


def test_a_wake_note_that_cannot_be_written_leaves_the_yaml_alone(clipped, capsys, monkeypatch):
    (clipped.parent / "framing.md").unlink()
    (clipped.parent / "framing.md").mkdir()                    # a folder where the note goes: no file can be written
    before = clipped.read_text(encoding="utf-8")
    monkeypatch.setenv("KBH_SETTINGS_REQUEST", json.dumps({"values": {"session.model": "claude-haiku-5-5",
                                                                     "framing": "{message}\n"}}))
    rc, out, _ = _run(capsys, "claude", "config", "apply", "--config", str(clipped))
    res = json.loads(out)
    assert rc == 1 and res["error"].startswith("nothing was written")
    assert clipped.read_text(encoding="utf-8") == before


def test_a_wake_gives_up_after_the_boxes_timeout(clipped, own_settings, fake_claude, tmp_path, capsys, monkeypatch):
    import subprocess
    json.dump({"mcpServers": {"wren-workbench": {"type": "http", "url": "http://nuc:7255/mcp"}}, "projects": {}},
              open(own_settings, "w"))
    home_bin = tmp_path / "home" / ".local" / "bin"; home_bin.mkdir(parents=True)
    shutil.copy(fake_claude.path, home_bin / os.path.basename(fake_claude.path))
    assert cli.main(["claude", "config", "set", "wake.timeout_seconds=120", "--config", str(clipped)]) == 0
    seen = {}

    def stuck(*a, **kw):
        seen.update(kw)
        raise subprocess.TimeoutExpired(a[0], kw["timeout"])
    monkeypatch.setattr(wake.subprocess, "run", stuck)
    capsys.readouterr()
    assert cli.main(["claude", "wake", "--config", str(clipped), "--run", "hello"]) == 1
    assert seen["timeout"] == 120 and "ran past 120s" in capsys.readouterr().err


def test_checking_a_change_never_asks_anthropic(clipped, capsys, monkeypatch):
    from kbh.carabiners.claude import fields
    monkeypatch.delenv("KBH_NO_DISCOVER", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    calls = []
    monkeypatch.setattr(fields, "discover_models", lambda timeout=3.0: calls.append(1) or None)
    assert cli.main(["claude", "config", "set", "session.permission_mode=plan", "--config", str(clipped)]) == 0
    assert calls == [], "set/unset/apply check against the schema, not Anthropic's list"
    assert cli.main(["claude", "config", "show", "--json", "--config", str(clipped)]) == 0
    assert calls == [1], "drawing the form is when the list is looked up"
