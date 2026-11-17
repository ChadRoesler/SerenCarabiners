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
    add      not a setting: the place a form offers "add a setting" (below)

`applies` says when a change counts: next_session, next_wake, or now.

What is NOT here: python, connections, servers and the bookmark. Those are
how the carabiner was clipped on (Starwright's card, `install`), and a token
must never travel through a form.

SETTINGS ADDED ON A BOX (design note, 13 Nov 2026). A carabiner's own fields
are code, so a new one waits on a new .kbh. What a person adds from the Rack does not: it is a name
and one line of text under `custom:` in the yaml,

    custom:
      talk_model: claude-haiku-5-5

listed back as a field like any other (custom true, so a form can offer to
take it away), and read by whatever wants it with
`kbh <carabiner> config get custom.talk_model`. The carabiner checks the name
and that the value is one line; what the value MEANS is the reader's, so a
reader that puts it on a command line checks it first. Still no tokens: a
value is shown back to every form that asks.
"""
from __future__ import annotations

import math
import os
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Tuple

KINDS = ("choice", "tools", "folder", "number", "note", "text", "add")
APPLIES = ("next_session", "next_wake", "now")
MAX_NOTE = 64 * 1024
CUSTOM = "custom"                          # the yaml block settings added on a box live under
CUSTOM_NAME = r"[a-z][a-z0-9_]{0,39}"      # a name a yaml key, a form and a command line can all carry
MAX_CUSTOM = 500


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
    custom: bool = False           # added on this box, not one of the carabiner's own: unset takes it away
    # Shown, never sent back: False, or the reason in words (the Rack draws the
    # value with the reason under it, and `config` refuses a write all the same).
    readonly: Any = False
    section: str = ""              # a header where the section changes (the Rack, 17 Nov 2026)
    section_help: str = ""

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


def custom_name(key: str) -> Optional[str]:
    """The name in `custom.<name>`, or None for any other key."""
    head, _, name = str(key or "").partition(".")
    return name if head == CUSTOM and re.fullmatch(CUSTOM_NAME, name) else None


def custom_field(name: str) -> Field:
    return Field(f"{CUSTOM}.{name}", name.replace("_", " ").capitalize(), kind="text", applies="now", custom=True,
                 help=f"Added on this box. Whatever wants it reads it with: config get {CUSTOM}.{name}")


def custom_fields(data: Dict[str, Any]) -> List[Field]:
    """The settings added on this box, as the yaml has them."""
    block = data.get(CUSTOM)
    names = [str(k) for k in block] if isinstance(block, dict) else []
    return [custom_field(n) for n in names if re.fullmatch(CUSTOM_NAME, n)]


def add_field() -> Field:
    """Where a form offers "add a setting": a name (`pattern`) and a value,
    sent as a change to `custom.<name>`. Not a setting itself."""
    return Field(CUSTOM, "Add a setting", kind="add", pattern=CUSTOM_NAME, applies="now",
                 help="A name and one line of text, kept on this box. Lowercase letters, digits and _ in the "
                      "name. Never a token or a password: it is shown back here.")


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
    if "\n" in v or "\r" in v:
        return None, "one line only"
    if f.custom and len(v) > MAX_CUSTOM:
        return None, f"longer than {MAX_CUSTOM} characters"
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
