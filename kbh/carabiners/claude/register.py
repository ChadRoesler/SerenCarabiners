"""
register - tell Claude Code where a Seren MCP server is and how to authenticate.

Lifted from Starwright's seren_claude_mcp_register / Register-SerenClaudeMcp and
seren-mcp-headers.py, made one thing, and taught the cross-box case the 6 Oct
2026 cutover did by hand.

An entry is written at USER scope (every folder) and never carries a token:
its headersHelper is this carabiner, `kbh claude headers <connection file>`,
run by the harness when it connects. The connection file is the service's
`server:` block (kbh.tokens). A rotated token needs no re-registration.

    kbh claude register add NAME --connection FILE [--dry]
    kbh claude register remove NAME
    kbh claude register list
    kbh claude register bundle --from BUNDLE.json --into DIR [--prefix wren-] [--only workbench ...]
    kbh claude register bundle --from-yamls DIR --host HOST --into DIR [--prefix wren-] [--only ...]

A BUNDLE is how the brain box's tokens reach the harness box: JSON,
{"instance": "wren", "services": {"workbench": {"host": "nuc", "port": 7255,
"bearer_token": "..."}}} - or, the user's way, a folder of the brain box's service
yamls (--from-yamls), each cut to its server block with --host put in for the
bind address. Either way: one connection file per service into --into, and
one MCP entry per service (or only the ones named with --only; the Workbench
alone is the single-door shape).
"""
from __future__ import annotations

import glob
import json
import os
import re
import subprocess
import sys
from typing import Dict, List, Optional

from ...harness import self_command
from ...tokens import Connection, connection_from_bundle_entry, read_connection, write_connection
from .common import claude_json_path, quote_command, servers_by_scope

_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.\-]{0,63}$")


def entry_for(connection_path: str, conn: Connection, python: Optional[str] = None) -> dict:
    helper = quote_command(self_command(python) + ["claude", "headers", os.path.abspath(connection_path)])
    return {"type": "http", "url": conn.mcp_url, "headersHelper": helper}


def _claude() -> Optional[str]:
    from .wake import find_claude
    return find_claude()


def _mcp(claude: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([claude, "mcp", *args], capture_output=True, text=True, encoding="utf-8")


def add(name: str, connection_path: str, dry: bool = False, python: Optional[str] = None) -> int:
    if not _NAME.match(name):
        print(f"'{name}' is not a usable server name", file=sys.stderr)
        return 64
    try:
        conn = read_connection(connection_path)
    except Exception as e:  # noqa: BLE001
        print(f"cannot read the connection file {connection_path}: {type(e).__name__}: {e}", file=sys.stderr)
        return 1
    if not conn.port:
        print(f"{connection_path} names no port", file=sys.stderr)
        return 1
    entry = entry_for(connection_path, conn, python)
    if dry:
        print(json.dumps({"name": name, "scope": "user", "entry": entry}, indent=2))
        return 0
    claude = _claude()
    if claude is None:
        print(f"no `claude` for this account; later, as the person: claude mcp add-json --scope user {name} "
              f"'{json.dumps(entry)}'", file=sys.stderr)
        return 2
    _mcp(claude, "remove", "--scope", "user", name)
    done = _mcp(claude, "add-json", "--scope", "user", name, json.dumps(entry))
    if done.returncode != 0:
        print(f"claude mcp add-json failed for {name}: {(done.stderr or done.stdout).strip()[:300]}",
              file=sys.stderr)
        return 1
    print(f"registered {name} -> {conn.mcp_url} at user scope; the bearer is read from {connection_path} on connect")
    return 0


def remove(name: str) -> int:
    claude = _claude()
    if claude is None:
        print("no `claude` for this account", file=sys.stderr)
        return 2
    done = _mcp(claude, "remove", "--scope", "user", name)
    print(f"removed {name}" if done.returncode == 0 else f"{name}: {(done.stderr or done.stdout).strip()[:200]}")
    return 0


def listing(claude_json: Optional[str] = None) -> int:
    try:
        scopes = servers_by_scope(claude_json or claude_json_path())
    except FileNotFoundError:
        print(f"no Claude Code settings at {claude_json or claude_json_path()}")
        return 0
    seen: Dict[str, List[str]] = {}
    for scope, servers in scopes.items():
        for name, entry in servers.items():
            seen.setdefault(name, []).append(scope)
            how = "headersHelper" if entry.get("headersHelper") else ("inline headers" if entry.get("headers") else "no auth")
            print(f"{scope:40s} {name:24s} {entry.get('url') or entry.get('command', '')}  [{how}]")
    for name, where in seen.items():
        if len(where) > 1:
            print(f"DUPLICATE: {name} is registered at {', '.join(where)}; the local one shadows the user one in "
                  f"that folder, and nothing warns")
    return 0


def _bundle_connections(argv: List[str]) -> Dict[str, Connection]:
    """From --from BUNDLE.json, or --from-yamls DIR --host HOST."""
    out: Dict[str, Connection] = {}
    if "--from" in argv:
        path = argv[argv.index("--from") + 1]
        with open(os.path.expanduser(path), encoding="utf-8") as f:
            bundle = json.load(f)
        for name, entry in (bundle.get("services") or {}).items():
            out[str(name)] = connection_from_bundle_entry(str(name), entry)
        return out
    if "--from-yamls" in argv:
        folder = os.path.expanduser(argv[argv.index("--from-yamls") + 1])
        host = argv[argv.index("--host") + 1] if "--host" in argv else ""
        for path in sorted(glob.glob(os.path.join(folder, "*.yaml")) + glob.glob(os.path.join(folder, "*.yml"))):
            stem = os.path.splitext(os.path.basename(path))[0]
            name = re.sub(r"^seren-", "", stem).replace("-", "_")
            if name.endswith(".yaml.bak") or ".bak." in os.path.basename(path):
                continue
            conn = read_connection(path)
            if not conn.port:
                continue
            if host:
                conn.host = host
            out[name] = conn
        return out
    raise ValueError("say --from BUNDLE.json, or --from-yamls DIR --host HOST")


def bundle(argv: List[str], python: Optional[str] = None) -> int:
    if "--into" not in argv:
        print("usage: kbh claude register bundle (--from BUNDLE.json | --from-yamls DIR --host HOST) --into DIR "
              "[--prefix wren-] [--only NAME ...] [--dry]", file=sys.stderr)
        return 64
    into = os.path.expanduser(argv[argv.index("--into") + 1])
    prefix = argv[argv.index("--prefix") + 1] if "--prefix" in argv else ""
    only = [a for i, a in enumerate(argv) if i > 0 and argv[i - 1] == "--only"]
    try:
        conns = _bundle_connections(argv)
    except Exception as e:  # noqa: BLE001
        print(f"cannot read the bundle: {type(e).__name__}: {e}", file=sys.stderr)
        return 1
    if not conns:
        print("the bundle names no services with a port", file=sys.stderr)
        return 1
    rc = 0
    for name, conn in conns.items():
        path = write_connection(os.path.join(into, f"{name}.yaml"), conn,
                                note=f"service {name}; written {os.path.basename(into)}")
        print(f"wrote {path}")
        if only and name not in only:
            continue
        rc = max(rc, add(f"{prefix}{name}", path, dry="--dry" in argv, python=python))
    return rc


def apply(argv: List[str]) -> int:
    """Register every server the config lists: `servers:` name -> connection
    file. The whole of `register` for a box that has its claude.yaml."""
    from ...config import load_for
    try:
        cfg = load_for("claude", argv)
    except OSError as e:
        print(f"cannot read the config: {e}", file=sys.stderr)
        return 1
    if cfg is None:
        print("no config found: say --config claude.yaml (kbh claude init writes one)", file=sys.stderr)
        return 64
    if not cfg.servers:
        print(f"{cfg.path} lists no servers under `servers:`; nothing to register", file=sys.stderr)
        return 1
    rc = 0
    for name in cfg.servers:
        rc = max(rc, add(name, cfg.connection(name), dry="--dry" in argv, python=cfg.python or None))
    return rc


def run(argv: List[str]) -> int:
    if not argv or argv[0] not in ("add", "remove", "list", "bundle", "apply"):
        print("usage: kbh claude register (apply [--config claude.yaml] | add NAME --connection FILE | remove NAME "
              "| list | bundle ...)", file=sys.stderr)
        return 64
    if argv[0] == "apply":
        return apply(argv[1:])
    python = argv[argv.index("--python") + 1] if "--python" in argv else None
    if argv[0] == "add":
        if len(argv) < 2 or "--connection" not in argv:
            print("usage: kbh claude register add NAME --connection FILE [--dry]", file=sys.stderr)
            return 64
        return add(argv[1], argv[argv.index("--connection") + 1], dry="--dry" in argv, python=python)
    if argv[0] == "remove":
        return remove(argv[1]) if len(argv) > 1 else 64
    if argv[0] == "list":
        return listing(argv[argv.index("--claude-json") + 1] if "--claude-json" in argv else None)
    return bundle(argv[1:], python=python)
