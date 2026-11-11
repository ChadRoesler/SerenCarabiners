"""
presence - tell the house a session of this harness is here, and when it goes.

The kitchen keeps a magnet per hand: who is working where, and how to get
back to them. Left to the model, the first minute is the step that gets
skipped: the second session of one partner (10 Nov 2026) walked in, saw one
magnet under the partner's name, and learned it should say which hand it was
only because a memory search happened to turn the note up. So the harness
says it, not the model. Claude Code hands its SessionStart and SessionEnd
hooks the session id and the folder on stdin; this passes them on.

    start   POST <kitchen>/api/sessions {"event": "start", partner, harness, session, cwd, box, source[, hand]}
    end     POST <kitchen>/api/sessions {"event": "end", partner, harness, session, reason[, hand]}

WHAT IT DOES NOT DECIDE. The hand is the kitchen's to name (it knows its
fridges; a carabiner does not know that SerenCarabiners is "carabiner"), so
none is sent unless the yaml pins one, and the answer says which it is.
`source` and `reason` are Claude Code's own words, passed through as given:
whether a /clear is an ending is the kitchen's call. A start never sticks a
magnet to a fridge; holding a repo stays something a session chooses.

A WOKEN SESSION SAYS NOTHING (SEREN_KBH_WAKE): housekeeping holds no repo.

It never blocks or fails a session: no kitchen in the yaml, an older kitchen
without the route (404), a kitchen that is down - exit 0, at most one line.
What `start` prints lands in the session, so it prints what the kitchen
answers (`say`, else the label): the model is told which hand it is.

    kbh claude presence start|end              the hooks (the event's JSON on stdin)
    kbh claude presence install [--settings PATH] [--python P]
    kbh claude presence remove [--settings PATH]

The yaml:

    kitchen:
      url: http://nuc:7431
      bearer_token: "..."          # or bearer_token_env / bearer_token_keyring; none on loopback
      partner: ada                # whose magnets these are
      hand: carabiner              # optional: pin it, else the kitchen names it from the folder
"""
from __future__ import annotations

import json
import os
import socket
import sys
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

from ... import settings
from ...harness import self_command
from ...tokens import read_connection
from .common import quote_command, settings_path

EVENTS = {"start": "SessionStart", "end": "SessionEnd"}
# How each hook is recognised inside a settings file, whichever way it was quoted.
MARKERS = {"start": ('presence" "start', "presence start"), "end": ('presence" "end', "presence end")}
WAKE_ENV = "SEREN_KBH_WAKE"
ROUTE = "/api/sessions"
TIMEOUT = {"start": 4.0, "end": 2.0}          # a session never waits long on a kitchen


def marker_in(which: str, command: str) -> bool:
    return any(m in command for m in MARKERS[which])


def _marker(which: str) -> str:
    return MARKERS[which][0 if os.name == "nt" else 1]


def hook_input(stream=None) -> Dict[str, Any]:
    """What Claude Code wrote on the hook's stdin, or {} (run by hand, or not JSON)."""
    stream = stream if stream is not None else sys.stdin
    try:
        if stream is None or stream.isatty():
            return {}
        data = json.loads(stream.read() or "{}")
    except Exception:  # noqa: BLE001 - a hook must never fail the session
        return {}
    return data if isinstance(data, dict) else {}


def body_for(which: str, cfg, data: Dict[str, Any]) -> Dict[str, Any]:
    body: Dict[str, Any] = {"event": which, "partner": cfg.partner(), "harness": "claude",
                            "session": str(data.get("session_id") or "")}
    if which == "start":
        body["cwd"] = str(data.get("cwd") or os.getcwd())
        body["box"] = socket.gethostname()
        body["source"] = str(data.get("source") or "")
    else:
        body["reason"] = str(data.get("reason") or "")
    hand = os.environ.get("SEREN_KITCHEN_HAND") or cfg.kitchen_hand()
    if hand:
        body["hand"] = hand
    return body


def tell(cfg, body: Dict[str, Any], timeout: float) -> Tuple[Optional[Dict[str, Any]], str]:
    """(the kitchen's answer, "") or (None, why). "" for both = an older
    kitchen without the route, which is nothing to say. Never raises."""
    try:
        conn = read_connection(cfg.kitchen_connection())
        token = conn.resolve_token()
    except Exception as e:  # noqa: BLE001
        return None, f"cannot read the kitchen's route in {cfg.path}: {type(e).__name__}: {e}"
    req = urllib.request.Request(conn.base_url + ROUTE, data=json.dumps(body).encode("utf-8"), method="POST",
                                 headers={"Content-Type": "application/json"})
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            answer = json.loads(r.read().decode("utf-8", "replace") or "{}")
    except urllib.error.HTTPError as e:
        if e.code in (404, 405):
            return None, ""
        return None, f"HTTP {e.code} from {conn.base_url}" + (" - check the bearer" if e.code in (401, 403) else "")
    except Exception as e:  # noqa: BLE001
        return None, f"{conn.base_url} did not answer: {e}"
    return (answer if isinstance(answer, dict) else {}), ""


def said(answer: Dict[str, Any]) -> str:
    """What a starting session is told: the kitchen's own words when it sends
    any, else which hand it is."""
    if str(answer.get("say") or "").strip():
        return str(answer["say"]).strip()
    label, hand = str(answer.get("label") or ""), str(answer.get("hand") or "")
    if not label:
        return ""
    return (f"The kitchen knows this session as {label}." +
            (f" Pass hand=\"{hand}\" on the kitchen's tools, so your notes and your magnet are yours and not "
             f"another session's." if hand else ""))


def hook_command(which: str, config_path: str, python: Optional[str] = None) -> str:
    return quote_command(self_command(python) + ["claude", "presence", which, "--config", os.path.abspath(config_path)])


def install(cfg, settings_file: str, python: Optional[str] = None) -> List[str]:
    read_connection(cfg.kitchen_connection())            # raises if unreadable: refuse to install a dead hook
    return [settings.set_hook(settings_file, EVENTS[w], _marker(w), hook_command(w, cfg.path, python),
                              handler={"timeout": int(TIMEOUT[w]) + 6})
            for w in ("start", "end")]


def remove(settings_file: str) -> List[str]:
    return [settings.set_hook(settings_file, EVENTS[w], _marker(w), remove=True) for w in ("start", "end")]


def run(argv: List[str]) -> int:
    if not argv or argv[0] not in ("start", "end", "install", "remove"):
        print("usage: kbh claude presence (start | end | install [--settings PATH] [--python P] | remove)"
              "  - the kitchen is the config's `kitchen:` (claude.yaml)", file=sys.stderr)
        return 64
    from ...config import load_for
    which = argv[0]
    try:
        cfg = load_for("claude", argv)
    except Exception as e:  # noqa: BLE001 - OSError, or a yaml that does not parse
        if which in EVENTS:
            return 0                                     # a hook must never fail the session
        print(f"cannot read the config: {e}", file=sys.stderr)
        return 1
    if which in EVENTS:
        if os.environ.get(WAKE_ENV) or cfg is None or not cfg.kitchen or not cfg.partner():
            return 0
        body = body_for(which, cfg, hook_input())
        if not body["session"]:
            return 0                                     # run by hand: nothing to name the magnet by
        answer, why = tell(cfg, body, TIMEOUT[which])
        if which == "start":
            if answer is not None and said(answer):
                print(said(answer))
            elif why:
                print(f"(The kitchen was not told about this session: {why})")
        return 0
    path = argv[argv.index("--settings") + 1] if "--settings" in argv else settings_path()
    try:
        if which == "remove":
            print("\n".join(remove(path)))
            return 0
        if cfg is None or not cfg.kitchen:
            print("no `kitchen:` in the config: add its url (and a token if it wants one) to claude.yaml first",
                  file=sys.stderr)
            return 64
        if not cfg.partner():
            print(f"{cfg.path} names a kitchen and no partner: add `partner: <name>` under `kitchen:`", file=sys.stderr)
            return 64
        python = argv[argv.index("--python") + 1] if "--python" in argv else (cfg.python or None)
        try:
            print("\n".join(install(cfg, path, python)))
        except (OSError, ValueError, KeyError) as e:
            print(f"cannot read the kitchen's route: {type(e).__name__}: {e}", file=sys.stderr)
            return 1
    except settings.SettingsError as e:
        print(str(e), file=sys.stderr)
        return 2
    return 0
