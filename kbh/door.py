"""
kbh.door - what a session reads at the door, put together from what the box has.

The bookmark used to be Margin's: one GET /bookmark, printed as it came. Since
the piton (PITON.md, 16 Nov 2026) the pages live on the box and Margin keeps
only the letters, so the carabiner assembles it:

    the preface        from the piton, only where the carabiner's yaml asks
                       (`piton_preface: true`) and never on a wake: the room
                       a preface describes is not always the room a session is in
    the dedication     from the piton
    the letters line   from Margin (a COUNT, never a letter), if the yaml has a
                       `bookmark:` route to one

Whatever is not installed is left out; a box with no Margin gets its
dedication and no letters line, and Margin being down costs one line, not
the dedication.

THE WORKBENCH LOOP (17 Nov 2026). The model writes its pages with the
Workbench's set_dedication / set_preface; the Workbench is rarely on this box
and never writes to it. It holds the newest version it was handed, counted
(seq), and at every session start this asks it for anything past the count
this piton last took (.pulled.json in the piton, not piton.yaml: that file is
the operator's), writes it, and only then puts the page in front of the model.
A page is written to the next session, so landing at the next session start
costs nothing; two boxes each pull the same version and agree.

THE TRANSITION. Until a page has been taken over (`kbh <c> piton import`,
which install runs too), the piton's dedication is empty while Margin's is
not. Then the hook shows Margin's, says so, and says how to take it over: no
session walks in without its dedication because a migration was half done.

Shared by every carabiner: what differs per harness is only how this text
reaches the model (a hook's output, a wake's message), and that stays in each
carabiner's bookmark.py / wake.py. It never raises and never blocks: a hook
must not fail a session.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

from . import piton as _piton

HEADER = "Your bookmark - picking up where you left off:"
HISTORY_ALL = 1000


def get_json(connection: str, path: str, timeout: float = 5.0) -> Tuple[int, Optional[Dict[str, Any]], str]:
    """(HTTP status, the JSON answered or None, why not). 0 when nothing
    answered. Never raises."""
    from .tokens import read_connection
    try:
        conn = read_connection(connection)
        token = conn.resolve_token()
    except Exception as e:  # noqa: BLE001
        return 0, None, f"cannot read {connection}: {type(e).__name__}: {e}"
    req = urllib.request.Request(conn.base_url + path)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            status = r.status
            data = json.loads(r.read().decode("utf-8", "replace") or "{}")
    except urllib.error.HTTPError as e:
        return e.code, None, (f"HTTP {e.code} from {conn.base_url}{path}"
                              + (" (check the bearer)" if e.code in (401, 403) else ""))
    except Exception as e:  # noqa: BLE001
        return 0, None, f"{conn.base_url} did not answer: {e}"
    return status, (data if isinstance(data, dict) else {}), ""


def margin_get(connection: str, path: str, timeout: float = 5.0) -> Tuple[Optional[Dict[str, Any]], str]:
    """(the JSON Margin answered, "") or (None, why not). Never raises."""
    _, data, err = get_json(connection, path, timeout)
    return data, err


# ── the Workbench loop: the model writes through the one door, the box pulls ──

PULLED = ".pulled.json"          # in the piton, per page: {seq: the Workbench's count last seen,
                                 #                       version: this piton's version right after}
PULL_TIMEOUT = 1.5               # LAN: a Workbench that has not answered in 1.5 s will not in 3 (lodestar)


def workbench_connection(cfg: Any) -> str:
    """Which route is the Workbench: the yaml's `workbench: NAME`, else the
    one server when there is only one (the single-door shape), else the one
    server named `<instance>-workbench` (Starwright's card registers it under
    that name beside any --server extras, 18 Nov 2026), else none."""
    if cfg is None:
        return ""
    name = str(cfg.extra.get("workbench") or "").strip()
    if not name and len(cfg.servers) == 1:
        name = next(iter(cfg.servers))
    if not name:
        named = [n for n in cfg.servers if n == "workbench" or n.endswith("-workbench")]
        name = named[0] if len(named) == 1 else ""
    return cfg.connection(name) if name and name in cfg.servers else ""


def _pulled(p: "_piton.Piton") -> Dict[str, Dict[str, int]]:
    """{page: {seq, version}}. A file that does not read is no record: the
    next pull asks from the start, which only means taking the newest again."""
    try:
        with open(os.path.join(p.root, PULLED), encoding="utf-8") as f:
            data = json.load(f)
        out: Dict[str, Dict[str, int]] = {}
        for page, rec in (data.items() if isinstance(data, dict) else []):
            if page in _piton.PAGES and isinstance(rec, dict):
                out[page] = {"seq": int(rec.get("seq") or 0), "version": int(rec.get("version") or 0)}
        return out
    except (OSError, ValueError, TypeError):
        return {}


def _save_pulled(p: "_piton.Piton", pulled: Dict[str, Dict[str, int]]) -> None:
    _piton._write_atomic(os.path.join(p.root, PULLED), json.dumps(pulled, indent=2) + "\n")


def pull(cfg: Any, p: "_piton.Piton", timeout: float = PULL_TIMEOUT) -> List[str]:
    """Take what the model wrote through the Workbench (set_dedication,
    set_preface) into this box's piton.

    ONE CALL in the common case (lodestar, 17 Nov 2026): GET /pages is the
    Workbench's summary, each page's `seq` or null; only a page whose seq
    moved past what this piton last saw is fetched (/pages/<page>?after=N). A
    Workbench that is down costs one short timeout; one from before /pages
    (404) is quiet.

    NO CLOCKS (workbench, 17 Nov 2026). "Newer" is the Workbench's count, and
    "this box changed the page since the last pull" (a hand edit, the
    operator) is this piton's own version against the one recorded right
    after that pull: never one box's clock against another's. Then the box's
    page is kept and the Workbench still holds the other, so nothing is lost.
    Who writes the page is this box's call (piton.yaml). Returns lines worth
    showing; nothing when nothing is new."""
    conn = workbench_connection(cfg)
    if not conn or not p.exists():
        return []
    status, summary, err = get_json(conn, "/pages", timeout)
    if status == 404:
        return []                                      # a Workbench from before /pages
    if summary is None:
        return [f"(the Workbench's pages could not be checked: {err})"]
    lines: List[str] = []
    pulled = _pulled(p)
    changed = False
    opts, _ = p.options()
    for page in _piton.PAGES:
        rec = pulled.get(page, {"seq": 0, "version": 0})
        info = summary.get(page)
        try:
            moved = isinstance(info, dict) and int(info.get("seq") or 0) > rec["seq"]
        except (TypeError, ValueError):
            moved = False
        if not moved:
            continue
        status, data, err = get_json(conn, f"/pages/{page}?after={rec['seq']}", timeout)
        if status in (204, 404) or (status == 200 and not data):
            continue
        if data is None:
            lines.append(f"(the Workbench's {page} could not be fetched: {err})")
            continue
        try:
            seq = int(data.get("seq") or 0)
            text_ = str(data.get("text") or "")
        except (TypeError, ValueError):
            lines.append(f"(the Workbench answered something that is not a {page}; left as it is)")
            continue
        if seq <= rec["seq"]:
            continue
        # The piton keeps ISO times; the Workbench sends them too (its first
        # stand-in in the tests sent floats, and the real door never does).
        set_at = _piton._epoch(data.get("set_at")) or None
        changed = True
        p.read(page)                                   # a hand edit waiting on disk becomes a version first
        have = p.latest(page)
        here = have["version"] if have else 0
        if opts[page] != "self":
            lines.append(f"(the {page} you wrote through the Workbench was not taken: on this box it is "
                         f"{'off' if opts[page] == 'off' else 'written by the operator'} - piton.yaml)")
            pulled[page] = {"seq": seq, "version": here}
            continue
        if rec["seq"] and have is not None and here > rec["version"] and have.get("by") != "pull":
            lines.append(f"(the {page} changed on this box since the last pull (version {here}); the box's is "
                         f"kept, and the Workbench still holds the one written through it)")
            pulled[page] = {"seq": seq, "version": here}
            continue
        try:
            entry, new = p.set(page, text_, why=data.get("why"), by="pull", set_at=set_at)
            pulled[page] = {"seq": seq, "version": entry["version"]}
            if new:
                lines.append(f"(your {page} came from the Workbench: version {entry['version']} here)")
        except _piton.PitonError as e:
            pulled[page] = {"seq": seq, "version": here}
            lines.append(f"(the Workbench's {page} was not taken: {e})")
    if changed:
        try:
            _save_pulled(p, pulled)
        except OSError as e:
            lines.append(f"(piton: could not remember what was pulled: {e}; it will be asked again)")
    return lines


def letters_line(bm: Dict[str, Any]) -> str:
    """Margin's own words for the count (seren_margin.bookmark)."""
    n = int(bm.get("unread_letters") or 0)
    if not n:
        return "No unread letters."
    oldest = bm.get("oldest_unread_age") or "a while ago"
    return (f"{n} unread letter{'s' if n != 1 else ''} from your other sessions, "
            f"the oldest from {oldest}. read_letters opens them.")


def text(cfg: Any, carabiner: str, margin: str = "", woken: bool = False) -> str:
    """The whole bookmark as a hook prints it. `margin` is a connection
    reference that overrides the yaml's `bookmark:` (the hook's argument)."""
    root = cfg.piton_dir() if cfg is not None else _piton.locate()
    p = _piton.Piton(root)
    has_piton = p.exists()
    if not margin and cfg is not None and cfg.bookmark:
        margin = cfg.connection(cfg.bookmark)
    bm, margin_err = margin_get(margin, "/bookmark") if margin else (None, "")

    lines: List[str] = [HEADER, ""]
    problems: List[str] = []
    try:
        pulled_lines = pull(cfg, p) if has_piton else []   # what the model wrote through the Workbench, first
    except Exception as e:  # noqa: BLE001 - a hook never fails the session
        pulled_lines = [f"(the Workbench pull failed: {type(e).__name__}: {e})"]

    want_preface = bool(cfg is not None and cfg.extra.get("piton_preface") is True) and not woken
    if has_piton and want_preface:
        r = p.read("preface")
        problems += r["problems"]
        if r["text"]:
            lines += [f"The room (preface, version {r['version']}):", r["text"], ""]

    ded = p.read("dedication") if has_piton else None
    if ded is not None:
        problems += [x for x in ded["problems"] if x not in problems]
    if ded is not None and ded["text"]:
        lines += [f"Your dedication (version {ded['version']}, written {_piton.age(ded['set_at'])}):", ded["text"]]
    elif ded is not None and ded["writer"] == "off":
        pass
    elif bm and isinstance(bm.get("dedication"), dict) and bm["dedication"].get("text"):
        md = bm["dedication"]
        lines += [f"Your dedication (version {md.get('version')}, written {_piton.age(md.get('set_at'))}; "
                  f"still Margin's copy):", str(md["text"]), "",
                  f"(This page has not been taken over by the piton yet: kbh {carabiner} piton import "
                  f"brings it and every version across.)"]
    else:
        lines.append(f"No dedication yet - the page at the front, written to your other sessions. "
                     f"set_dedication writes it (or kbh {carabiner} piton set dedication).")

    lines.append("")
    if bm is not None:
        lines.append(letters_line(bm))
    elif margin_err:
        lines.append(f"(Margin's letters are unavailable: {margin_err})")
    lines += pulled_lines
    for x in problems:
        lines.append(f"(piton: {x})")
    return "\n".join(lines).rstrip()


def import_from_margin(p: "_piton.Piton", connection: str, carabiner: str) -> Tuple[List[str], bool]:
    """Take the pages over from Margin with every version, once: a page the
    piton already has a version of is never touched (so this is safe to run
    again, and safe on a box where someone wrote a page by hand). Returns
    (lines to print, whether everything that could come across did)."""
    lines: List[str] = []
    ok = True
    p.make()
    for page in _piton.PAGES:
        p.read(page)                                   # a page written here by hand becomes a version first
        have = p.latest(page)
        if have is not None:
            lines.append(f"{page}: kept - the piton already has version {have['version']}; nothing imported")
            continue
        data, err = margin_get(connection, f"/{page}?history={HISTORY_ALL}")
        if data is None:
            older = err.startswith("HTTP 404") and page == "dedication"
            lines.append(f"{page}: not imported - " + (
                "this Margin is older than its history routes; upgrade it, then " if older else f"{err}; ")
                + f"kbh {carabiner} piton import")
            ok = False
            continue
        hist = data.get("history")
        if hist is None:
            lines.append(f"{page}: not imported - this Margin does not send history yet; upgrade it, "
                         f"then kbh {carabiner} piton import")
            ok = False
            continue
        versions = sorted((v for v in hist if isinstance(v, dict) and str(v.get("text") or "").strip()),
                          key=lambda v: int(v.get("version") or 0))
        if not versions:
            lines.append(f"{page}: Margin has none")
            continue
        # A page Margin already holds is history, not a new write: the cap must
        # fit it, never skip it. 17 Nov 2026, the first real migration: Margin's
        # v6 dedication was 2253 characters against a cap of 2000, so v6 was
        # skipped and the piton's page would have been v5 - an older self at
        # the door. Raise the cap in piton.yaml to fit, and say so.
        longest = max(len(_piton._clean(v["text"])) for v in versions)
        cap = p.options()[0]["caps"][page]
        if longest > cap:
            from . import yamledit
            new_cap = -(-longest // 500) * 500                  # the next 500 up: room for the next edit
            try:
                text = open(p.yaml_path, encoding="utf-8").read()
                yamledit.write(p.yaml_path, yamledit.set(text, f"caps.{page}", new_cap))
                lines.append(f"{page}: Margin's longest version is {longest} characters; the cap in piton.yaml "
                             f"is raised from {cap} to {new_cap} so every version comes across")
            except (OSError, ValueError) as e:
                lines.append(f"{page}: Margin's longest version is {longest} characters and the cap of {cap} could "
                             f"not be raised ({e}); raise caps.{page} in piton.yaml, then piton import")
                ok = False
                continue
        brought = 0
        for v in versions:
            try:
                _, changed = p.set(page, str(v["text"]), why=v.get("why"), by="margin",
                                   set_at=float(v.get("set_at") or 0) or None)
                brought += bool(changed)
            except _piton.PitonError as e:
                lines.append(f"{page}: Margin's version {v.get('version')} skipped: {e}")
                ok = False
        latest = p.latest(page)
        lines.append(f"{page}: {brought} version{'s' if brought != 1 else ''} from Margin"
                     + (f"; the page is version {latest['version']}" if latest else ""))
    return lines, ok
