"""Shared bits of the GitHub Copilot carabiner: where its files are, and its
MCP config read and written by whole entries.

ONE FILE, TWO HARNESSES. `$COPILOT_HOME/mcp-config.json` (`~/.copilot/` when
the variable is unset) is the Copilot CLI's user config, and VS Code's
Copilot reads the same file as its portable format (docs of 4 Nov 2026). So
one registration serves the terminal agent and the editor. Its shape:

    {"mcpServers": {"<name>": {"type": "http", "url": "...", "headers": {...}, "tools": ["*"]}}}

Everything in the file that is not ours is kept as it was; a file that is not
JSON is never touched; the previous file stays beside it as .seren-bak.
"""
from __future__ import annotations

import json
import os
import shutil
from typing import Any, Dict

from ...settings import SettingsError, load

KEY = "mcpServers"


def copilot_home() -> str:
    return os.path.expanduser(os.environ.get("SEREN_COPILOT_HOME") or os.environ.get("COPILOT_HOME") or "~/.copilot")


def mcp_config_path() -> str:
    return os.path.join(copilot_home(), "mcp-config.json")


def read(path: str) -> Dict[str, Any]:
    """The whole file ({} when there is none). SettingsError when it is not JSON."""
    return load(path)


def servers_in(path: str) -> Dict[str, Dict[str, Any]]:
    data = read(path)
    servers = data.get(KEY)
    return {str(k): v for k, v in servers.items() if isinstance(v, dict)} if isinstance(servers, dict) else {}


def write_entry(path: str, name: str, entry: Any, secret: bool = False) -> None:
    """Put one server in (or, entry None, take it out), the rest untouched.
    `secret`: the entry holds a token, so the file is made 0600."""
    data = read(path)
    servers = data.get(KEY)
    if servers is not None and not isinstance(servers, dict):
        raise SettingsError(f"{path}: {KEY} is not an object; not touching it.")
    servers = dict(servers or {})
    if entry is None:
        servers.pop(name, None)
    else:
        servers[name] = entry
    data[KEY] = servers
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    if os.path.exists(path):
        shutil.copy2(path, path + ".seren-bak")
    tmp = path + ".seren-tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, indent=2)
        f.write("\n")
    if secret:
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
    elif os.path.exists(path):
        try:
            shutil.copymode(path, tmp)
        except OSError:
            pass
    os.replace(tmp, path)
