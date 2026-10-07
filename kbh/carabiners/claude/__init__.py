"""
The Claude Code carabiner.

Verbs: register (MCP entries at user scope with a headersHelper), wake
(`claude -p` with the registered servers pre-approved, framed), bookmark (a
SessionStart hook that prints Margin's bookmark). due: unsupported - Claude
Code has no channel into a live session yet; a draft that lands mid-conversation
is found by asking sleep_status, or by the next wake.

Belay checks each verb's two sides. Flags: --project DIR (the folder wakes run
in), --connection FILE (the Workbench or any registered server, for the
register checks), --margin FILE (for the bookmark checks), --dry-wake (run the
binary once, `claude --version`), --json.
"""
from __future__ import annotations

import json
import os
import subprocess
import urllib.error
import urllib.request
from typing import Callable, List

from ... import settings
from ...belay import Check, held, let_go, skipped
from ...harness import Carabiner
from ...tokens import read_connection
from . import bookmark as _bookmark
from . import register as _register
from . import wake as _wake
from .common import claude_json_path, servers_by_scope, servers_for, settings_path


class ClaudeCarabiner(Carabiner):
    name = "claude"
    display = "Claude Code"
    supports = {"register": True, "wake": True, "bookmark": True, "due": False}
    description = ("Claude Code (the CLI): MCP entries at user scope with a headersHelper, headless wakes with "
                   "the registered servers pre-approved and framed, Margin's bookmark as a SessionStart hook.")

    def register(self, argv: List[str]) -> int:
        return _register.run(argv)

    def wake(self, argv: List[str]) -> int:
        return _wake.run(argv)

    def bookmark(self, argv: List[str]) -> int:
        return _bookmark.run(argv)

    # ── belay ──────────────────────────────────────────────────────────────
    def default_framing(self) -> str:
        return _wake.default_framing()

    def belay_checks(self, argv: List[str]) -> List[Callable[[], Check]]:
        from ...config import load_for

        def opt(flag: str) -> str:
            return argv[argv.index(flag) + 1] if flag in argv and argv.index(flag) + 1 < len(argv) else ""
        checks: List[Callable[[], Check]] = []
        cfg = None
        try:
            cfg = load_for("claude", argv)
        except OSError as e:
            checks.append(lambda e=e: let_go("config", "on belay?", "claude.yaml", f"cannot read it: {e}"))
        # Flags win; the config fills what they leave blank.
        project = opt("--project") or (cfg.project if cfg else "")
        connection = opt("--connection") or (cfg.connection(next(iter(cfg.servers))) if cfg and cfg.servers else "")
        margin = opt("--margin") or (cfg.connection(cfg.bookmark) if cfg and cfg.bookmark else "")
        framing_path = cfg.framing_path() if cfg and cfg.framing else ""
        claude_json = opt("--claude-json") or claude_json_path()
        settings_file = opt("--settings") or settings_path()

        if cfg is not None:
            def config_reads(cfg=cfg) -> Check:
                missing = [k for k in ("project", "python") if not getattr(cfg, k)]
                why = f"{cfg.path}: {len(cfg.servers)} server(s)" + (f"; blank: {', '.join(missing)}" if missing else "")
                return held("config", "on belay?", "claude.yaml", why)
            checks.append(config_reads)
            if framing_path:
                def framing_file(p=framing_path) -> Check:
                    return (held("wake", "on belay?", "framing file", p) if os.path.isfile(p)
                            else let_go("wake", "on belay?", "framing file", f"{p} is named in the config and is not there"))
                checks.append(framing_file)
        else:
            checks.append(lambda: skipped("config", "on belay?", "claude.yaml",
                                          "none found (--config PATH, KBH_CONFIG, beside the .kbh, ~/.seren/kbh/)"))

        # register / on belay?
        def register_entries() -> Check:
            try:
                scopes = servers_by_scope(claude_json)
            except FileNotFoundError:
                return let_go("register", "on belay?", "settings", f"no Claude Code settings at {claude_json}")
            names = {n for s in scopes.values() for n in s}
            if not names:
                return let_go("register", "on belay?", "entries", "no MCP servers registered at any scope")
            dup = sorted(n for n in names if sum(n in s for s in scopes.values()) > 1)
            if dup:
                return let_go("register", "on belay?", "entries",
                              f"registered at more than one scope: {', '.join(dup)} (the local one shadows)")
            return held("register", "on belay?", "entries", f"{len(names)} server(s), each at one scope",
                        servers=sorted(names))
        checks.append(register_entries)

        if connection:
            def connection_reads() -> Check:
                conn = read_connection(connection)
                if not conn.port:
                    return let_go("register", "on belay?", "connection", f"{connection} names no port")
                tok = "a token pointer" if conn.has_token_pointer() else "no token (open service)"
                return held("register", "on belay?", "connection", f"{conn.mcp_url}, {tok}")
            checks.append(connection_reads)

            def helper_runs() -> Check:
                entry = _register.entry_for(connection, read_connection(connection))
                helper = entry["headersHelper"]
                import shlex
                parts = shlex.split(helper, posix=(os.name != "nt"))
                if os.name == "nt":
                    parts = [p.strip('"') for p in parts]
                done = subprocess.run(parts, capture_output=True, text=True, encoding="utf-8", timeout=60)
                if done.returncode != 0:
                    return let_go("register", "on belay?", "headersHelper", (done.stderr or done.stdout).strip()[:200])
                hdrs = json.loads(done.stdout or "{}")
                return held("register", "on belay?", "headersHelper",
                            "prints an Authorization header" if hdrs else "prints {} (open service)")
            checks.append(helper_runs)

            def server_answers() -> Check:
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
                        return held("register", "belay on.", "initialize", f"{conn.mcp_url} answered {r.status}")
                except urllib.error.HTTPError as e:
                    return let_go("register", "belay on.", "initialize", f"{conn.mcp_url} answered HTTP {e.code}"
                                  + (" - the token is wrong" if e.code == 401 else ""))
                except Exception as e:  # noqa: BLE001
                    return let_go("register", "belay on.", "initialize", f"{conn.mcp_url}: {e}")
            checks.append(server_answers)

        # wake
        def binary_found() -> Check:
            found = _wake.find_claude()
            if not found:
                return let_go("wake", "on belay?", "claude binary",
                              "not on PATH, not in ~/.local/bin, ~/.claude/local or npm's folder; set SEREN_CLAUDE_BIN")
            return held("wake", "on belay?", "claude binary", found)
        checks.append(binary_found)

        if project:
            def project_servers() -> Check:
                if not os.path.isdir(os.path.expanduser(project)):
                    return let_go("wake", "on belay?", "project", f"no such folder: {project}")
                try:
                    servers = servers_for(project, claude_json)
                except FileNotFoundError:
                    return let_go("wake", "on belay?", "project", f"no settings at {claude_json}")
                if not servers:
                    return let_go("wake", "on belay?", "project", "no MCP servers for this folder: a wake would have no memory")
                return held("wake", "on belay?", "project", f"would pre-approve {', '.join(servers)}", servers=servers)
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
                found = _wake.find_claude()
                if not found:
                    return let_go("wake", "belay on.", "claude --version", "no binary")
                done = subprocess.run([found, "--version"], capture_output=True, text=True, encoding="utf-8",
                                      timeout=60)
                return (held("wake", "belay on.", "claude --version", done.stdout.strip()[:80]) if done.returncode == 0
                        else let_go("wake", "belay on.", "claude --version", (done.stderr or done.stdout).strip()[:200]))
            checks.append(binary_runs)
        else:
            checks.append(lambda: skipped("wake", "belay on.", "claude --version", "say --dry-wake to run it"))

        # bookmark
        def hook_present() -> Check:
            try:
                data = settings.load(settings_file)
            except settings.SettingsError as e:
                return let_go("bookmark", "on belay?", "hook", str(e))
            hooks = data.get("hooks") if isinstance(data.get("hooks"), dict) else {}
            all_hooks = [h for g in (hooks.get(_bookmark.EVENT) or []) if isinstance(g, dict)
                         for h in (g.get("hooks") or []) if isinstance(h, dict)]
            ours = [h for h in all_hooks if _bookmark.marker_in(str(h.get("command", "")))]
            old = [h for h in all_hooks if _bookmark.OLD_MARKER in str(h.get("command", ""))]
            if not ours and not old:
                return skipped("bookmark", "on belay?", "hook", f"no bookmark hook in {settings_file}")
            if len(ours) + len(old) > 1:
                return let_go("bookmark", "on belay?", "hook",
                              f"{len(ours) + len(old)} bookmark hooks; there should be one "
                              f"(kbh claude bookmark install replaces the Starwright-era one)")
            if old:
                return held("bookmark", "on belay?", "hook",
                            "the Starwright-era hook (seren-margin-bookmark.py); kbh claude bookmark install replaces it "
                            "and points it at a connection file")
            return held("bookmark", "on belay?", "hook", ours[0]["command"][-80:])
        checks.append(hook_present)

        if margin:
            def margin_answers() -> Check:
                conn = read_connection(margin)
                token = conn.resolve_token()
                req = urllib.request.Request(conn.base_url + "/health")
                if token:
                    req.add_header("Authorization", f"Bearer {token}")
                try:
                    with urllib.request.urlopen(req, timeout=5) as r:
                        return held("bookmark", "belay on.", "margin /health", f"{conn.base_url} answered {r.status}")
                except urllib.error.HTTPError as e:
                    return let_go("bookmark", "belay on.", "margin /health", f"HTTP {e.code} from {conn.base_url}")
                except Exception as e:  # noqa: BLE001
                    return let_go("bookmark", "belay on.", "margin /health", f"{conn.base_url}: {e}")
            checks.append(margin_answers)

        checks.append(lambda: skipped("due", "on belay?", "channel", "Claude Code has no channel into a live session"))
        return checks


CARABINER = ClaudeCarabiner
