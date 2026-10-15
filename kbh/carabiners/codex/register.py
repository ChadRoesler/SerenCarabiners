"""
register - tell Codex where a Seren MCP server is and how to authenticate.

An entry is a [mcp_servers.<name>] table in $CODEX_HOME/config.toml (every
folder: Codex has no per-project user scope) and never carries a token: its
http_headers_helper is this carabiner, `kbh codex headers <connection>`, which
Codex runs when it connects and again after a 401 (codex-rs, rmcp-client
http_headers.rs). A rotated token needs no re-registration - the same shape as
Claude Code's headersHelper, so the same connection files serve both.

WHAT CODEX DOES TO THE HELPER. It runs the string through `cmd /Q /D /C` (or
`sh -c`) with the environment CLEARED down to a few basics (PATH, HOME,
USERPROFILE, SYSTEMROOT...), stdin closed, 10 seconds to answer. So a route
whose token is `bearer_token_env: NAME` cannot be read by the helper unless
that variable is one Codex passes on; a token in the yaml (0600) or the
keyring works. Belay runs the helper that same way and says so.

The file is edited by whole tables (common.set_server), everything else kept,
the old file kept as config.toml.seren-bak. `codex mcp add` is not used: it
has no flag for a headers helper.

    kbh codex register apply [--config codex.yaml] [--dry]
    kbh codex register add NAME --connection FILE [--dry] [--python P]
    kbh codex register remove NAME
    kbh codex register list
"""
from __future__ import annotations

import json
import os
import sys
from typing import Any, Dict, List, Optional

from ...harness import self_command
from ...tokens import Connection, read_connection
from .common import NAME, TomlError, config_path, quote_command, servers_in, set_server

STARTUP_TIMEOUT = 30          # Codex's default is 10s; a cold python helper and a far NUC can need more


def entry_for(connection_path: str, conn: Connection, python: Optional[str] = None) -> Dict[str, Any]:
    ref = connection_path if "#" in connection_path else os.path.abspath(connection_path)
    if "#" in ref:
        file, name = ref.rsplit("#", 1)
        ref = f"{os.path.abspath(file)}#{name}"
    helper = quote_command(self_command(python) + ["codex", "headers", ref])
    return {"url": conn.mcp_url, "http_headers_helper": helper, "startup_timeout_sec": STARTUP_TIMEOUT}


def add(name: str, connection_path: str, dry: bool = False, python: Optional[str] = None,
        config: Optional[str] = None) -> int:
    if not NAME.match(name):
        print(f"'{name}' is not a usable server name (letters, digits, - and _)", file=sys.stderr)
        return 64
    try:
        conn = read_connection(connection_path)
    except Exception as e:  # noqa: BLE001
        print(f"cannot read the connection {connection_path}: {type(e).__name__}: {e}", file=sys.stderr)
        return 1
    entry = entry_for(connection_path, conn, python)
    path = config or config_path()
    if dry:
        print(json.dumps({"name": name, "config": path, "entry": entry}, indent=2))
        return 0
    try:
        set_server(path, name, entry, note=f"the bearer is read from {connection_path} on connect")
    except TomlError as e:
        print(str(e), file=sys.stderr)
        return 2
    print(f"registered {name} -> {conn.mcp_url} in {path}; the bearer is read from {connection_path} on connect")
    return 0


def remove(name: str, config: Optional[str] = None) -> int:
    try:
        print(set_server(config or config_path(), name, None))
    except TomlError as e:
        print(str(e), file=sys.stderr)
        return 2
    return 0


def listing(config: Optional[str] = None) -> int:
    path = config or config_path()
    try:
        servers = servers_in(path)
    except FileNotFoundError:
        print(f"no Codex config at {path}")
        return 0
    except TomlError as e:
        print(f"{path}: {e}", file=sys.stderr)
        return 2
    for name, e in servers.items():
        if e.get("http_headers_helper"):
            how = "headers helper"
        elif e.get("bearer_token_env_var") or e.get("env_http_headers"):
            how = "token from the environment"
        elif e.get("bearer_token") or e.get("http_headers"):
            how = "INLINE headers"
        elif e.get("command"):
            how = "stdio"
        else:
            how = "no auth"
        off = "" if e.get("enabled", True) is not False else "  (disabled)"
        print(f"{name:24s} {e.get('url') or e.get('command', '')}  [{how}]{off}")
    return 0


def apply(argv: List[str]) -> int:
    """Register every server the config lists: `servers:` name -> route or
    connection file. The whole of `register` for a box that has its codex.yaml."""
    from ...config import load_for
    try:
        cfg = load_for("codex", argv)
    except OSError as e:
        print(f"cannot read the config: {e}", file=sys.stderr)
        return 1
    if cfg is None:
        print("no config found: say --config codex.yaml (kbh codex init writes one)", file=sys.stderr)
        return 64
    if not cfg.servers:
        print(f"{cfg.path} lists no servers under `servers:`; nothing to register", file=sys.stderr)
        return 1
    rc = 0
    for name in cfg.servers:
        rc = max(rc, add(name, cfg.connection(name), dry="--dry" in argv, python=cfg.python or None))
    return rc


def run(argv: List[str]) -> int:
    if not argv or argv[0] not in ("add", "remove", "list", "apply"):
        print("usage: kbh codex register (apply [--config codex.yaml] | add NAME --connection FILE | remove NAME "
              "| list)", file=sys.stderr)
        return 64
    config = argv[argv.index("--codex-config") + 1] if "--codex-config" in argv else None
    if argv[0] == "apply":
        return apply(argv[1:])
    if argv[0] == "add":
        if len(argv) < 2 or "--connection" not in argv:
            print("usage: kbh codex register add NAME --connection FILE [--dry]", file=sys.stderr)
            return 64
        python = argv[argv.index("--python") + 1] if "--python" in argv else None
        return add(argv[1], argv[argv.index("--connection") + 1], dry="--dry" in argv, python=python, config=config)
    if argv[0] == "remove":
        return remove(argv[1], config) if len(argv) > 1 else 64
    return listing(config)
