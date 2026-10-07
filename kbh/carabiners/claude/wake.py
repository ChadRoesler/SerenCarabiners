"""
wake - start a headless Claude Code session with a message, framed.

Lifted from Starwright's seren-claude-ripple.py (28 Sept - 7 Oct 2026). The
two decisions it carries:

THE SERVER LIST IS READ WHEN THE MODEL IS WOKEN, NOT WHEN IT WAS INSTALLED.
The Observatory's ripple command used to carry the five server names found on
install day; then the model's servers became one Workbench and the next wake
pre-approved five servers that were gone. So the command the Observatory holds
is this verb, and this verb does the lookup at that moment:

    command: [<python>, <this .kbh>, "claude", "wake", "--project", <dir>, "--run", "{message}"]

THE BINARY IS FOUND FOR THE ACCOUNT, NOT TRUSTED TO PATH. A service that wakes
the model (the Observatory, as run_as) hands it the SERVICE's PATH. The first
wake over the cluster (7 Oct 2026) refused with "no claude on PATH" while claude
sat in ~/.local/bin. SEREN_CLAUDE_BIN names it outright and wins.

FRAMING. The caller owns the message (the Hippocampus knows what a draft is);
this carabiner owns how a woken Claude Code session is told who it is, where
its memory is and when to stop - framing.md beside this file, with {message},
{servers}, {event}, {when} filled in. --no-framing sends the message bare.

    kbh claude wake --project DIR --run [MESSAGE]      (MESSAGE or stdin)
    kbh claude wake --project DIR --yaml N [--python P]   the ripple lines for an Observatory
    kbh claude wake --project DIR --dry                 what would run, as JSON, running nothing
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
from .common import claude_json_path, quote_command, servers_for

HERE = os.path.dirname(os.path.abspath(__file__))


def find_claude() -> Optional[str]:
    """Where `claude` is for the account this runs as: PATH, then the places
    the installers put it. SEREN_CLAUDE_BIN wins."""
    named = os.environ.get("SEREN_CLAUDE_BIN")
    if named:
        return named
    found = shutil.which("claude")
    if found:
        return found
    homes = [os.path.expanduser("~")]
    for var in ("USERPROFILE", "HOME"):
        if os.environ.get(var) and os.environ[var] not in homes:
            homes.append(os.environ[var])
    if os.name == "nt" and os.environ.get("USERNAME"):
        homes.append(os.path.join(os.environ.get("SystemDrive", "C:") + os.sep, "Users", os.environ["USERNAME"]))
    names = ("claude.exe", "claude.cmd", "claude") if os.name == "nt" else ("claude",)
    for home in dict.fromkeys(homes):
        for folder in (os.path.join(home, ".local", "bin"),                     # the native installer
                       os.path.join(home, ".claude", "local"),                  # claude's own local install
                       os.path.join(home, "AppData", "Roaming", "npm"),         # npm -g on Windows
                       os.path.join(home, ".npm-global", "bin")):               # npm -g with a user prefix
            for name in names:
                candidate = os.path.join(folder, name)
                if os.path.isfile(candidate):
                    return candidate
    for candidate in ("/usr/local/bin/claude", "/opt/homebrew/bin/claude"):
        if os.path.isfile(candidate):
            return candidate
    return None


def default_framing() -> str:
    """The package's framing.md - the fallback when the config names none.
    Read through pkgutil so it is found inside a .kbh zip as well as on disk."""
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
    """The framing in use: the file the config points at (claude.yaml:
    framing), else the package default. The framing is prose a person edits,
    so it lives beside the config, not in the carabiner."""
    if path:
        with open(path, encoding="utf-8") as f:          # a named file that is missing is an error, not a fallback
            return f.read()
    return default_framing()


def frame(message: str, servers: List[str], event: str = "", when: Optional[str] = None,
          framing_path: Optional[str] = None) -> str:
    """The message as the woken session reads it."""
    text = framing_text(framing_path)
    when = when or _dt.datetime.now().astimezone().strftime("%A %d %B %Y, %H:%M %Z")
    return (text.replace("{message}", message.strip())
                .replace("{servers}", ", ".join(servers) or "none")
                .replace("{event}", event or os.environ.get("SEREN_RIPPLE_EVENT", "") or "a wake")
                .replace("{when}", when)).strip() + "\n"


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
        cfg = load_for("claude", argv)
    except OSError as e:
        print(f"cannot read the config: {e}", file=sys.stderr)
        return 1
    project = _arg(argv, "--project") or (cfg.project if cfg else "")
    if not project:
        print("usage: kbh claude wake [--config claude.yaml | --project DIR] (--run [MESSAGE] | --yaml N "
              "[--python P] | --dry)", file=sys.stderr)
        return 64
    framing_path = None
    if cfg and cfg.framing:
        framing_path = cfg.framing_path()
        if not os.path.isfile(framing_path):
            print(f"{cfg.path} names framing {cfg.framing} and there is no such file ({framing_path}); a wake "
                  f"would go out unframed. Put the file back, or clear the key to use the default.", file=sys.stderr)
            return 2
    claude_json = _arg(argv, "--claude-json") or claude_json_path()
    if not os.path.isdir(os.path.expanduser(project)):
        print(f"no such project folder: {project}", file=sys.stderr)
        return 2
    try:
        servers = servers_for(project, claude_json)
    except FileNotFoundError:
        print(f"no Claude Code settings at {claude_json} - run claude once in {project} and register the MCP "
              f"server there first (kbh claude register)", file=sys.stderr)
        return 2
    if not servers:
        print(f"no MCP servers are registered for {project} in {claude_json} (or its .mcp.json): a wake would "
              f"start the model without its memory. kbh claude register first.", file=sys.stderr)
        return 2
    cwd = os.path.abspath(os.path.expanduser(project))
    allowed = ",".join(f"mcp__{s}" for s in servers)

    # The command a hook or an Observatory holds. With a config, it names the
    # config and nothing else: project, framing and python all come from there
    # at wake time, so changing the yaml changes the next wake.
    python = _arg(argv, "--python") or (cfg.python if cfg else None) or None
    where = ["--config", cfg.path] if cfg else ["--project", cwd]
    command = self_command(python) + ["claude", "wake"] + where + ["--run", "{message}"]

    if "--yaml" in argv:
        pad = " " * int(_arg(argv, "--yaml") or "2")
        print(f"{pad}command: {json.dumps(command)}")
        print(f"{pad}cwd: {json.dumps(cwd)}")
        return 0

    if "--run" in argv:
        raw = _arg(argv, "--run")
        message = raw if raw else sys.stdin.read()
        event = _arg(argv, "--event") or ""
        text = message.strip() + "\n" if "--no-framing" in argv else frame(message, servers, event, framing_path=framing_path)
        claude = find_claude()
        if "--dry" in argv:
            print(json.dumps({"claude": claude, "cwd": cwd, "allowed": allowed, "servers": servers,
                              "stdin": text}, indent=2))
            return 0 if claude else 2
        if claude is None:
            print(f"no `claude` for this account: not on PATH ({os.environ.get('PATH', '')[:200]}), not in "
                  f"~/.local/bin, ~/.claude/local or npm's folder. Set SEREN_CLAUDE_BIN to where it is. "
                  f"The model cannot be woken here.", file=sys.stderr)
            return 2
        try:
            done = subprocess.run([claude, "-p", "--allowedTools", allowed], input=text, text=True,
                                  encoding="utf-8", cwd=cwd)
        except OSError as exc:
            print(f"`claude` at {claude} could not be started ({exc}) - the model cannot be woken here",
                  file=sys.stderr)
            return 2
        return done.returncode

    print(json.dumps({"claude": find_claude(), "cwd": cwd, "servers": servers, "allowed": allowed,
                      "config": cfg.path if cfg else None, "framing": framing_path or "(package default)",
                      "command": command, "command_line": quote_command(command)}, indent=2))
    return 0
