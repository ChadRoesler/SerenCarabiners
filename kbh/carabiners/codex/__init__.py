"""
The Codex carabiner (OpenAI's Codex CLI) - the second harness, so the clip
is proven on more than the one it was cut for.

Verbs: register ([mcp_servers.<name>] in $CODEX_HOME/config.toml with an
http_headers_helper - no token in Codex's files), wake (`codex exec` with the
registered servers approved and required for that run, framed, the bookmark
in the message), bookmark (a SessionStart hook in hooks.json, which Codex runs
once a person has trusted it). due: unsupported for now - `codex queue
--thread <id>` puts a message into an existing session, and is the channel
to try once there is a way to know which session is live.

Learned from codex-cli 0.162.1 and its source (14 Oct 2026): the helper is a
single command string run through cmd /C or sh -c, with the environment
cleared to a short list, 10 seconds to answer; default_tools_approval_mode
takes auto | prompt | writes | approve, and approve is the one that never asks.

Belay checks each verb's two sides. Flags: --project DIR, --connection FILE,
--margin FILE, --codex-config PATH, --hooks PATH, --dry-wake (`codex
--version`), --json.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import urllib.error
import urllib.request
from typing import Callable, Dict, List

from ... import settings
from ...belay import Check, held, let_go, skipped
from ...harness import Carabiner
from ...tokens import read_connection
from . import bookmark as _bookmark
from . import register as _register
from . import wake as _wake
from .common import config_path, hooks_path, servers_for, servers_in

# What Codex leaves in a headers helper's environment (codex-rs rmcp-client
# utils.rs DEFAULT_ENV_VARS; protocol shell_environment.rs on Windows).
HELPER_ENV_UNIX = ("HOME", "LOGNAME", "PATH", "SHELL", "USER", "__CF_USER_TEXT_ENCODING", "LANG", "LC_ALL",
                   "TERM", "TMPDIR", "TZ")
HELPER_ENV_WINDOWS = ("PATH", "PATHEXT", "SHELL", "COMSPEC", "SYSTEMROOT", "WINDIR", "SYSTEMDRIVE", "USERNAME",
                      "USERDOMAIN", "USERPROFILE", "HOMEDRIVE", "HOMEPATH", "PROGRAMFILES", "PROGRAMFILES(X86)",
                      "PROGRAMW6432", "PROGRAMDATA", "LOCALAPPDATA", "APPDATA", "TEMP", "TMP", "TMPDIR",
                      "POWERSHELL", "PWSH")
HELPER_TIMEOUT = 10


def run_like_codex(command: str, timeout: float = HELPER_TIMEOUT) -> subprocess.CompletedProcess:
    """Run a helper or hook command string the way Codex runs a headers
    helper: through the shell, with the environment cut down, stdin closed."""
    keep = HELPER_ENV_WINDOWS if os.name == "nt" else HELPER_ENV_UNIX
    env: Dict[str, str] = {k: os.environ[k] for k in keep if k in os.environ}
    if os.name == "nt":
        shell = os.environ.get("COMSPEC") or "cmd.exe"
        return subprocess.run(f'"{shell}" /Q /D /C "{command}"', capture_output=True, text=True, encoding="utf-8",
                              env=env, stdin=subprocess.DEVNULL, timeout=timeout)
    sh = shutil.which("sh") or "/bin/sh"
    return subprocess.run([sh, "-c", command], capture_output=True, text=True, encoding="utf-8", env=env,
                          stdin=subprocess.DEVNULL, timeout=timeout)


class CodexCarabiner(Carabiner):
    name = "codex"
    display = "Codex"
    supports = {"register": True, "wake": True, "bookmark": True, "due": False}
    description = ("Codex (OpenAI's CLI): MCP servers in config.toml with a headers helper, headless wakes "
                   "(codex exec) with the registered servers approved for the run and framed, Margin's bookmark "
                   "as a SessionStart hook once trusted.")

    def register(self, argv: List[str]) -> int:
        return _register.run(argv)

    def wake(self, argv: List[str]) -> int:
        return _wake.run(argv)

    def bookmark(self, argv: List[str]) -> int:
        return _bookmark.run(argv)

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
            cfg = load_for("codex", argv)
        except OSError as e:
            checks.append(lambda e=e: let_go("config", "on belay?", "codex.yaml", f"cannot read it: {e}"))
        project = opt("--project") or (cfg.project if cfg else "")
        connection = opt("--connection") or (cfg.connection(next(iter(cfg.servers))) if cfg and cfg.servers else "")
        margin = opt("--margin") or (cfg.connection(cfg.bookmark) if cfg and cfg.bookmark else "")
        framing_path = cfg.framing_path() if cfg and cfg.framing else ""
        toml = opt("--codex-config") or config_path()
        hooks_file = opt("--hooks") or hooks_path()

        if cfg is not None:
            def config_reads(cfg=cfg) -> Check:
                missing = [k for k in ("project", "python") if not getattr(cfg, k)]
                why = f"{cfg.path}: {len(cfg.servers)} server(s)" + (f"; blank: {', '.join(missing)}" if missing else "")
                return held("config", "on belay?", "codex.yaml", why)
            checks.append(config_reads)
            if framing_path:
                def framing_file(p=framing_path) -> Check:
                    return (held("wake", "on belay?", "framing file", p) if os.path.isfile(p)
                            else let_go("wake", "on belay?", "framing file", f"{p} is named in the config and is not there"))
                checks.append(framing_file)
        else:
            checks.append(lambda: skipped("config", "on belay?", "codex.yaml",
                                          "none found (--config PATH, KBH_CONFIG, beside the .kbh, ~/.seren/kbh/)"))

        # register / on belay?
        def register_entries() -> Check:
            try:
                servers = servers_in(toml)
            except FileNotFoundError:
                return let_go("register", "on belay?", "entries", f"no Codex config at {toml}")
            except Exception as e:  # noqa: BLE001
                return let_go("register", "on belay?", "entries", f"{toml}: {e}")
            if not servers:
                return let_go("register", "on belay?", "entries", "no MCP servers in config.toml")
            inline = sorted(n for n, e in servers.items() if e.get("bearer_token") or
                            any(str(k).lower() == "authorization" for k in (e.get("http_headers") or {})))
            if inline:
                return let_go("register", "on belay?", "entries",
                              f"a token written into config.toml for {', '.join(inline)}; kbh codex register "
                              f"replaces it with a headers helper")
            return held("register", "on belay?", "entries", f"{len(servers)} server(s), no token in config.toml",
                        servers=sorted(servers))
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
                conn = read_connection(connection)
                helper = _register.entry_for(connection, conn,
                                             cfg.python if cfg and cfg.python else None)["http_headers_helper"]
                done = run_like_codex(helper)
                if done.returncode != 0:
                    return let_go("register", "on belay?", "headers helper", (done.stderr or done.stdout).strip()[:200])
                hdrs = json.loads(done.stdout or "{}")
                if not hdrs and conn.has_token_pointer():
                    # A token the helper could not find prints {}, and Codex then connects bare: a 401 later.
                    why = "prints {} although the connection names a token"
                    if conn.bearer_token_env:
                        why += (f" - Codex clears the helper's environment, so ${conn.bearer_token_env} never "
                                f"reaches it: put the token in the yaml (0600) or the keyring")
                    return let_go("register", "on belay?", "headers helper", why)
                return held("register", "on belay?", "headers helper",
                            ("prints an Authorization header" if hdrs else "prints {} (open service)")
                            + ", run the way Codex runs it")
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
            found = _wake.find_codex()
            if not found:
                return let_go("wake", "on belay?", "codex binary",
                              "not on PATH, not in ~/.local/bin or npm's folder; set SEREN_CODEX_BIN")
            return held("wake", "on belay?", "codex binary", found)
        checks.append(binary_found)

        if project:
            def project_servers() -> Check:
                if not os.path.isdir(os.path.expanduser(project)):
                    return let_go("wake", "on belay?", "project", f"no such folder: {project}")
                try:
                    servers = servers_for(project, toml)
                except FileNotFoundError:
                    return let_go("wake", "on belay?", "project", f"no Codex config at {toml}")
                if not servers:
                    return let_go("wake", "on belay?", "project", "no MCP servers enabled: a wake would have no memory")
                return held("wake", "on belay?", "project", f"would approve and require {', '.join(servers)}",
                            servers=servers)
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
                found = _wake.find_codex()
                if not found:
                    return let_go("wake", "belay on.", "codex --version", "no binary")
                done = subprocess.run([found, "--version"], capture_output=True, text=True, encoding="utf-8",
                                      timeout=60)
                return (held("wake", "belay on.", "codex --version", done.stdout.strip()[:80]) if done.returncode == 0
                        else let_go("wake", "belay on.", "codex --version", (done.stderr or done.stdout).strip()[:200]))
            checks.append(binary_runs)
        else:
            checks.append(lambda: skipped("wake", "belay on.", "codex --version", "say --dry-wake to run it"))

        # bookmark
        def hook_present() -> Check:
            try:
                data = settings.load(hooks_file)
            except settings.SettingsError as e:
                return let_go("bookmark", "on belay?", "hook", str(e))
            hooks = data.get("hooks") if isinstance(data.get("hooks"), dict) else {}
            ours = [h for g in (hooks.get(_bookmark.EVENT) or []) if isinstance(g, dict)
                    for h in (g.get("hooks") or []) if isinstance(h, dict) and _bookmark.marker_in(str(h.get("command", "")))]
            if not ours:
                return skipped("bookmark", "on belay?", "hook", f"no bookmark hook in {hooks_file}")
            if len(ours) > 1:
                return let_go("bookmark", "on belay?", "hook", f"{len(ours)} bookmark hooks; there should be one")
            return held("bookmark", "on belay?", "hook",
                        f"{ours[0]['command'][-60:]} - Codex runs it once trusted (/hooks); a wake does not need it")
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

        checks.append(lambda: skipped("due", "on belay?", "channel",
                                      "not yet: codex queue --thread is the channel, once a live session can be named"))
        return checks


CARABINER = CodexCarabiner
