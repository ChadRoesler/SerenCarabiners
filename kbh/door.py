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
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

from . import piton as _piton

HEADER = "Your bookmark - picking up where you left off:"
HISTORY_ALL = 1000


def margin_get(connection: str, path: str, timeout: float = 5.0) -> Tuple[Optional[Dict[str, Any]], str]:
    """(the JSON Margin answered, "") or (None, why not). Never raises."""
    from .tokens import read_connection
    try:
        conn = read_connection(connection)
        token = conn.resolve_token()
    except Exception as e:  # noqa: BLE001
        return None, f"cannot read {connection}: {type(e).__name__}: {e}"
    req = urllib.request.Request(conn.base_url + path)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode("utf-8", "replace") or "{}")
    except urllib.error.HTTPError as e:
        return None, f"HTTP {e.code} from {conn.base_url}{path}" + (" (check the bearer)" if e.code in (401, 403) else "")
    except Exception as e:  # noqa: BLE001
        return None, f"{conn.base_url} did not answer: {e}"
    return (data if isinstance(data, dict) else {}), ""


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
                     f"kbh {carabiner} piton set dedication writes it.")

    lines.append("")
    if bm is not None:
        lines.append(letters_line(bm))
    elif margin_err:
        lines.append(f"(Margin's letters are unavailable: {margin_err})")
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
