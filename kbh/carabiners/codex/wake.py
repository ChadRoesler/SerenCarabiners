"""
wake - start a headless Codex session with a message, framed.

The Claude carabiner's two decisions hold here too: the server list is read
when the model is woken, not when it was installed (the Observatory holds
this verb, not a list); and the binary is found for the account, not trusted
to the service's PATH (SEREN_CODEX_BIN wins).

HOW CODEX IS WOKEN:

    codex exec --skip-git-repo-check --color never -C <project>
          -c mcp_servers.<each>.default_tools_approval_mode=approve
          -c mcp_servers.<each>.required=true
          -                                   (the framed message on stdin)

- Pre-approved for THIS run only. A headless run has nobody to answer an
  approval, and Claude's equivalent is --allowedTools mcp__<server>. `approve`
  is the mode that gives way to any other (AppToolApproval::restrict_to in
  codex-rs/config/src/mcp_types.rs); config.toml is not changed, so an
  interactive session still asks the way it was set to.
- `required`: a memory server that does not come up stops the run rather
  than leaving the model awake without its memory.
- The sandbox stays Codex's exec default, read-only: like `claude -p` with
  only the MCP tools allowed, a woken model talks to its memory, it does not
  edit the project. --sandbox workspace-write widens it on purpose.
- THE BOOKMARK RIDES IN THE MESSAGE. Claude's SessionStart hook fires for
  `claude -p`; Codex runs a user hook only once it is trusted (/hooks), and
  an untrusted one is skipped without a word. So a wake fetches Margin's
  bookmark itself and puts it above the framing, and sets SEREN_KBH_WAKE=1 so
  a trusted hook that does fire prints nothing the second time.

    kbh codex wake --project DIR --run [MESSAGE]      (MESSAGE or stdin)
    kbh codex wake --project DIR --yaml N [--python P]   the ripple lines for an Observatory
    kbh codex wake --project DIR --dry                 what would run, as JSON, running nothing
"""
from __future__ import annotations

import datetime as _dt
import glob
import json
import os
import shutil
import subprocess
import sys
from typing import List, Optional

from ...harness import self_command
from .common import config_path, quote_command, servers_for

HERE = os.path.dirname(os.path.abspath(__file__))
WAKE_ENV = "SEREN_KBH_WAKE"


def _native_beside(shim: str) -> Optional[str]:
    """The real codex.exe an npm shim (codex.cmd) starts through node. A
    service's PATH often has no node; the binary itself needs none."""
    base = os.path.dirname(shim)
    for pattern in (os.path.join(base, "node_modules", "@openai", "codex", "node_modules", "@openai",
                                 "codex-win32-*", "vendor", "*", "bin", "codex.exe"),
                    os.path.join(base, "node_modules", "@openai", "codex-win32-*", "vendor", "*", "bin", "codex.exe"),
                    os.path.join(base, "..", "node_modules", "@openai", "codex-win32-*", "vendor", "*", "bin",
                                 "codex.exe")):
        hits = sorted(glob.glob(pattern))
        if hits:
            return os.path.abspath(hits[-1])
    return None


def find_codex() -> Optional[str]:
    """Where `codex` is for the account this runs as: SEREN_CODEX_BIN, PATH,
    then the places the installers put it. On Windows an npm shim is followed
    to the binary it starts."""
    named = os.environ.get("SEREN_CODEX_BIN")
    if named:
        return named
    found = shutil.which("codex")
    if not found:
        homes = [os.path.expanduser("~")]
        for var in ("USERPROFILE", "HOME"):
            if os.environ.get(var) and os.environ[var] not in homes:
                homes.append(os.environ[var])
        if os.name == "nt" and os.environ.get("USERNAME"):
            homes.append(os.path.join(os.environ.get("SystemDrive", "C:") + os.sep, "Users", os.environ["USERNAME"]))
        names = ("codex.exe", "codex.cmd", "codex") if os.name == "nt" else ("codex",)
        for home in dict.fromkeys(homes):
            for folder in (os.path.join(home, ".local", "bin"),
                           os.path.join(home, "AppData", "Roaming", "npm"),
                           os.path.join(home, ".npm-global", "bin")):
                for name in names:
                    if os.path.isfile(os.path.join(folder, name)):
                        found = os.path.join(folder, name)
                        break
                if found:
                    break
            if found:
                break
    if not found:
        for candidate in ("/usr/local/bin/codex", "/opt/homebrew/bin/codex"):
            if os.path.isfile(candidate):
                found = candidate
                break
    if found and os.name == "nt" and found.lower().endswith((".cmd", ".ps1")):
        return _native_beside(found) or found
    return found


def default_framing() -> str:
    import pkgutil
    try:
        data = pkgutil.get_data(__package__, "framing.md")
    except Exception:  # noqa: BLE001
        data = None
    if data:
        return data.decode("utf-8")
    try:
        with open(os.path.join(HERE, "framing.md"), encoding="utf-8") as f:
            return f.read()
    except OSError:
        return "{message}"


def framing_text(path: Optional[str] = None) -> str:
    if path:
        with open(path, encoding="utf-8") as f:          # a named file that is missing is an error, not a fallback
            return f.read()
    return default_framing()


def frame(message: str, servers: List[str], event: str = "", when: Optional[str] = None,
          framing_path: Optional[str] = None, bookmark: str = "") -> str:
    """The message as the woken session reads it: the bookmark, then the framing."""
    text = framing_text(framing_path)
    when = when or _dt.datetime.now().astimezone().strftime("%A %d %B %Y, %H:%M %Z")
    body = (text.replace("{message}", message.strip())
                .replace("{servers}", ", ".join(servers) or "none")
                .replace("{event}", event or os.environ.get("SEREN_RIPPLE_EVENT", "") or "a wake")
                .replace("{when}", when)).strip() + "\n"
    return (bookmark.strip() + "\n\n---\n\n" + body) if bookmark.strip() else body


def command_for(codex: str, cwd: str, servers: List[str], sandbox: str = "") -> List[str]:
    cmd = [codex, "exec", "--skip-git-repo-check", "--color", "never", "-C", cwd]
    if sandbox:
        cmd += ["--sandbox", sandbox]
    for s in servers:
        # Unquoted values: Codex takes a -c value that is not TOML as a string,
        # and a quote has to survive cmd when codex is an npm .cmd shim.
        cmd += ["-c", f"mcp_servers.{s}.default_tools_approval_mode=approve",
                "-c", f"mcp_servers.{s}.required=true"]
    return cmd + ["-"]


def _arg(argv: List[str], flag: str, default: Optional[str] = None) -> Optional[str]:
    if flag in argv:
        i = argv.index(flag)
        if i + 1 < len(argv) and not argv[i + 1].startswith("--"):
            return argv[i + 1]
        return ""
    return default


def run(argv: List[str]) -> int:
    from ...config import load_for
    try:
        cfg = load_for("codex", argv)
    except OSError as e:
        print(f"cannot read the config: {e}", file=sys.stderr)
        return 1
    project = _arg(argv, "--project") or (cfg.project if cfg else "")
    if not project:
        print("usage: kbh codex wake [--config codex.yaml | --project DIR] (--run [MESSAGE] | --yaml N "
              "[--python P] | --dry)", file=sys.stderr)
        return 64
    framing_path = None
    if cfg and cfg.framing:
        framing_path = cfg.framing_path()
        if not os.path.isfile(framing_path):
            print(f"{cfg.path} names framing {cfg.framing} and there is no such file ({framing_path}); a wake "
                  f"would go out unframed. Put the file back, or clear the key to use the default.", file=sys.stderr)
            return 2
    config = _arg(argv, "--codex-config") or config_path()
    if not os.path.isdir(os.path.expanduser(project)):
        print(f"no such project folder: {project}", file=sys.stderr)
        return 2
    try:
        servers = servers_for(project, config)
    except FileNotFoundError:
        print(f"no Codex config at {config} - register the MCP server first (kbh codex register)", file=sys.stderr)
        return 2
    except Exception as e:  # noqa: BLE001 - a config.toml that does not parse
        print(f"cannot read {config}: {e}", file=sys.stderr)
        return 2
    if not servers:
        print(f"no MCP servers are enabled in {config} (or {project}/.codex/config.toml): a wake would start the "
              f"model without its memory. kbh codex register first.", file=sys.stderr)
        return 2
    cwd = os.path.abspath(os.path.expanduser(project))
    sandbox = _arg(argv, "--sandbox") or ""

    python = _arg(argv, "--python") or (cfg.python if cfg else None) or None
    where = ["--config", cfg.path] if cfg else ["--project", cwd]
    command = self_command(python) + ["codex", "wake"] + where + ["--run", "{message}"]

    if "--yaml" in argv:
        pad = " " * int(_arg(argv, "--yaml") or "2")
        print(f"{pad}command: {json.dumps(command)}")
        print(f"{pad}cwd: {json.dumps(cwd)}")
        return 0

    if "--run" in argv:
        raw = _arg(argv, "--run")
        message = raw if raw else sys.stdin.read()
        event = _arg(argv, "--event") or ""
        bookmark = ""
        if cfg and cfg.bookmark and "--no-framing" not in argv and "--no-bookmark" not in argv:
            from .bookmark import fetch
            bookmark = fetch(cfg.connection(cfg.bookmark))
        text = (message.strip() + "\n" if "--no-framing" in argv
                else frame(message, servers, event, framing_path=framing_path, bookmark=bookmark))
        codex = find_codex()
        if "--dry" in argv:
            print(json.dumps({"codex": codex, "cwd": cwd, "servers": servers,
                              "argv": command_for(codex or "codex", cwd, servers, sandbox), "stdin": text}, indent=2))
            return 0 if codex else 2
        if codex is None:
            print(f"no `codex` for this account: not on PATH ({os.environ.get('PATH', '')[:200]}), not in "
                  f"~/.local/bin or npm's folder. Set SEREN_CODEX_BIN to where it is. The model cannot be woken "
                  f"here.", file=sys.stderr)
            return 2
        env = dict(os.environ, **{WAKE_ENV: "1"})
        try:
            done = subprocess.run(command_for(codex, cwd, servers, sandbox), input=text, text=True,
                                  encoding="utf-8", cwd=cwd, env=env)
        except OSError as exc:
            print(f"`codex` at {codex} could not be started ({exc}) - the model cannot be woken here",
                  file=sys.stderr)
            return 2
        return done.returncode

    print(json.dumps({"codex": find_codex(), "cwd": cwd, "servers": servers,
                      "config": cfg.path if cfg else None, "framing": framing_path or "(package default)",
                      "command": command, "command_line": quote_command(command)}, indent=2))
    return 0
