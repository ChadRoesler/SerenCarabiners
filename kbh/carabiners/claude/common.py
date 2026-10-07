"""Shared bits of the Claude Code carabiner: where its files are, how to
quote a command for its settings, which servers a project has."""
from __future__ import annotations

import json
import os
import shlex
from typing import Dict, List


def claude_json_path() -> str:
    return os.environ.get("SEREN_CLAUDE_JSON") or os.path.expanduser("~/.claude.json")


def settings_path() -> str:
    return os.environ.get("SEREN_CLAUDE_SETTINGS") or os.path.expanduser("~/.claude/settings.json")


def quote_command(parts: List[str]) -> str:
    """A command line Claude Code can run: its headersHelper and hook
    commands are one string. On Windows every part is double-quoted (the
    way the Starwright cards wrote them, and the way cmd reads them);
    elsewhere shlex does it."""
    if os.name == "nt":
        return " ".join('"' + p.replace('"', '\\"') + '"' for p in parts)
    return shlex.join(parts)


def servers_for(project: str, claude_json: str) -> List[str]:
    """Every MCP server registered for `project`: user scope, local scope
    for that folder, and the folder's own .mcp.json. Raises FileNotFoundError
    when there are no settings at all."""
    with open(claude_json, encoding="utf-8") as f:
        data = json.load(f)
    want = os.path.normcase(os.path.normpath(os.path.expanduser(project)))
    found: List[str] = list((data.get("mcpServers") or {}).keys())           # user scope
    for key, proj in (data.get("projects") or {}).items():
        if os.path.normcase(os.path.normpath(key)) == want:
            found += list((proj or {}).get("mcpServers", {}).keys())          # local scope
    mcp_json = os.path.join(os.path.expanduser(project), ".mcp.json")        # project scope
    if os.path.isfile(mcp_json):
        with open(mcp_json, encoding="utf-8") as f:
            found += list((json.load(f).get("mcpServers") or {}).keys())
    return sorted(set(found))


def servers_by_scope(claude_json: str) -> Dict[str, Dict[str, dict]]:
    """{"user": {name: entry}, "local:<folder>": {name: entry}} - what belay
    reads to find duplicates across scopes."""
    with open(claude_json, encoding="utf-8") as f:
        data = json.load(f)
    out: Dict[str, Dict[str, dict]] = {"user": dict(data.get("mcpServers") or {})}
    for key, proj in (data.get("projects") or {}).items():
        servers = (proj or {}).get("mcpServers") or {}
        if servers:
            out[f"local:{key}"] = dict(servers)
    return out
