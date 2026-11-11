"""
The GitHub Copilot carabiner.

Verbs: register (entries in $COPILOT_HOME/mcp-config.json, which the Copilot
CLI and VS Code's Copilot both read), wake (`copilot -p` with the yaml's
servers allowed, framed; the CLI only). bookmark, presence and due:
unsupported for now. The CLI has sessionStart and sessionEnd hooks
($COPILOT_HOME/hooks/*.json, the session id and folder on stdin, an
`additionalContext` answer) and they are where both would go; whether VS Code
runs them is not known, so neither is claimed yet.

Visual Studio (the IDE) reads a different file (%USERPROFILE%\\.mcp.json,
`servers`) whose header shape its docs do not show; it is not written here.

Belay: the yaml, each server's entry in mcp-config.json (there, pointing where
the yaml says, its token not gone stale), each server answering initialize,
and the CLI when there is one. Flags: --project DIR, --dry-wake, --json.
"""
from __future__ import annotations

import json
import os
import subprocess
import urllib.error
import urllib.request
from typing import Callable, List

from ...belay import Check, held, let_go, skipped
from ...harness import Carabiner
from ...settings import SettingsError
from ...tokens import read_connection
from . import register as _register
from . import wake as _wake
from .common import mcp_config_path, servers_in


class CopilotCarabiner(Carabiner):
    name = "copilot"
    display = "GitHub Copilot"
    supports = {"register": True, "wake": True, "bookmark": False, "due": False, "presence": False}
    description = ("GitHub Copilot: MCP entries in ~/.copilot/mcp-config.json (read by the Copilot CLI and by "
                   "Copilot in VS Code), headless wakes of the CLI with the yaml's servers allowed and framed.")

    def register(self, argv: List[str]) -> int:
        return _register.run(argv)

    def wake(self, argv: List[str]) -> int:
        return _wake.run(argv)

    def default_framing(self) -> str:
        return _wake.default_framing()

    # ── belay ──────────────────────────────────────────────────────────────
    def belay_checks(self, argv: List[str]) -> List[Callable[[], Check]]:
        from ...config import load_for

        def opt(flag: str) -> str:
            return argv[argv.index(flag) + 1] if flag in argv and argv.index(flag) + 1 < len(argv) else ""
        checks: List[Callable[[], Check]] = []
        cfg = None
        try:
            cfg = load_for("copilot", argv)
        except OSError as e:
            checks.append(lambda e=e: let_go("config", "on belay?", "copilot.yaml", f"cannot read it: {e}"))
        project = opt("--project") or (cfg.project if cfg else "")
        framing_path = cfg.framing_path() if cfg and cfg.framing else ""
        mcp_config = mcp_config_path()

        if cfg is not None:
            def config_reads(cfg=cfg) -> Check:
                missing = [k for k in ("project", "python") if not getattr(cfg, k)]
                why = f"{cfg.path}: {len(cfg.servers)} server(s)" + (f"; blank: {', '.join(missing)}" if missing else "")
                return held("config", "on belay?", "copilot.yaml", why)
            checks.append(config_reads)
            if framing_path:
                def framing_file(p=framing_path) -> Check:
                    return (held("wake", "on belay?", "framing file", p) if os.path.isfile(p)
                            else let_go("wake", "on belay?", "framing file", f"{p} is named in the config and is not there"))
                checks.append(framing_file)
        else:
            checks.append(lambda: skipped("config", "on belay?", "copilot.yaml",
                                          "none found (--config PATH, KBH_CONFIG, beside the .kbh, ~/.seren/kbh/)"))

        def registered() -> Check:
            try:
                servers = servers_in(mcp_config)
            except SettingsError as e:
                return let_go("register", "on belay?", "entries", str(e))
            if not servers:
                return let_go("register", "on belay?", "entries", f"no MCP servers in {mcp_config}")
            return held("register", "on belay?", "entries", f"{len(servers)} server(s) in {mcp_config}",
                        servers=sorted(servers))
        checks.append(registered)

        # Every server the yaml lists: its entry, its route, its answer.
        names = list(cfg.servers) if cfg else []
        for name in names:
            tag = f": {name}" if len(names) > 1 else ""
            connection = cfg.connection(name)

            def entry_matches(name=name, connection=connection, tag=tag) -> Check:
                conn = read_connection(connection)
                entry = servers_in(mcp_config).get(name)
                if entry is None:
                    return let_go("register", "on belay?", "entry" + tag, f"{name} is not in {mcp_config}: kbh copilot register apply")
                if str(entry.get("url") or "").rstrip("/") != conn.mcp_url:
                    return let_go("register", "on belay?", "entry" + tag,
                                  f"points at {entry.get('url')}, and the yaml says {conn.mcp_url}: kbh copilot register apply")
                want, secret = _register.authorization(conn)
                have = str((entry.get("headers") or {}).get("Authorization") or "")
                if have != want:
                    return let_go("register", "on belay?", "entry" + tag,
                                  ("the token written into mcp-config.json is not the one the yaml has now"
                                   if secret else "its Authorization header is not what the yaml asks for")
                                  + ": kbh copilot register apply")
                if "${" in have and not os.environ.get(conn.bearer_token_env):
                    return let_go("register", "on belay?", "entry" + tag,
                                  f"reads its token from ${conn.bearer_token_env}, which is not set in this environment; "
                                  f"Copilot needs it set where it runs")
                how = ("the token is a copy in the file (0600); register again after a rotation" if secret
                       else f"the token is read from ${conn.bearer_token_env}" if have else "no token (open service)")
                return held("register", "on belay?", "entry" + tag, f"{conn.mcp_url}; {how}")
            checks.append(entry_matches)

            def server_answers(connection=connection, tag=tag) -> Check:
                conn = read_connection(connection)
                token = conn.resolve_token()
                body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                                   "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                                              "clientInfo": {"name": "kbh-belay", "version": "0"}}}).encode()
                req = urllib.request.Request(conn.mcp_url + "/", data=body, method="POST",
                                             headers={"Content-Type": "application/json",
                                                      "Accept": "application/json, text/event-stream"})
                if token:
                    req.add_header("Authorization", f"Bearer {token}")
                try:
                    with urllib.request.urlopen(req, timeout=8) as r:
                        return held("register", "belay on.", "initialize" + tag, f"{conn.mcp_url} answered {r.status}")
                except urllib.error.HTTPError as e:
                    return let_go("register", "belay on.", "initialize" + tag, f"{conn.mcp_url} answered HTTP {e.code}"
                                  + (" - the token is wrong" if e.code == 401 else ""))
                except Exception as e:  # noqa: BLE001
                    return let_go("register", "belay on.", "initialize" + tag, f"{conn.mcp_url}: {e}")
            checks.append(server_answers)

        # wake: the CLI, when this box has one. An editor alone is a whole install.
        found = _wake.find_copilot()
        if not found:
            checks.append(lambda: skipped("wake", "on belay?", "copilot binary",
                                          "no Copilot CLI on this box: Copilot in the editor is registered and cannot be "
                                          "woken (set SEREN_COPILOT_BIN if the CLI is somewhere else)"))
        else:
            def binary_usable() -> Check:
                if _wake.is_shim(found):
                    return let_go("wake", "on belay?", "copilot binary",
                                  f"{found} is a .cmd shim and cannot carry a wake's message: install the CLI with winget, "
                                  f"or set SEREN_COPILOT_BIN to the .exe")
                return held("wake", "on belay?", "copilot binary", found)
            checks.append(binary_usable)

            if project:
                def project_servers() -> Check:
                    if not os.path.isdir(os.path.expanduser(project)):
                        return let_go("wake", "on belay?", "project", f"no such folder: {project}")
                    servers = sorted(servers_in(mcp_config))
                    if cfg and cfg.servers:
                        servers = cfg.wake_servers(servers)
                    if not servers:
                        return let_go("wake", "on belay?", "project", "none of the yaml's servers is registered: a wake would have no memory")
                    return held("wake", "on belay?", "project", f"would allow {', '.join(servers)}", servers=servers)
                checks.append(project_servers)

                def framing_renders() -> Check:
                    text = _wake.frame("belay", ["x"], "belay",
                                       framing_path=framing_path if framing_path and os.path.isfile(framing_path) else None)
                    missing = [k for k in ("{message}", "{servers}", "{event}", "{when}") if k in text]
                    return (let_go("wake", "on belay?", "framing", f"unfilled: {', '.join(missing)}") if missing
                            else held("wake", "on belay?", "framing", f"{len(text)} characters"))
                checks.append(framing_renders)
            else:
                checks.append(lambda: skipped("wake", "on belay?", "project", "say --project DIR to check it"))

            if "--dry-wake" in argv:
                def binary_runs() -> Check:
                    done = subprocess.run([found, "--version"], capture_output=True, text=True, encoding="utf-8", timeout=60)
                    return (held("wake", "belay on.", "copilot --version", done.stdout.strip()[:80]) if done.returncode == 0
                            else let_go("wake", "belay on.", "copilot --version", (done.stderr or done.stdout).strip()[:200]))
                checks.append(binary_runs)
            else:
                checks.append(lambda: skipped("wake", "belay on.", "copilot --version", "say --dry-wake to run it"))

        checks.append(lambda: skipped("bookmark", "on belay?", "hook", "not built for Copilot yet"))
        checks.append(lambda: skipped("due", "on belay?", "channel", "Copilot has no channel into a live session"))
        return checks


CARABINER = CopilotCarabiner
