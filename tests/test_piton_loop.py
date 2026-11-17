"""The piton's settings in the Rack's form, and the Workbench loop: the model
writes through the one door, each box pulls at session start by the
Workbench's own count, and the box decides who writes what."""
from __future__ import annotations

import json
import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from kbh import cli, config, door
from kbh import piton as P
from kbh.tokens import Connection, write_connection


# ── a stand-in Workbench: GET /pages/<page>?after=N, by its own count ──

@pytest.fixture
def workbench():
    """A stand-in for the REAL door (seren_workbench routes/pages.py, 17 Nov
    2026), shaped like it, not like what we expected: set_at as an ISO string
    ("2026-11-17T21:04:09Z"), GET /pages the summary (each page's seq, or null
    when never written), GET /pages/<page>?after=N the newest past N or 204.
    The first stand-in served epoch floats and passed every test while the real
    door's answer would have been refused on every session start."""
    pages = {"dedication": [], "preface": []}
    state = {"old": False}
    hits = []

    class H(BaseHTTPRequestHandler):
        def _json(self, body):
            self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers()
            self.wfile.write(json.dumps(body).encode())

        def do_GET(self):
            hits.append(self.path)
            if self.headers.get("Authorization") != "Bearer wb-secret":
                self.send_response(401); self.end_headers(); return
            path, _, query = self.path.partition("?")
            if state["old"]:
                self.send_response(404); self.end_headers(); return
            if path == "/pages":
                return self._json({pg: ({"seq": vs[-1]["seq"], "set_at": vs[-1]["set_at"], "by": "self",
                                         "chars": len(vs[-1]["text"]), "cap": 2000} if vs else None)
                                   for pg, vs in pages.items()})
            page = path[len("/pages/"):] if path.startswith("/pages/") else ""
            if page not in pages:
                self.send_response(404); self.end_headers(); return
            after = int(dict(q.split("=", 1) for q in query.split("&") if "=" in q).get("after", 0))
            newer = [v for v in pages[page] if v["seq"] > after]
            if not newer:
                self.send_response(204); self.end_headers(); return
            self._json(newer[-1])

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    def write(page, text, set_at, why=None):
        pages[page].append({"seq": len(pages[page]) + 1, "text": text, "why": why,
                            "set_at": P._iso(set_at), "by": "self"})
    srv.write = write
    srv.state = state
    srv.hits = hits
    yield srv
    srv.shutdown()


def _box(tmp_path, name, wb, extra=""):
    """A carabiner yaml on its own box: its own piton, the Workbench as its one server."""
    conn = write_connection(str(tmp_path / name / "routes" / "workbench.yaml"),
                            Connection(host="127.0.0.1", port=wb.server_address[1], bearer_token="wb-secret"))
    (tmp_path / name).mkdir(exist_ok=True)
    y = tmp_path / name / "claude.yaml"
    y.write_text(f"carabiner: claude\nproject: {json.dumps(str(tmp_path))}\nservers:\n  wren-workbench: {json.dumps(conn)}\n"
                 f"piton: {json.dumps(str(tmp_path / name / 'piton'))}\n{extra}", encoding="utf-8")
    cfg = config.load(str(y))
    p = P.Piton(cfg.piton_dir())
    p.make()
    return cfg, p


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv(P.ENV, raising=False)
    for v in P.SESSION_ENV + ("KBH_AS",):
        monkeypatch.delenv(v, raising=False)


# ── the pull ──

def test_what_the_model_wrote_through_the_workbench_is_what_the_next_session_reads(tmp_path, workbench):
    cfg, p = _box(tmp_path, "desktop", workbench)
    workbench.write("dedication", "To whoever I am next time: the clock got built.", 1795000000.0, "the clock")
    out = door.text(cfg, "claude")
    assert "the clock got built." in out and "came from the Workbench" in out
    v = p.latest("dedication")
    assert v["by"] == "pull" and v["why"] == "the clock" and v["set_at"] == 1795000000.0
    assert json.load(open(os.path.join(p.root, door.PULLED))) == {"dedication": {"seq": 1, "version": 1}}
    workbench.hits.clear()
    again = door.text(cfg, "claude")
    assert "came from the Workbench" not in again and len(p.history("dedication")) == 1
    assert workbench.hits == ["/pages"], "nothing new is one call"


def test_two_boxes_pull_the_same_page_and_agree(tmp_path, workbench):
    a, pa = _box(tmp_path, "desktop", workbench)
    b, pb = _box(tmp_path, "nuc", workbench)
    workbench.write("dedication", "one page, two boxes", 1795000000.0)
    door.text(a, "claude")
    door.text(b, "claude")
    assert pa.read("dedication")["text"] == pb.read("dedication")["text"] == "one page, two boxes"


def test_the_newest_is_taken_when_several_were_written_between_sessions(tmp_path, workbench):
    cfg, p = _box(tmp_path, "desktop", workbench)
    for i in range(3):
        workbench.write("dedication", f"draft {i}", 1795000000.0 + i)
    door.text(cfg, "claude")
    assert p.read("dedication")["text"] == "draft 2"
    assert json.load(open(os.path.join(p.root, door.PULLED)))["dedication"]["seq"] == 3


def test_the_box_decides_who_writes(tmp_path, workbench):
    cfg, p = _box(tmp_path, "desktop", workbench)
    workbench.write("preface", "the model's idea of the room", 1795000000.0)     # preface is the operator's
    out = door.text(cfg, "claude")
    assert "was not taken" in out and "written by the operator" in out
    assert p.latest("preface") is None
    assert "was not taken" not in door.text(cfg, "claude"), "said once, not every session"


def test_a_page_changed_on_the_box_since_the_last_pull_is_kept(tmp_path, workbench):
    cfg, p = _box(tmp_path, "desktop", workbench)
    workbench.write("dedication", "first, through the Workbench", 1795000000.0)
    door.text(cfg, "claude")
    P._set_locked(p.page_path("dedication"), False)
    open(p.page_path("dedication"), "w", encoding="utf-8").write("typed on the box since")
    workbench.write("dedication", "second, through the Workbench", 1795000100.0)
    out = door.text(cfg, "claude")
    assert p.read("dedication")["text"] == "typed on the box since" and "box's is kept" in out
    workbench.write("dedication", "third, after the box's was kept", 1795000200.0)
    door.text(cfg, "claude")
    assert p.read("dedication")["text"] == "third, after the box's was kept", "the next write is taken again"


def test_no_clocks_a_workbench_far_behind_in_time_is_still_newer_by_its_count(tmp_path, workbench):
    """The NUC's clock says 1970; the count says it is new. The count wins."""
    cfg, p = _box(tmp_path, "desktop", workbench)
    p.set("dedication", "imported from Margin, stamped today")
    workbench.write("dedication", "written through the Workbench", 1000.0)
    door.text(cfg, "claude")
    assert p.read("dedication")["text"] == "written through the Workbench"


def test_an_older_workbench_is_quiet(tmp_path, workbench):
    cfg, p = _box(tmp_path, "desktop", workbench)
    workbench.state["old"] = True
    p.set("dedication", "mine")
    out = door.text(cfg, "claude")
    assert "mine" in out and "Workbench" not in out


def test_a_workbench_that_is_down_costs_a_line_not_the_dedication(tmp_path, workbench):
    cfg, p = _box(tmp_path, "desktop", workbench)
    p.set("dedication", "still here")
    workbench.shutdown()
    workbench.server_close()
    out = door.text(cfg, "claude")
    assert "still here" in out and "could not be checked" in out


def test_which_route_is_the_workbench(tmp_path, workbench):
    cfg, _ = _box(tmp_path, "one", workbench)
    assert door.workbench_connection(cfg)
    two = tmp_path / "two.yaml"
    two.write_text("carabiner: claude\nservers:\n  memory: m.yaml\n  loci: l.yaml\n", encoding="utf-8")
    assert door.workbench_connection(config.load(str(two))) == ""
    two.write_text("carabiner: claude\nworkbench: memory\nservers:\n  memory: m.yaml\n  loci: l.yaml\n", encoding="utf-8")
    assert door.workbench_connection(config.load(str(two))).endswith("m.yaml")


# ── the settings form ──

def _show(cfg, capsys):
    assert cli.main(["claude", "config", "show", "--json", "--config", cfg.path]) == 0
    return json.loads(capsys.readouterr().out)


def _apply(cfg, request, monkeypatch, capsys):
    monkeypatch.setenv("KBH_SETTINGS_REQUEST", json.dumps(request))
    cli.main(["claude", "config", "apply", "--config", cfg.path])
    return json.loads(capsys.readouterr().out)


def test_the_form_shows_the_pages_at_the_door(tmp_path, workbench, capsys):
    cfg, p = _box(tmp_path, "desktop", workbench)
    p.set("dedication", "mine")
    m = _show(cfg, capsys)
    f = {x["key"]: x for x in m["fields"]}
    assert f["piton.dedication"]["value"] == "self" and f["piton.preface"]["value"] == "operator"
    assert f["piton.dedication_page"]["value"] == "mine" and "The model writes this page" in f["piton.dedication_page"]["readonly"]
    assert f["piton.preface_page"]["readonly"] is False
    assert {x["section"] for k, x in f.items() if k.startswith("piton.")} == {"The pages at the door"}
    conn = next(c for c in m["connections"] if c["name"] == "piton")
    assert conn["where"] == p.root and "token" not in conn and "shared" in conn["note"]


def test_saving_the_room_page_from_the_form_is_a_version(tmp_path, workbench, monkeypatch, capsys):
    cfg, p = _box(tmp_path, "desktop", workbench)
    before = open(cfg.path, encoding="utf-8").read()
    res = _apply(cfg, {"values": {"piton.preface_page": "How the room works."}}, monkeypatch, capsys)
    assert res["ok"], res
    v = p.latest("preface")
    assert v["text"] == "How the room works." and v["by"] == "operator" and v["why"] == "saved from the settings form"
    assert open(cfg.path, encoding="utf-8").read() == before, "a change that is only the piton's leaves claude.yaml be"


def test_the_models_page_is_refused_from_the_form(tmp_path, workbench, monkeypatch, capsys):
    cfg, p = _box(tmp_path, "desktop", workbench)
    p.set("dedication", "mine")
    res = _apply(cfg, {"values": {"piton.dedication_page": "a fat finger", "piton.preface": "off"}},
                 monkeypatch, capsys)
    assert not res["ok"] and "The model writes this page" in res["refused"]["piton.dedication_page"]
    assert p.read("dedication")["text"] == "mine" and p.options()[0]["preface"] == "operator", "all or nothing"


def test_handing_a_page_over_and_writing_it_is_one_change(tmp_path, workbench, monkeypatch, capsys):
    cfg, p = _box(tmp_path, "desktop", workbench)
    p.set("dedication", "mine")
    res = _apply(cfg, {"values": {"piton.dedication": "operator", "piton.dedication_page": "yours now"}},
                 monkeypatch, capsys)
    assert res["ok"], res
    assert p.options()[0]["dedication"] == "operator" and p.read("dedication")["text"] == "yours now"
    assert not P.is_locked(p.page_path("dedication"))


def test_off_from_the_form_is_off(tmp_path, workbench, monkeypatch, capsys):
    cfg, p = _box(tmp_path, "desktop", workbench)
    assert _apply(cfg, {"values": {"piton.dedication": "off"}}, monkeypatch, capsys)["ok"]
    assert p.options()[0]["dedication"] == "off"
    assert _apply(cfg, {"unset": ["piton.dedication"]}, monkeypatch, capsys)["ok"]
    assert p.options()[0]["dedication"] == "self"


def test_a_page_is_never_emptied_unset_or_over_its_cap(tmp_path, workbench, monkeypatch, capsys):
    cfg, p = _box(tmp_path, "desktop", workbench)
    assert "never emptied" in _apply(cfg, {"values": {"piton.preface_page": "  "}}, monkeypatch, capsys)["refused"]["piton.preface_page"]
    assert "not unset" in _apply(cfg, {"unset": ["piton.preface_page"]}, monkeypatch, capsys)["refused"]["piton.preface_page"]
    assert "capped at 8000" in _apply(cfg, {"values": {"piton.preface_page": "x" * 8001}}, monkeypatch, capsys)["refused"]["piton.preface_page"]
    assert p.latest("preface") is None


def test_config_get_reads_the_piton(tmp_path, workbench, capsys):
    cfg, p = _box(tmp_path, "desktop", workbench)
    p.set("dedication", "mine")
    assert cli.main(["claude", "config", "get", "piton.dedication_page", "--config", cfg.path]) == 0
    assert capsys.readouterr().out.strip() == "mine"


def test_a_box_with_no_piton_shows_no_piton_fields(tmp_path, capsys):
    y = tmp_path / "claude.yaml"
    y.write_text(f"carabiner: claude\nproject: {json.dumps(str(tmp_path))}\npiton: {json.dumps(str(tmp_path / 'none'))}\n",
                 encoding="utf-8")
    m = _show(config.load(str(y)), capsys)
    assert not any(f["key"].startswith("piton.") for f in m["fields"])
    assert not any(c["name"] == "piton" for c in m["connections"])
