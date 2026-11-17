"""
bookmark - the bookmark in front of the model as a session starts.

Lifted from Starwright's seren-margin-bookmark.py and the --claude-bookmark
half of seren-claude-hook.py. A Claude Code SessionStart hook runs
`kbh claude bookmark print [CONNECTION]`; whatever it prints lands in the
session - and SessionStart fires for a headless `claude -p` too, so a woken
session gets the bookmark as well. Letters do not go both ways any more
(18 Oct 2026): a wake is housekeeping, and opening a letter marks it read,
so a 3 a.m. review was taking the awake session's mail. A woken session
(SEREN_KBH_WAKE, set by wake.py) gets the bookmark with a line telling it
to leave the letters closed.

WHAT IT PRINTS (16 Nov 2026) is no longer Margin's page as it came: kbh.door
puts it together from the piton (the dedication, and the preface where
claude.yaml says `piton_preface: true`) and Margin (the letter count). So a
box with no Margin still gets the hook, pointed at its yaml instead of a
connection; until the dedication has been taken over from Margin, Margin's
copy is shown and says how to take it over.

It never blocks a session: Margin down, a bad file, a 401 - one short line,
exit 0. The bearer is read from the connection file by the family's rules,
never from a command line. The 6 Oct 2026 move left the hook pointing at the
desktop Margin's yaml after Margin had gone to the NUC; a connection file is
the thing to point it at, and belay checks it answers.

    kbh claude bookmark print [CONNECTION]
    kbh claude bookmark install [CONNECTION] [--settings PATH] [--python P]
    kbh claude bookmark remove [--settings PATH]
"""
from __future__ import annotations

import os
import sys
from typing import Any, List, Optional

from ... import settings
from ...harness import self_command
from ...tokens import read_connection
from .common import quote_command, settings_path

EVENT = "SessionStart"
# How our hook is recognised inside a settings file, whichever way the command
# was quoted; and the Starwright-era hook it replaces.
MARKERS = ('bookmark" "print', "bookmark print")
OLD_MARKER = "seren-margin-bookmark.py"
WAKE_ENV = "SEREN_KBH_WAKE"
WOKEN = ("You were woken, not opened by a person: any letters counted above are for the awake you. "
         "Leave them closed - opening one marks it read, and the awake you would never see it arrive.")


def marker_in(command: str) -> bool:
    return any(m in command for m in MARKERS)


def _marker() -> str:
    return MARKERS[0] if os.name == "nt" else MARKERS[1]


def fetch(connection_path: str = "", cfg: Any = None, woken: bool = False) -> str:
    """The bookmark's text (kbh.door), or lines saying what is missing. Never raises."""
    from ...door import text
    try:
        return text(cfg, "claude", margin=connection_path, woken=woken)
    except Exception as e:  # noqa: BLE001 - never block the session
        return f"(The bookmark is unavailable: {type(e).__name__}: {e})"


def hook_command(connection_path: str = "", python: Optional[str] = None, config_path: str = "") -> str:
    tail = [os.path.abspath(connection_path)] if connection_path else ["--config", os.path.abspath(config_path)]
    return quote_command(self_command(python) + ["claude", "bookmark", "print"] + tail)


def install(connection_path: str, settings_file: str, python: Optional[str] = None, config_path: str = "") -> str:
    if connection_path:
        read_connection(connection_path)                 # raises if unreadable: refuse to install a dead hook
    elif not config_path:
        raise ValueError("a Margin connection or a config (for the piton alone) is needed")
    # The Starwright-era hook, if present, goes: two bookmarks would print twice.
    settings.set_hook(settings_file, EVENT, OLD_MARKER, remove=True)
    return settings.set_hook(settings_file, EVENT, _marker(), hook_command(connection_path, python, config_path))


def remove(settings_file: str) -> str:
    return settings.set_hook(settings_file, EVENT, _marker(), remove=True)


def run(argv: List[str]) -> int:
    if not argv or argv[0] not in ("print", "install", "remove"):
        print("usage: kbh claude bookmark (print [CONNECTION] | install [CONNECTION] [--settings PATH] | remove)"
              "  - with no CONNECTION, the config's `bookmark:` (claude.yaml), or the piton alone",
              file=sys.stderr)
        return 64
    from ...config import load_for
    try:
        cfg = load_for("claude", argv)
    except OSError as e:
        if argv[0] == "print":                           # a hook must never fail the session
            print(fetch("", None, woken=bool(os.environ.get(WAKE_ENV))))
            print(f"(claude.yaml did not read: {e})")
            return 0
        print(f"cannot read the config: {e}", file=sys.stderr)
        return 1
    # the connection: given, else the config's bookmark entry
    given = argv[1] if len(argv) > 1 and not argv[1].startswith("--") else ""
    connection = given or (cfg.connection(cfg.bookmark) if cfg and cfg.bookmark else "")
    path = argv[argv.index("--settings") + 1] if "--settings" in argv else settings_path()
    if argv[0] == "print":
        woken = bool(os.environ.get(WAKE_ENV))
        print(fetch(given, cfg, woken=woken))
        if woken:
            print("\n" + WOKEN)
        return 0
    try:
        if argv[0] == "install":
            if not connection and cfg is None:
                print("usage: kbh claude bookmark install CONNECTION [--settings PATH], or set `bookmark:` in "
                      "claude.yaml, or run it with --config so the hook shows the piton alone", file=sys.stderr)
                return 64
            python = argv[argv.index("--python") + 1] if "--python" in argv else (cfg.python if cfg and cfg.python else None)
            try:
                print(install(connection, path, python, config_path=cfg.path if cfg is not None else ""))
            except (OSError, ValueError) as e:
                print(f"cannot read the connection file {connection}: {type(e).__name__}: {e}", file=sys.stderr)
                return 1
        else:
            print(remove(path))
    except settings.SettingsError as e:
        print(str(e), file=sys.stderr)
        return 2
    return 0
