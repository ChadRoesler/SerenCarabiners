"""
kbh.schema - the settings a carabiner says it has, in words a person reads.

The yaml beside the .kbh is how a carabiner rolls on a box, and a person who
does not edit yaml still has to be able to change it: Lodestar's Rack draws a
form, the box's Observatory carries the change, and `kbh <carabiner> config`
writes it. None of them knows what a Claude Code permission mode is, and none
of them should: the carabiner says which settings exist, what each one means,
which values it takes and when a change counts, and checks every value it is
handed (22 Oct 2026: "saying go edit a config, kinda poop from a butt").

A Field is one setting, addressed by its yaml key (`session.permission_mode`,
two levels at most, like the yaml). Kinds:

    choice   one of `choices` (or anything, with free_text); a value in
             `expert` is taken only when the change says expert
    tools    a list of tool rules; `suggestions` are the common ones by name
    folder   a folder that exists on this box
    number   between min and max, in `unit`
    note     prose in a file the yaml points at (the framing): the value is
             the file's text
    text     one line

`applies` says when a change counts: next_session, next_wake, or now.

What is NOT here: python, connections, servers and the bookmark. Those are
how the carabiner was clipped on (Starwright's card, `install`), and a token
must never travel through a form.
"""
from __future__ import annotations

import math
import os
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Tuple

KINDS = ("choice", "tools", "folder", "number", "note", "text")
APPLIES = ("next_session", "next_wake", "now")
MAX_NOTE = 64 * 1024


@dataclass
class Field:
    key: str
    label: str
    help: str = ""
    kind: str = "text"
    default: Any = None
    choices: List[Dict[str, str]] = field(default_factory=list)       # {value, label, help}
    expert: List[str] = field(default_factory=list)
    suggestions: List[Dict[str, str]] = field(default_factory=list)   # tools: {value, label}
    free_text: bool = False
    min: Optional[float] = None
    max: Optional[float] = None
    unit: str = ""
    must_hold: str = ""            # note: a placeholder the text cannot lose
    pattern: str = ""              # free text must match it whole (it may end up on a command line)
    required: bool = False         # no default to go back to: cannot be unset
    applies: str = "next_session"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def choice(value: str, label: str, help: str = "") -> Dict[str, str]:
    return {"value": value, "label": label, "help": help}


def base_fields() -> List[Field]:
    """What every carabiner that wakes a model has."""
    return [
        Field("project", "Where it works", kind="folder", applies="next_wake", required=True,
              help="Its folder on this box: where a wake starts, the files it may change, and what it reads first."),
        Field("wake.timeout_seconds", "Give up on a wake after", kind="number", default=900, min=60, max=7200,
              unit="seconds", applies="next_wake",
              help="A wake still running after this long is stopped."),
        Field("framing", "Wake note", kind="note", applies="next_wake", must_hold="{message}",
              help="What it reads first when Seren wakes it: who it is, where its memory lives, when to stop. "
                   "{message} is where the wake's own words go; a note that is only {message} sends them bare."),
    ]


def split_tools(value: Any) -> List[str]:
    """A list of tool rules, from a list or one comma line (what the
    by-hand yaml reader makes of `allowed_tools: Read, Edit`)."""
    items = value if isinstance(value, (list, tuple)) else str(value or "").split(",")
    return [str(t).strip() for t in items if str(t).strip()]


def validate(f: Field, value: Any, expert: bool = False) -> Tuple[Any, str]:
    """(the value to write, "") or (None, why it was refused)."""
    if f.kind == "choice":
        v = "" if value is None else str(value).strip()
        known = [c["value"] for c in f.choices]
        if v in f.expert:
            return (v, "") if expert else (None, f"{v} is an expert setting; it is only taken when the change says so")
        if v not in known and not (f.free_text and v and "\n" not in v):
            return None, f"not one of: {', '.join(k or '(blank)' for k in known)}"
        if v not in known and f.pattern and not re.fullmatch(f.pattern, v):
            return None, "only letters, digits and . _ - : @ / [ ] (it goes on a command line)"
        return v, ""
    if f.kind == "tools":
        tools = split_tools(value)
        bad = [t for t in tools if "\n" in t or "," in t]
        if bad:
            return None, f"a tool rule cannot hold a comma or a new line: {bad[0]!r}"
        return tools, ""
    if f.kind == "folder":
        v = str(value or "").strip()
        if not v:
            return None, "a folder is needed"
        if not os.path.isdir(os.path.expanduser(v)):
            return None, f"no such folder on this box: {v}"
        return v, ""
    if f.kind == "number":
        try:
            n = float(value)
        except (TypeError, ValueError):
            return None, "not a number"
        if not math.isfinite(n):
            return None, "not a number"
        if (f.min is not None and n < f.min) or (f.max is not None and n > f.max):
            return None, f"must be between {f.min:g} and {f.max:g} {f.unit}".rstrip()
        return (int(n) if n.is_integer() else n), ""
    if f.kind == "note":
        v = "" if value is None else str(value)
        if len(v.encode("utf-8")) > MAX_NOTE:
            return None, f"longer than {MAX_NOTE // 1024} KB"
        if f.must_hold and f.must_hold not in v:
            return None, f"it has to keep {f.must_hold}, or what the wake says is lost"
        return v, ""
    v = "" if value is None else str(value)
    if "\n" in v:
        return None, "one line only"
    return v, ""


def get(data: Dict[str, Any], key: str) -> Any:
    """A dotted key out of the yaml's data, or None."""
    cur: Any = data
    for part in key.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def current(f: Field, data: Dict[str, Any]) -> Any:
    """The setting as the yaml has it now, shaped like the field (a tools
    list whichever way the yaml spells it)."""
    v = get(data, f.key)
    if f.kind == "tools":
        return split_tools(v) if v not in (None, "", {}) else []
    if v in (None, {}):
        return f.default
    return v
