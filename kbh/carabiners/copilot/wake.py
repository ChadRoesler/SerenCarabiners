"""
wake - start a headless GitHub Copilot CLI session with a message, framed.

    copilot -p <the framed message> --allow-tool <server> [--allow-tool <server> ...] [--model M]

run in the project folder. `--allow-tool <server>` with a server's bare name
allows every tool of that server and nothing else, which is what a wake with
nobody in the room needs; only the servers the yaml lists are allowed
(kbh.config.wake_servers), read from mcp-config.json at that moment.

BUILT FROM THE DOCS, NOT YET RUN AGAINST THE BINARY (10 Nov 2026: no Copilot
CLI on the box this was written on). What the docs state and this relies on:
`-p` / `--prompt`, `--allow-tool='<server>'`, `--model`. What they do not
state, so this does not use: a prompt on stdin, a working-directory flag.

ONLY THE CLI CAN BE WOKEN. Copilot inside VS Code or Visual Studio has no
headless start; a box with the editor and no `copilot` binary takes `register`
and has no wake, and says so.

THE MESSAGE IS ONE ARGUMENT, so it must reach the binary whole. An npm install
on Windows is a `copilot.cmd` shim, and cmd.exe cuts an argument at its first
newline and reads `&` and `|` in it as its own: a framed message would arrive
as its first line and the rest would be run. That is refused (exit 2) rather
than tried; install the CLI with winget (a real .exe), or name the .exe with
SEREN_COPILOT_BIN.

    kbh copilot wake --project DIR --run [MESSAGE]     (MESSAGE or stdin)
    kbh copilot wake --project DIR --yaml N            the ripple lines for a Hippocampus or an Observatory
    kbh copilot wake --project DIR --dry               what would run, as JSON, running nothing
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import shutil
import subprocess
import sys
from typing import List, Optional

from ...harness import self_command
from ...settings import SettingsError
from .common import mcp_config_path, servers_in

WAKE_ENV = "SEREN_KBH_WAKE"


def find_copilot() -> Optional[str]:
    """Where `copilot` is for the account this runs as. SEREN_COPILOT_BIN wins."""
    named = os.environ.get("SEREN_COPILOT_BIN")
    if named:
        return named
    found = shutil.which("copilot")
    if found:
        return found
    homes = [os.path.expanduser("~")]
    for var in ("USERPROFILE", "HOME"):
        if os.environ.get(var) and os.environ[var] not in homes:
            homes.append(os.environ[var])
    names = ("copilot.exe", "copilot.cmd", "copilot") if os.name == "nt" else ("copilot",)
    for home in dict.fromkeys(homes):
        for folder in (os.path.join(home, ".local", "bin"),                              # the install script
                       os.path.join(home, "AppData", "Local", "Microsoft", "WinGet", "Links"),   # winget
                       os.path.join(home, "AppData", "Roaming", "npm"),                  # npm -g on Windows
                       os.path.join(home, ".npm-global", "bin")):                        # npm -g with a user prefix
            for name in names:
                candidate = os.path.join(folder, name)
                if os.path.isfile(candidate):
                    return candidate
    for candidate in ("/usr/local/bin/copilot", "/opt/homebrew/bin/copilot"):
        if os.path.isfile(candidate):
            return candidate
    return None


def is_shim(binary: str) -> bool:
    """A .cmd/.bat on Windows: run through cmd.exe, which cannot carry the message."""
    return os.name == "nt" and binary.lower().endswith((".cmd", ".bat"))


def default_framing() -> str:
    import pkgutil
    try:
        data = pkgutil.get_data(__package__, "framing.md")
    except Exception:  # noqa: BLE001
        data = None
    return data.decode("utf-8") if data else "{message}"


def frame(message: str, servers: List[str], event: str = "", when: Optional[str] = None,
          framing_path: Optional[str] = None) -> str:
    """The message as the woken session reads it."""
    if framing_path:
        with open(framing_path, encoding="utf-8") as f:       # a named file that is missing is an error, not a fallback
            text = f.read()
    else:
        text = default_framing()
    when = when or _dt.datetime.now().astimezone().strftime("%A %d %B %Y, %H:%M %Z")
    return (text.replace("{message}", message.strip())
                .replace("{servers}", ", ".join(servers) or "none")
                .replace("{event}", event or os.environ.get("SEREN_RIPPLE_EVENT", "") or "a wake")
                .replace("{when}", when)).strip() + "\n"


def command_for(copilot: str, text: str, servers: List[str], model: str = "") -> List[str]:
    cmd = [copilot, "-p", text]
    for s in servers:
        cmd += ["--allow-tool", s]
    if model:
        cmd += ["--model", model]
    return cmd


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
        cfg = load_for("copilot", argv)
    except OSError as e:
        print(f"cannot read the config: {e}", file=sys.stderr)
        return 1
    project = _arg(argv, "--project") or (cfg.project if cfg else "")
    if not project:
        print("usage: kbh copilot wake [--config copilot.yaml | --project DIR] (--run [MESSAGE] | --yaml N | --dry)",
              file=sys.stderr)
        return 64
    framing_path = None
    if cfg and cfg.framing:
        framing_path = cfg.framing_path()
        if not os.path.isfile(framing_path):
            print(f"{cfg.path} names framing {cfg.framing} and there is no such file ({framing_path}); a wake "
                  f"would go out unframed. Put the file back, or clear the key to use the default.", file=sys.stderr)
            return 2
    if not os.path.isdir(os.path.expanduser(project)):
        print(f"no such project folder: {project}", file=sys.stderr)
        return 2
    config = mcp_config_path()
    try:
        servers = sorted(servers_in(config))
    except SettingsError as e:
        print(str(e), file=sys.stderr)
        return 2
    if not servers:
        print(f"no MCP servers in {config}: a wake would start the model without its memory. "
              f"kbh copilot register first.", file=sys.stderr)
        return 2
    if cfg and cfg.servers:
        registered, servers = servers, cfg.wake_servers(servers)
        if not servers:
            print(f"{cfg.path} lists {', '.join(cfg.servers)} under `servers:` and none of them is registered "
                  f"({', '.join(registered)} {'is' if len(registered) == 1 else 'are'}): a wake approves only the "
                  f"servers the yaml names. kbh copilot register apply.", file=sys.stderr)
            return 2
    cwd = os.path.abspath(os.path.expanduser(project))
    model = str((cfg.session.get("model") if cfg else "") or "")
    python = _arg(argv, "--python") or (cfg.python if cfg else None) or None
    where = ["--config", cfg.path] if cfg else ["--project", cwd]
    command = self_command(python) + ["copilot", "wake"] + where + ["--run", "{message}"]

    if "--yaml" in argv:
        pad = " " * int(_arg(argv, "--yaml") or "2")
        print(f"{pad}command: {json.dumps(command)}")
        print(f"{pad}cwd: {json.dumps(cwd)}")
        return 0

    copilot = find_copilot()
    if "--run" in argv:
        raw = _arg(argv, "--run")
        message = raw if raw else sys.stdin.read()
        text = (message.strip() + "\n" if "--no-framing" in argv
                else frame(message, servers, _arg(argv, "--event") or "", framing_path=framing_path))
        if "--dry" in argv:
            print(json.dumps({"copilot": copilot, "cwd": cwd, "servers": servers, "model": model or None,
                              "argv": command_for(copilot or "copilot", text, servers, model),
                              "shim": bool(copilot and is_shim(copilot))}, indent=2))
            return 0 if copilot and not is_shim(copilot) else 2
        if copilot is None:
            print("no `copilot` for this account: not on PATH, not in ~/.local/bin, winget's links or npm's folder. "
                  "Set SEREN_COPILOT_BIN to where it is. Copilot in an editor cannot be woken; only the CLI can.",
                  file=sys.stderr)
            return 2
        if is_shim(copilot):
            print(f"{copilot} is a .cmd shim: cmd.exe would cut the message at its first line and run the rest. "
                  f"Install the Copilot CLI with winget (a real .exe), or set SEREN_COPILOT_BIN to the .exe.",
                  file=sys.stderr)
            return 2
        env = dict(os.environ, **{WAKE_ENV: "1"})
        timeout = cfg.wake_timeout() if cfg else None
        try:
            done = subprocess.run(command_for(copilot, text, servers, model), stdin=subprocess.DEVNULL, cwd=cwd,
                                  env=env, timeout=timeout)
        except subprocess.TimeoutExpired:
            print(f"the wake ran past {timeout:g}s (wake.timeout_seconds) and was stopped", file=sys.stderr)
            return 1
        except OSError as exc:
            print(f"`copilot` at {copilot} could not be started ({exc}) - the model cannot be woken here",
                  file=sys.stderr)
            return 2
        return done.returncode

    print(json.dumps({"copilot": copilot, "cwd": cwd, "servers": servers, "config": cfg.path if cfg else None,
                      "framing": framing_path or "(package default)", "command": command}, indent=2))
    return 0
