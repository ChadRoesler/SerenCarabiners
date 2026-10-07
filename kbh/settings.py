"""
kbh.settings - add or remove one of our hooks in a harness's JSON settings.

Lifted from Starwright's seren-claude-hook.py (the Claude CLI's clip until
carabiners existed). A hook entry is identified by a MARKER inside its
command - a file name, a verb - so an existing entry carrying the marker is
replaced, never duplicated, and a reinstall is safe.

The file is kept exactly as it was apart from our entry: a settings file that
is not valid JSON is never touched (SettingsError, and why); the previous
file is kept beside it as <name>.seren-bak; the write is atomic. Merging JSON
by hand in a shell is how settings files get mangled, so this is the one
place any carabiner does it.
"""
from __future__ import annotations

import json
import os
import shutil
from typing import Any, Dict, List


class SettingsError(RuntimeError):
    """The settings file could not be changed safely; it was not touched."""


def _strip(entries: List[Any], marker: str) -> List[Any]:
    """The event's matcher groups with every hook carrying `marker` removed;
    a group left with no hooks goes too."""
    out: List[Any] = []
    for group in entries:
        if not isinstance(group, dict):
            out.append(group)
            continue
        hooks = [h for h in (group.get("hooks") or [])
                 if not (isinstance(h, dict) and marker in str(h.get("command", "")))]
        if hooks:
            out.append({**group, "hooks": hooks})
    return out


def load(path: str) -> Dict[str, Any]:
    path = os.path.expanduser(path)
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f) if os.path.getsize(path) else {}
    except (OSError, ValueError) as e:
        raise SettingsError(f"{path} is not valid JSON ({e}); not touching it. Fix it, then run again.")
    if not isinstance(data, dict):
        raise SettingsError(f"{path} is not a JSON object; not touching it.")
    return data


def hooks_with(path: str, event: str, marker: str) -> List[Dict[str, Any]]:
    """Our entries for `event`, as they stand (for belay: present once?)."""
    data = load(path)
    hooks = data.get("hooks") if isinstance(data.get("hooks"), dict) else {}
    out = []
    for group in hooks.get(event) or []:
        for h in (group.get("hooks") or []) if isinstance(group, dict) else []:
            if isinstance(h, dict) and marker in str(h.get("command", "")):
                out.append(h)
    return out


def set_hook(path: str, event: str, marker: str, command: str = "", remove: bool = False) -> str:
    """Add (replace) or remove our hook under `event`. Returns a one-line
    account of what was done."""
    path = os.path.expanduser(path)
    data = load(path)
    hooks = data.get("hooks") if isinstance(data.get("hooks"), dict) else {}
    entries = _strip(list(hooks.get(event) or []), marker)
    if not remove:
        entries.append({"hooks": [{"type": "command", "command": command}]})
    if entries:
        hooks[event] = entries
    else:
        hooks.pop(event, None)
    if hooks:
        data["hooks"] = hooks
    else:
        data.pop("hooks", None)
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    if os.path.exists(path):
        shutil.copy2(path, path + ".seren-bak")
    tmp = path + ".seren-tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
        f.write("\n")
    os.replace(tmp, path)
    return f"{'removed' if remove else 'set'} the {event} hook ({marker}) in {path}"
