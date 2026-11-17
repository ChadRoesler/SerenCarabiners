"""
bookmark - the bookmark in front of the model as a Codex session starts.

Since 16 Nov 2026 the text is put together by kbh.door: the piton's
dedication (and preface, where codex.yaml says `piton_preface: true`) and
Margin's letter count, whatever of those the box has.

Codex has SessionStart hooks, in the same shape as Claude Code's
($CODEX_HOME/hooks.json: {"hooks": {"SessionStart": [{matcher, hooks: [{type,
command}]}]}}), and plain text a hook prints is added to the session as
developer context. So the hook is `kbh codex bookmark print <connection>`,
merged into hooks.json by kbh.settings (never a hand edit; the file kept as
it was apart from our entry).

TRUST. Codex runs a user hook only after a person has reviewed and trusted
it (/hooks in the CLI); a new or changed hook is skipped until then, with a
startup warning pointing there. So after `install`, open codex once and
trust it. A headless wake does not wait on that: it puts the bookmark in the
message itself (wake.py), and this hook prints nothing when SEREN_KBH_WAKE
is set, so a trusted hook does not say it twice.

It never blocks a session: Margin down, a bad file, a 401 - one short line,
exit 0.

    kbh codex bookmark print CONNECTION
    kbh codex bookmark install CONNECTION [--hooks PATH] [--python P]
    kbh codex bookmark remove [--hooks PATH]
"""
from __future__ import annotations

import os
import sys
from typing import Any, List, Optional

from ... import settings
from ...harness import self_command
from ...tokens import read_connection
from .common import hooks_path, quote_command

EVENT = "SessionStart"
MATCHER = "startup|resume"
MARKERS = ('"codex" "bookmark" "print"', "codex bookmark print")


def marker_in(command: str) -> bool:
    return any(m in command for m in MARKERS)


def _marker() -> str:
    return MARKERS[0] if os.name == "nt" else MARKERS[1]


def fetch(connection_path: str = "", cfg: Any = None, woken: bool = False) -> str:
    """The bookmark's text (kbh.door: the piton's pages, Margin's letter
    count), or lines saying what is missing. Never raises."""
    from ...door import text
    try:
        return text(cfg, "codex", margin=connection_path, woken=woken)
    except Exception as e:  # noqa: BLE001 - never block the session
        return f"(The bookmark is unavailable: {type(e).__name__}: {e})"


def hook_command(connection_path: str = "", python: Optional[str] = None, config_path: str = "") -> str:
    if not connection_path:
        return quote_command(self_command(python) + ["codex", "bookmark", "print", "--config",
                                                     os.path.abspath(config_path)])
    ref = connection_path
    if "#" in ref:
        file, name = ref.rsplit("#", 1)
        ref = f"{os.path.abspath(file)}#{name}"
    else:
        ref = os.path.abspath(ref)
    return quote_command(self_command(python) + ["codex", "bookmark", "print", ref])


def install(connection_path: str, hooks_file: str, python: Optional[str] = None, config_path: str = "") -> str:
    if connection_path:
        read_connection(connection_path)                 # raises if unreadable: refuse to install a dead hook
    elif not config_path:
        raise ValueError("a Margin connection or a config (for the piton alone) is needed")
    # Codex's SessionStart matcher filters on the source: a bookmark belongs
    # on startup and resume, not on clear, compact or fork.
    said = settings.set_hook(hooks_file, EVENT, _marker(), hook_command(connection_path, python, config_path),
                             group={"matcher": MATCHER},
                             handler={"timeout": 15, "statusMessage": "Reading the bookmark"})
    return said + " - open codex once and trust it under /hooks; until then Codex skips it"


def remove(hooks_file: str) -> str:
    return settings.set_hook(hooks_file, EVENT, _marker(), remove=True)


def run(argv: List[str]) -> int:
    if not argv or argv[0] not in ("print", "install", "remove"):
        print("usage: kbh codex bookmark (print [CONNECTION] | install [CONNECTION] [--hooks PATH] | remove)"
              "  - with no CONNECTION, the config's `bookmark:` (codex.yaml)", file=sys.stderr)
        return 64
    if argv[0] == "print" and os.environ.get("SEREN_KBH_WAKE"):
        return 0                                         # a wake put the bookmark in its message already
    from ...config import load_for
    try:
        cfg = load_for("codex", argv)
    except OSError as e:
        if argv[0] == "print":                           # a hook must never fail the session
            print(fetch("", None))
            print(f"(codex.yaml did not read: {e})")
            return 0
        print(f"cannot read the config: {e}", file=sys.stderr)
        return 1
    given = argv[1] if len(argv) > 1 and not argv[1].startswith("--") else ""
    connection = given or (cfg.connection(cfg.bookmark) if cfg and cfg.bookmark else "")
    path = argv[argv.index("--hooks") + 1] if "--hooks" in argv else hooks_path()
    if argv[0] == "print":
        print(fetch(given, cfg))                         # never fails the session; the piton alone is fine
        return 0
    try:
        if argv[0] == "install":
            if not connection and cfg is None:
                print("usage: kbh codex bookmark install CONNECTION [--hooks PATH], or set `bookmark:` in codex.yaml, "
                      "or run it with --config so the hook shows the piton alone", file=sys.stderr)
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
