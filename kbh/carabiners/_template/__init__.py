"""
A carabiner for __HARNESS__ - start here.

This is the template every carabiner starts from (`kbh new <name>` copies it).
One carabiner per harness: the program a model lives in. It answers four verbs
and a handshake, declares which verbs it supports, and keeps everything that
is specific to its harness - where the binary is, how a headless session is
started, how settings are edited, how the model should be framed - in here,
so no Seren app ever learns a harness.

What to fill in:

  1. `name`, `display`, `description`, and `supports` (True for the verbs
     this harness can do; the binder answers "unsupported" for the rest).
  2. The verbs you support, as methods. Each takes the remaining argv and
     returns an exit code: 0 done, 1 failed and said why, 2 refused (do not
     wake a model with no memory; do not touch a settings file that is not
     JSON), 64 usage. Print for people on stdout, reasons on stderr.
  3. `framing.md` beside this file: how a woken session is told who it is,
     where its memory is, and when to stop. {message}, {servers}, {event},
     {when} are filled in. The message belongs to the caller; the framing
     is yours.
  4. `belay_checks`: one function per check, returning kbh.belay.held /
     let_go / skipped. Two sides per verb: "on belay?" is what you can check
     about your own files and binary; "belay on." is the harness answering
     (a dry run, an initialize, a health check). A check that raises is
     counted as let go, with the exception as its reason.
  5. Tests. Copy tests/test_claude.py's shape: a fake harness binary that
     records how it was started, your own settings files, never the real
     ones, never a live service.

Helpers the binder gives you: kbh.tokens (connection files: where a Seren
service is and how to present its token; `headers` is already a verb on every
carabiner), kbh.settings (merge one hook into a JSON settings file safely),
kbh.harness.self_command() (a command line that reaches this carabiner again
later, from inside the harness's own settings).
"""
from __future__ import annotations

from typing import Callable, List

from ...belay import Check, skipped
from ...harness import Carabiner


class TemplateCarabiner(Carabiner):
    name = "__NAME__"
    display = "__HARNESS__"
    supports = {"register": False, "wake": False, "bookmark": False, "due": False}
    description = "A carabiner for __HARNESS__: fill in the verbs it supports."

    # def register(self, argv: List[str]) -> int:
    #     """Tell __HARNESS__ where the Seren MCP server is and how to
    #     authenticate - never a token on a command line. Read the connection
    #     file with kbh.tokens.read_connection; write what the harness needs."""
    #     return 0

    # def wake(self, argv: List[str]) -> int:
    #     """Start a headless __HARNESS__ session with the message on stdin
    #     (or however the harness takes it), the Seren MCP server(s)
    #     pre-approved, framed with framing.md. Refuse (exit 2) when no server
    #     is registered: a wake without memory is worse than none."""
    #     return 0

    # def bookmark(self, argv: List[str]) -> int:
    #     """Put Margin's bookmark in front of the model as a session starts:
    #     install whatever __HARNESS__ has for "run this at session start",
    #     pointing at `kbh <name> bookmark print <connection file>`. Never
    #     fail a session: Margin down is one line and exit 0."""
    #     return 0

    # def due(self, argv: List[str]) -> int:
    #     """Tell a LIVE session something is waiting, if __HARNESS__ has a
    #     channel for that (a status line, a notification, a watched file)."""
    #     return 0

    def belay_checks(self, argv: List[str]) -> List[Callable[[], Check]]:
        return [lambda: skipped("register", "on belay?", "template", "nothing to check yet")]


CARABINER = TemplateCarabiner
