"""kbh.piton: the pages at the door. Each test is one promise PITON.md makes."""
from __future__ import annotations

import os

import pytest

from kbh import piton as P


def _unlocked(path, mode="w"):
    """What a person does on purpose: take the read-only mark off, then write."""
    P._set_locked(path, False)
    return open(path, mode, **({} if "b" in mode else {"encoding": "utf-8"}))


def _hand(pt, page, mode="w"):
    return _unlocked(pt.page_path(page), mode)


@pytest.fixture
def pt(tmp_path):
    p = P.Piton(str(tmp_path / "piton"))
    p.make()
    return p


# ── where it is ──

def test_locate_order(tmp_path, monkeypatch):
    monkeypatch.delenv(P.ENV, raising=False)
    home = os.path.expanduser("~")
    assert P.locate() == os.path.abspath(os.path.join(home, ".seren", "piton"))
    assert P.locate(configured="pages", base=str(tmp_path)) == str(tmp_path / "pages")
    monkeypatch.setenv(P.ENV, str(tmp_path / "env"))
    assert P.locate(configured="pages", base=str(tmp_path)) == str(tmp_path / "env")
    assert P.locate(explicit=str(tmp_path / "flag")) == str(tmp_path / "flag")


# ── making it: fill in what is missing, never touch what is there ──

def test_make_creates_everything_once(tmp_path):
    p = P.Piton(str(tmp_path / "piton"))
    created = p.make()
    assert p.yaml_path in created and p.page_path("dedication") in created and p.page_path("preface") in created
    assert os.path.isdir(p.history_dir("dedication")) and os.path.isdir(p.history_dir("preface"))
    assert p.make() == []


def test_make_repairs_a_half_made_folder_and_keeps_the_rest(pt):
    _hand(pt, "dedication").write("mine\n")
    open(pt.yaml_path, "w", encoding="utf-8").write("schema: 1\ndedication: operator\n")
    os.remove(pt.page_path("preface"))
    assert pt.make() == [pt.page_path("preface")]
    assert open(pt.page_path("dedication"), encoding="utf-8").read() == "mine\n"
    assert "dedication: operator" in open(pt.yaml_path, encoding="utf-8").read()


# ── the options ──

def test_defaults_when_the_yaml_says_nothing(pt):
    open(pt.yaml_path, "w", encoding="utf-8").write("schema: 1\n")
    opts, problems = pt.options()
    assert (opts["dedication"], opts["preface"]) == ("self", "operator")
    assert opts["caps"] == {"dedication": 2000, "preface": 8000}
    assert problems == []
    assert open(pt.yaml_path, encoding="utf-8").read() == "schema: 1\n"     # never written back


@pytest.mark.parametrize("by_hand", [False, True])
def test_a_bare_off_means_off(pt, monkeypatch, by_hand):
    """YAML 1.1 reads `off` as False; with PyYAML or kbh's own reader (a
    harness box with no PyYAML), the word a person types still works."""
    if by_hand:
        from kbh import config
        monkeypatch.setattr(P, "read_yaml",
                            lambda path: config._two_levels_by_hand(open(path, encoding="utf-8").read()))
    open(pt.yaml_path, "w", encoding="utf-8").write("schema: 1\ndedication: off\ncaps:\n  preface: 100\n")
    opts, problems = pt.options()
    assert opts["dedication"] == "off" and opts["caps"]["preface"] == 100 and problems == []


def test_the_template_reads_the_same_by_hand(pt):
    from kbh import config
    assert config._two_levels_by_hand(open(pt.yaml_path, encoding="utf-8").read()) == {
        "schema": 1, "dedication": "self", "preface": "operator",
        "caps": {"dedication": 2000, "preface": 8000}}


def test_unknown_keys_ignored_and_bad_values_say_so(pt):
    open(pt.yaml_path, "w", encoding="utf-8").write(
        "schema: 2\nfrom_the_future: yes\ndedication: banana\ncaps:\n  preface: lots\n")
    opts, problems = pt.options()
    assert opts["dedication"] == "self" and opts["caps"]["preface"] == 8000
    assert len(problems) == 2 and "banana" in problems[0]


# ── writing ──

def test_set_writes_history_then_the_page(pt):
    entry, changed = pt.set("dedication", "To whoever I am next time.", why="first page")
    assert changed and entry["version"] == 1
    assert open(pt.page_path("dedication"), encoding="utf-8").read() == "To whoever I am next time.\n"
    h = pt.history("dedication")
    assert h[0]["text"] == "To whoever I am next time." and h[0]["why"] == "first page" and h[0]["by"] == "self"


def test_same_text_is_not_a_new_version(pt):
    pt.set("dedication", "one")
    _, changed = pt.set("dedication", "one\r\n")
    assert not changed and len(pt.history("dedication")) == 1


def test_every_version_is_kept(pt):
    for i in range(1, 4):
        pt.set("dedication", f"version {i}", why=f"why {i}")
    assert [v["version"] for v in pt.history("dedication")] == [3, 2, 1]
    assert pt.read("dedication")["text"] == "version 3"


def test_cap_and_empty_are_refused(pt):
    with pytest.raises(P.PitonError, match="capped at 2000"):
        pt.set("dedication", "x" * 2001)
    with pytest.raises(P.PitonError, match="must not be empty"):
        pt.set("dedication", "   ")


def test_who_writes(pt):
    with pytest.raises(P.PitonError, match="written by the operator"):
        pt.set("preface", "the room", by="self")
    pt.set("preface", "the room", by="operator")
    with pytest.raises(P.PitonError, match="the model's own page"):
        pt.set("dedication", "not yours", by="operator")
    open(pt.yaml_path, "w", encoding="utf-8").write("schema: 1\ndedication: off\n")
    with pytest.raises(P.PitonError, match="off on this box"):
        pt.set("dedication", "anyone", by="self")
    # A record of what happened is never refused: the one-time import, say.
    _, changed = pt.set("dedication", "from margin", by="margin")
    assert changed


def test_a_quote_and_newlines_in_why_survive(pt):
    pt.set("dedication", "page", why='the "clock"\ngot built: yes')
    assert pt.latest("dedication")["why"] == 'the "clock"\ngot built: yes'


def test_set_at_is_kept_for_an_import(pt):
    pt.set("dedication", "old page", by="margin", set_at=1790000000.0)
    assert pt.latest("dedication")["set_at"] == 1790000000.0


# ── reading ──

def test_nothing_written_is_nothing_shown(pt):
    r = pt.read("dedication")
    assert r["text"] == "" and r["version"] is None and r["problems"] == []


def test_off_shows_nothing(pt):
    pt.set("dedication", "a page")
    open(pt.yaml_path, "w", encoding="utf-8").write("schema: 1\ndedication: off\n")
    assert pt.read("dedication")["text"] == ""


def test_a_hand_edit_becomes_a_version(pt):
    pt.set("dedication", "v1")
    _hand(pt, "dedication").write("v2, typed in Notepad\r\n")
    r = pt.read("dedication")
    assert r["text"] == "v2, typed in Notepad" and r["version"] == 2 and r["by"] == "hand"
    assert pt.latest("dedication")["why"] == "edited by hand"
    assert pt.read("dedication")["version"] == 2          # recorded once, not every read


def test_a_page_written_before_there_was_history_is_kept(pt):
    _hand(pt, "preface").write("the room as it was\n")
    r = pt.read("preface")
    assert r["text"] == "the room as it was" and r["version"] == 1


def test_set_records_a_waiting_hand_edit_before_replacing_it(pt):
    pt.set("dedication", "v1")
    _hand(pt, "dedication").write("hand edit")
    pt.set("dedication", "v3")
    assert [v["text"] for v in pt.history("dedication")] == ["v3", "hand edit", "v1"]


def test_over_the_cap_falls_back_to_the_last_good_version(pt):
    pt.set("dedication", "good")
    _hand(pt, "dedication").write("x" * 2500)
    r = pt.read("dedication")
    assert r["text"] == "good" and r["version"] == 1
    assert "over its cap" in r["problems"][0]
    assert len(pt.history("dedication")) == 1               # the bad page is not recorded


def test_an_emptied_page_falls_back(pt):
    pt.set("dedication", "good")
    _hand(pt, "dedication").write("")
    r = pt.read("dedication")
    assert r["text"] == "good" and "is empty" in r["problems"][0]


def test_a_page_that_does_not_read_falls_back(pt):
    pt.set("dedication", "good")
    _hand(pt, "dedication", "wb").write(b"\xff\xfe\x00bad")
    r = pt.read("dedication")
    assert r["text"] == "good" and "does not read" in r["problems"][0]


def test_a_broken_yaml_is_defaults_and_a_line(pt):
    pt.set("dedication", "still here")
    open(pt.yaml_path, "w", encoding="utf-8").write("dedication: [unclosed\n  - : :\n")
    r = pt.read("dedication")
    assert r["text"] == "still here"
    assert r["writer"] == "self"


def test_a_broken_version_file_is_skipped(pt):
    pt.set("dedication", "v1")
    pt.set("dedication", "v2")
    _unlocked(os.path.join(pt.history_dir("dedication"), "0002.md"), "wb").write(b"\xff\xfe")
    assert pt.latest("dedication")["text"] == "v1"


def test_no_such_page(pt):
    with pytest.raises(ValueError):
        pt.read("letters")


# ── the fat-finger lock ──

def test_the_models_page_cannot_be_saved_over_by_accident(pt):
    pt.set("dedication", "mine")
    assert P.is_locked(pt.page_path("dedication"))
    with pytest.raises(PermissionError):
        open(pt.page_path("dedication"), "w", encoding="utf-8").write("oops, a fat finger")
    assert pt.read("dedication")["text"] == "mine"


def test_the_operators_page_stays_theirs_to_edit(pt):
    pt.set("preface", "the room", by="operator")
    assert not P.is_locked(pt.page_path("preface"))
    open(pt.page_path("preface"), "w", encoding="utf-8").write("the room, by hand")
    assert pt.read("preface")["text"] == "the room, by hand"


def test_history_is_always_read_only(pt):
    pt.set("preface", "v1", by="operator")
    for _, path in pt._version_files("preface"):
        assert P.is_locked(path)
        with pytest.raises(PermissionError):
            open(path, "w", encoding="utf-8").write("trash")


def test_set_writes_through_its_own_lock_again_and_again(pt):
    for i in range(3):
        pt.set("dedication", f"v{i}")
    assert pt.read("dedication")["text"] == "v2" and P.is_locked(pt.page_path("dedication"))


def test_changing_the_writer_moves_the_lock_at_the_next_read(pt):
    pt.set("dedication", "mine")
    open(pt.yaml_path, "w", encoding="utf-8").write("schema: 1\ndedication: operator\n")
    pt.read("dedication")
    assert not P.is_locked(pt.page_path("dedication"))
    open(pt.yaml_path, "w", encoding="utf-8").write("schema: 1\ndedication: self\n")
    pt.read("dedication")
    assert P.is_locked(pt.page_path("dedication"))


def test_a_deliberate_unlock_and_edit_is_recorded_and_locked_again(pt):
    pt.set("dedication", "v1")
    _hand(pt, "dedication").write("v2 on purpose")
    assert pt.read("dedication")["by"] == "hand"
    assert P.is_locked(pt.page_path("dedication"))


# ── restore ──

def test_restore_brings_an_old_version_back_as_a_new_one(pt):
    pt.set("dedication", "the good one")
    pt.set("dedication", "trashed")
    entry, changed = pt.restore("dedication", 1)
    assert changed and entry["version"] == 3 and entry["why"] == "restored version 1"
    assert pt.read("dedication")["text"] == "the good one"
    pt.restore("dedication", 2)                         # and the undo can be undone
    assert pt.read("dedication")["text"] == "trashed"


def test_restore_of_no_such_version(pt):
    pt.set("dedication", "one")
    with pytest.raises(P.PitonError, match="no version 9"):
        pt.restore("dedication", 9)


def test_restore_follows_who_writes(pt):
    pt.set("dedication", "mine")
    with pytest.raises(P.PitonError, match="the model's own page"):
        pt.restore("dedication", 1, by="operator")


# ── the verb ──

def _cli(*args):
    from kbh import cli
    return cli.main(["claude", "piton", *args])


def test_who_is_writing(monkeypatch):
    for v in P.SESSION_ENV + ("KBH_AS",):
        monkeypatch.delenv(v, raising=False)
    assert P.who_is_writing([]) == "operator"
    monkeypatch.setenv("CLAUDECODE", "1")
    assert P.who_is_writing([]) == "self"
    assert P.who_is_writing(["--as", "operator"]) == "operator"
    monkeypatch.delenv("CLAUDECODE")
    monkeypatch.setenv("KBH_AS", "self")
    assert P.who_is_writing([]) == "self"


def test_the_verb_end_to_end(pt, tmp_path, capsys, monkeypatch):
    for v in P.SESSION_ENV + ("KBH_AS",):
        monkeypatch.delenv(v, raising=False)
    page = tmp_path / "page.md"
    page.write_text("﻿To whoever I am next time.\n", encoding="utf-8")       # a BOM from Notepad is dropped
    where = ["--piton", pt.root]

    assert _cli("set", "dedication", "--file", str(page), "--why", "first", *where) == 1
    assert "the model's own page" in capsys.readouterr().err                 # you, at a terminal
    monkeypatch.setenv("CLAUDECODE", "1")
    assert _cli("set", "dedication", "--file", str(page), "--why", "first", *where) == 0
    assert "dedication: version 1" in capsys.readouterr().out
    assert pt.read("dedication")["text"] == "To whoever I am next time."

    assert _cli(*where) == 0
    out = capsys.readouterr().out
    assert "written by the model" in out and "version 1" in out and "read only" in out

    assert _cli("show", "dedication", "--history", "5", *where) == 0
    assert "--- version 1" in capsys.readouterr().out

    page.write_text("second", encoding="utf-8")
    _cli("set", "dedication", "--file", str(page), *where)
    assert _cli("restore", "dedication", "1", *where) == 0
    assert pt.read("dedication")["text"] == "To whoever I am next time."
    capsys.readouterr()

    assert _cli("show", "letters", *where) == 64
    assert _cli("set", "dedication", "--as", "root", "--file", str(page), *where) == 64


def test_the_verb_json_is_what_a_form_reads(pt, capsys):
    import json
    assert _cli("--json", "--piton", pt.root) == 0
    s = json.loads(capsys.readouterr().out)
    assert s["root"] == pt.root and s["pages"]["dedication"]["writer"] == "self"
    assert s["pages"]["preface"]["locked"] is False


# ── belay ──

def _belay(name, argv):
    from kbh import belay
    return belay.run(name, P.belay_checks(name, argv))


def test_belay_holds_on_a_good_piton(pt):
    pt.set("dedication", "mine")
    rep = _belay("claude", ["--piton", pt.root])
    assert rep.ok and all(c.held for c in rep.checks), rep.text()


def test_belay_skips_a_box_that_never_had_one(tmp_path, monkeypatch):
    monkeypatch.delenv(P.ENV, raising=False)
    rep = _belay("claude", [])
    assert rep.ok and rep.checks[0].held is None and "install makes one" in rep.checks[0].why


def test_belay_lets_go_of_a_named_piton_that_is_gone(tmp_path):
    rep = _belay("claude", ["--piton", str(tmp_path / "gone")])
    assert not rep.ok and "no piton at" in rep.checks[0].why


def test_belay_lets_go_of_a_page_over_its_cap(pt):
    pt.set("dedication", "good")
    _hand(pt, "dedication").write("x" * 2500)
    rep = _belay("claude", ["--piton", pt.root])
    assert not rep.ok and any("over its cap" in c.why for c in rep.checks)
