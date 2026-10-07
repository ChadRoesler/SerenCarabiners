"""
bookmark - Margin's bookmark in front of the model as a session starts.

Lifted from Starwright's seren-margin-bookmark.py and the --claude-bookmark
half of seren-claude-hook.py. A Claude Code SessionStart hook runs
`kbh claude bookmark print <connection file>`; whatever it prints lands in the
session - and SessionStart fires for a headless `claude -p` too, so a woken
session gets the bookmark as well. Letters go both ways.

It never blocks a session: Margin down, a bad file, a 401 - one short line,
exit 0. The bearer is read from the connection file by the family's rules,
never from a command line. The 6 Oct 2026 move left the hook pointing at the
desktop Margin's yaml after Margin had gone to the NUC; a connection file is
the thing to point it at, and belay checks it answers.

    kbh claude bookmark print CONNECTION
    kbh claude bookmark install CONNECTION [--settings PATH] [--python P]
    kbh claude bookmark remove [--settings PATH]
"""
from __future__ import annotations

import os
import sys
import urllib.error
import urllib.request
from typing import List, Optional

from ... import settings
from ...harness import self_command
from ...tokens import read_connection
from .common import quote_command, settings_path

EVENT = "SessionStart"
# How our hook is recognised inside a settings file, whichever way the command
# was quoted; and the Starwright-era hook it replaces.
MARKERS = ('bookmark" "print', "bookmark print")
OLD_MARKER = "seren-margin-bookmark.py"


def marker_in(command: str) -> bool:
    return any(m in command for m in MARKERS)


def _marker() -> str:
    return MARKERS[0] if os.name == "nt" else MARKERS[1]


def fetch(connection_path: str, timeout: float = 5.0) -> str:
    """The bookmark's text, or one line saying why not. Never raises."""
    try:
        conn = read_connection(connection_path)
        token = conn.resolve_token()
    except Exception as e:  # noqa: BLE001 - never block the session
        return f"(Margin's bookmark is unavailable: cannot read {connection_path}: {type(e).__name__}: {e})"
    req = urllib.request.Request(f"{conn.base_url}/bookmark?format=text")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read().decode("utf-8", "replace").rstrip()
    except urllib.error.HTTPError as e:
        return (f"(Margin's bookmark is unavailable: HTTP {e.code} from {conn.base_url} - "
                f"{'an older Margin without /bookmark?' if e.code == 404 else 'check the bearer'})")
    except Exception as e:  # noqa: BLE001
        return f"(Margin's bookmark is unavailable: {conn.base_url} did not answer: {e})"
    return "Your bookmark, from Margin - picking up where you left off:\n\n" + body


def hook_command(connection_path: str, python: Optional[str] = None) -> str:
    return quote_command(self_command(python) + ["claude", "bookmark", "print", os.path.abspath(connection_path)])


def install(connection_path: str, settings_file: str, python: Optional[str] = None) -> str:
    read_connection(connection_path)                     # raises if unreadable: refuse to install a dead hook
    # The Starwright-era hook, if present, goes: two bookmarks would print twice.
    settings.set_hook(settings_file, EVENT, OLD_MARKER, remove=True)
    return settings.set_hook(settings_file, EVENT, _marker(), hook_command(connection_path, python))


def remove(settings_file: str) -> str:
    return settings.set_hook(settings_file, EVENT, _marker(), remove=True)


def run(argv: List[str]) -> int:
    if not argv or argv[0] not in ("print", "install", "remove"):
        print("usage: kbh claude bookmark (print [CONNECTION] | install [CONNECTION] [--settings PATH] | remove)"
              "  - with no CONNECTION, the config's `bookmark:` (claude.yaml)", file=sys.stderr)
        return 64
    from ...config import load_for
    try:
        cfg = load_for("claude", argv)
    except OSError as e:
        print(f"cannot read the config: {e}", file=sys.stderr)
        return 1
    # the connection: given, else the config's bookmark entry
    given = argv[1] if len(argv) > 1 and not argv[1].startswith("--") else ""
    connection = given or (cfg.connection(cfg.bookmark) if cfg and cfg.bookmark else "")
    path = argv[argv.index("--settings") + 1] if "--settings" in argv else settings_path()
    if argv[0] == "print":
        if not connection:
            print("(Margin's bookmark is unavailable: no connection file given and no `bookmark:` in the config)")
            return 0                                     # a hook must never fail the session
        print(fetch(connection))
        return 0
    try:
        if argv[0] == "install":
            if not connection:
                print("usage: kbh claude bookmark install CONNECTION [--settings PATH], or set `bookmark:` in claude.yaml",
                      file=sys.stderr)
                return 64
            python = argv[argv.index("--python") + 1] if "--python" in argv else (cfg.python if cfg and cfg.python else None)
            try:
                print(install(connection, path, python))
            except (OSError, ValueError) as e:
                print(f"cannot read the connection file {connection}: {type(e).__name__}: {e}", file=sys.stderr)
                return 1
        else:
            print(remove(path))
    except settings.SettingsError as e:
        print(str(e), file=sys.stderr)
        return 2
    return 0
