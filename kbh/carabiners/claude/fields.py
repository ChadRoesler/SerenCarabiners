"""
The Claude Code carabiner's own settings, on top of kbh.schema's base ones:
what a session may do without asking, what it may always use, and the model.

The permission modes are Claude Code's, named as Symposium names them
("manual" is the newer name of "default"). bypassPermissions is an expert
choice: a form never offers it in one click, and a change carrying it is
taken only when it says expert.

THE MODEL LIST is found, not typed into a service (22 Oct 2026: a new model
should show "the day it exists"). Claude Code has no command that lists its
models, so with an ANTHROPIC_API_KEY in this account's environment the list
is Anthropic's own /v1/models; without one, or when that does not answer in a
few seconds, it is the list this carabiner shipped with. Either way the field
takes any model id typed in, so a model released today never waits on a
carabiner release.
"""
from __future__ import annotations

import json
import os
import urllib.request
from typing import Dict, List, Optional

from ...schema import Field, choice

MODES = [
    choice("", "Claude Code's own setting", "Whatever Claude Code itself is set to on this box."),
    choice("manual", "Ask me first", "Asks before it changes a file or runs a command."),
    choice("acceptEdits", "Edit files freely", "Changes files in its folder without asking. Still asks before it runs a command."),
    choice("auto", "Let Claude Code judge", "Claude Code's own safety check decides what can go ahead."),
    choice("dontAsk", "Only the always-allowed list",
           "Uses what is always allowed and turns down everything else. Good when nobody is there to ask."),
    choice("plan", "Look, don't touch", "Reads and plans. Changes nothing."),
]
EXPERT = ["bypassPermissions"]

SHIPPED_MODELS = [
    ("claude-opus-5-5", "Claude Opus 5.5"),
    ("claude-sonnet-5-5", "Claude Sonnet 5.5"),
    ("claude-haiku-5-5", "Claude Haiku 5.5"),
    ("claude-fable-5-1", "Claude Fable 5.1"),
]

TOOLS = [
    ("Read", "Read files"),
    ("Edit", "Edit files"),
    ("Bash", "Run commands"),
    ("WebSearch", "Search the web"),
    ("WebFetch", "Open web pages"),
]

MODELS_URL = "https://api.anthropic.com/v1/models?limit=100"
MODEL_ID = r"[A-Za-z0-9][A-Za-z0-9._:@/\[\]-]{0,99}"


def discover_models(timeout: float = 3.0) -> Optional[List[Dict[str, str]]]:
    """Anthropic's model list, or None (no key here, or no answer)."""
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not key:
        return None
    req = urllib.request.Request(MODELS_URL, headers={"x-api-key": key, "anthropic-version": "2023-06-01"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode("utf-8"))
    except Exception:  # noqa: BLE001 - offline, refused, a bad key: the shipped list stands in
        return None
    models = [choice(str(m["id"]), str(m.get("display_name") or m["id"]))
              for m in data.get("data") or [] if isinstance(m, dict) and m.get("id")]
    return models or None


def fields(servers: List[str], discover: bool = False) -> List[Field]:
    """`discover` asks Anthropic for the list: only for a form being drawn.
    Checking a change never needs it, since any id that looks like one is
    taken."""
    models = (discover_models() if discover else None) or [choice(v, label) for v, label in SHIPPED_MODELS]
    suggestions = [{"value": f"mcp__{s}__*", "label": f"Seren's tools ({s})"} for s in servers]
    suggestions += [{"value": v, "label": label} for v, label in TOOLS]
    return [
        Field("session.permission_mode", "What Claude may do without asking", kind="choice", default="",
              choices=MODES, expert=EXPERT,
              help="The default for sessions Seren starts on this box. A Symposium project or chat can still ask for its own."),
        Field("session.allowed_tools", "Always allowed", kind="tools", default=[], suggestions=suggestions,
              help="Claude never asks before using these, whatever the setting above says. "
                   "A rule like Bash(git status:*) allows one command."),
        # A typed id goes on `claude`'s command line at the next wake, and on
        # Windows that is claude.cmd, read by cmd.exe: `x&calc.exe` would run
        # calc. Hence the pattern: what a model id looks like, nothing more.
        Field("session.model", "Model", kind="choice", default="", free_text=True, applies="next_wake",
              pattern=MODEL_ID, choices=[choice("", "Claude Code's own default")] + models,
              help="The model a wake runs on here. Any model id can be typed in."),
    ]
