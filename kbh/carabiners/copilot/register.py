"""
register - tell GitHub Copilot where a Seren MCP server is and how to authenticate.

An entry goes into `$COPILOT_HOME/mcp-config.json`, which the Copilot CLI and
VS Code's Copilot both read (common.py): one registration, two harnesses.

THE TOKEN, AND WHY THIS ONE IS DIFFERENT. Claude Code and Codex run a headers
helper when they connect, so their files never hold a token. Copilot has no
such thing: a header is a value in the file. So:

  - a route kept as `bearer_token_env: NAME` is written as
    `"Authorization": "Bearer ${NAME}"` - no secret in Copilot's file, and the
    variable has to be in the environment Copilot runs in (the docs give
    `${NAME}` for this file as VS Code reads it; for the CLI they do not say);
  - a route with the token inline or in the keyring has it WRITTEN INTO
    mcp-config.json, which is then made 0600. It is a copy: after a token is
    rotated, `register apply` again. belay says when the copy has gone stale.

    kbh copilot register apply [--config copilot.yaml] [--dry]
    kbh copilot register add NAME --connection FILE [--dry]
    kbh copilot register remove NAME
    kbh copilot register list
"""
from __future__ import annotations

import json
import re
import sys
from typing import Any, Dict, List, Tuple

from ...settings import SettingsError
from ...tokens import Connection, read_connection
from .common import mcp_config_path, servers_in, write_entry

_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.\-]{0,63}$")


def authorization(conn: Connection) -> Tuple[str, bool]:
    """(the Authorization header's value or "", whether it is the secret itself)."""
    if conn.bearer_token_env and not conn.bearer_token and not conn.bearer_token_keyring:
        return "Bearer ${" + conn.bearer_token_env + "}", False
    token = conn.resolve_token()
    return (f"Bearer {token}", True) if token else ("", False)


def entry_for(conn: Connection) -> Tuple[Dict[str, Any], bool]:
    header, secret = authorization(conn)
    entry: Dict[str, Any] = {"type": "http", "url": conn.mcp_url}
    if header:
        entry["headers"] = {"Authorization": header}
    entry["tools"] = ["*"]
    return entry, secret


def _shown(entry: Dict[str, Any], secret: bool) -> Dict[str, Any]:
    """The entry as it may be printed: never the token."""
    if not secret:
        return entry
    return {**entry, "headers": {"Authorization": "Bearer <the token, written into the file>"}}


def add(name: str, connection_path: str, dry: bool = False) -> int:
    if not _NAME.match(name):
        print(f"'{name}' is not a usable server name", file=sys.stderr)
        return 64
    try:
        conn = read_connection(connection_path)
    except Exception as e:  # noqa: BLE001
        print(f"cannot read the connection {connection_path}: {type(e).__name__}: {e}", file=sys.stderr)
        return 1
    entry, secret = entry_for(conn)
    path = mcp_config_path()
    if dry:
        print(json.dumps({"name": name, "file": path, "entry": _shown(entry, secret)}, indent=2))
        return 0
    try:
        write_entry(path, name, entry, secret=secret)
    except SettingsError as e:
        print(str(e), file=sys.stderr)
        return 2
    how = ("the token is written into that file (0600): register again after it is rotated" if secret
           else "the bearer is read from the environment when Copilot connects" if "headers" in entry
           else "no token (open service)")
    print(f"registered {name} -> {conn.mcp_url} in {path}; {how}")
    return 0


def remove(name: str) -> int:
    path = mcp_config_path()
    try:
        if name not in servers_in(path):
            print(f"{name}: not in {path}")
            return 0
        write_entry(path, name, None)
    except SettingsError as e:
        print(str(e), file=sys.stderr)
        return 2
    print(f"removed {name} from {path}")
    return 0


def listing() -> int:
    path = mcp_config_path()
    try:
        servers = servers_in(path)
    except SettingsError as e:
        print(str(e), file=sys.stderr)
        return 2
    for name, entry in servers.items():
        auth = str((entry.get("headers") or {}).get("Authorization") or "")
        how = "no auth" if not auth else ("from the environment" if "${" in auth else "token in the file")
        print(f"{name:24s} {entry.get('url') or entry.get('command', '')}  [{how}]")
    if not servers:
        print(f"no MCP servers in {path}")
    return 0


def apply(argv: List[str]) -> int:
    """Register every server the config lists."""
    from ...config import load_for
    try:
        cfg = load_for("copilot", argv)
    except OSError as e:
        print(f"cannot read the config: {e}", file=sys.stderr)
        return 1
    if cfg is None:
        print("no config found: say --config copilot.yaml (kbh copilot install writes one)", file=sys.stderr)
        return 64
    if not cfg.servers:
        print(f"{cfg.path} lists no servers under `servers:`; nothing to register", file=sys.stderr)
        return 1
    rc = 0
    for name in cfg.servers:
        rc = max(rc, add(name, cfg.connection(name), dry="--dry" in argv))
    return rc


def run(argv: List[str]) -> int:
    if not argv or argv[0] not in ("add", "remove", "list", "apply"):
        print("usage: kbh copilot register (apply [--config copilot.yaml] | add NAME --connection FILE | remove NAME "
              "| list) [--dry]", file=sys.stderr)
        return 64
    if argv[0] == "apply":
        return apply(argv[1:])
    if argv[0] == "add":
        if len(argv) < 2 or "--connection" not in argv:
            print("usage: kbh copilot register add NAME --connection FILE [--dry]", file=sys.stderr)
            return 64
        return add(argv[1], argv[argv.index("--connection") + 1], dry="--dry" in argv)
    if argv[0] == "remove":
        return remove(argv[1]) if len(argv) > 1 else 64
    return listing()
