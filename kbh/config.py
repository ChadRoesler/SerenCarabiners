"""
kbh.config - how a carabiner rolls on THIS box.

The .kbh is code and is the same everywhere. What differs per install lives
in one yaml beside it, named for the harness - claude.yaml - and is read by
every verb:

    # claude.yaml - how the Claude Code carabiner rolls on this box
    carabiner: claude
    project: D:\\serenDaemon\\SerenCore          # where wakes run (the model's working folder)
    python: C:\\...\\venvs\\observatory\\Scripts\\python.exe   # runs the .kbh from hooks and ripples
    connections: C:\\Users\\alice\\seren\\wren\\nuc    # the folder of connection files (kbh.tokens)
    servers:                                   # what register registers: name -> connection file
      wren-workbench: workbench.yaml
    bookmark: margin.yaml                      # Margin's connection file; blank = no bookmark hook
    framing: framing.md                        # the text a woken session is given; beside this yaml
    wake:
      timeout_seconds: 900

FRAMING IS NOT IN THE CARABINER. It is prose a person (or the model) edits,
so it is a file the yaml points at; the package carries a default only as
the fallback when the yaml names none. Relative paths are relative to the
yaml's folder, so the whole thing moves as one folder.

Where the yaml is looked for, in order: --config PATH; KBH_CONFIG; <the
.kbh's own folder>/<carabiner>.yaml; ~/.seren/kbh/<carabiner>.yaml.
Read with PyYAML when it is there, else by hand (two levels of
`key: value`, which is all this file has).
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from typing import Any, Dict, Optional


def read_yaml(path: str) -> Dict[str, Any]:
    text = open(path, encoding="utf-8").read()
    try:
        import yaml  # type: ignore
        data = yaml.safe_load(text)
        return data if isinstance(data, dict) else {}
    except ImportError:
        return _two_levels_by_hand(text)


def _scalar(value: str) -> Any:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    low = value.lower()
    if low in ("true", "yes", "on"):
        return True
    if low in ("false", "no", "off"):
        return False
    if low in ("", "~", "null"):
        return ""
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        return value


def _two_levels_by_hand(text: str) -> Dict[str, Any]:
    """`key: value` at the top, and `key:` blocks of `  key: value`. Comments
    and blank lines dropped; a `#` inside quotes is kept."""
    out: Dict[str, Any] = {}
    block: Optional[str] = None
    for raw in text.splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        line = raw.rstrip()
        if " #" in line and not (line.count('"') % 2 or line.count("'") % 2):
            line = line.split(" #", 1)[0].rstrip()
        indented = line.startswith((" ", "\t"))
        key, sep, value = line.strip().partition(":")
        if not sep:
            continue
        if not indented:
            if value.strip():
                out[key.strip()] = _scalar(value)
                block = None
            else:
                block = key.strip()
                out[block] = {}
        elif block is not None and isinstance(out.get(block), dict):
            out[block][key.strip()] = _scalar(value)
    return out


@dataclass
class HarnessConfig:
    carabiner: str = ""
    project: str = ""
    python: str = ""
    connections: str = ""
    servers: Dict[str, str] = field(default_factory=dict)      # name -> connection file (relative to `connections`)
    bookmark: str = ""                                          # connection file for Margin, or ""
    framing: str = ""                                           # path to the framing text, or "" = the package default
    wake: Dict[str, Any] = field(default_factory=dict)
    path: str = ""                                              # the yaml this came from
    extra: Dict[str, Any] = field(default_factory=dict)         # keys this binder does not know; a carabiner may

    @property
    def folder(self) -> str:
        return os.path.dirname(os.path.abspath(self.path)) if self.path else os.getcwd()

    def resolve(self, p: str, base: Optional[str] = None) -> str:
        """A path from the yaml: absolute as given, relative to the yaml's
        folder (or `base`)."""
        p = os.path.expanduser(str(p or ""))
        if not p:
            return ""
        return p if os.path.isabs(p) else os.path.normpath(os.path.join(base or self.folder, p))

    def connection(self, name_or_file: str) -> str:
        """The connection file for a server name from `servers:`, or a file
        name under `connections:`, or a path."""
        target = self.servers.get(name_or_file, name_or_file)
        base = self.resolve(self.connections) if self.connections else self.folder
        return self.resolve(target, base)

    def framing_path(self) -> str:
        return self.resolve(self.framing) if self.framing else ""

    def wake_timeout(self) -> float:
        try:
            return float(self.wake.get("timeout_seconds", 900))
        except (TypeError, ValueError):
            return 900.0


def load(path: str) -> HarnessConfig:
    path = os.path.abspath(os.path.expanduser(path))
    data = read_yaml(path)                                       # OSError if missing, on purpose
    known = {"carabiner", "project", "python", "connections", "servers", "bookmark", "framing", "wake"}
    servers = data.get("servers") if isinstance(data.get("servers"), dict) else {}
    return HarnessConfig(carabiner=str(data.get("carabiner") or ""), project=str(data.get("project") or ""),
                         python=str(data.get("python") or ""), connections=str(data.get("connections") or ""),
                         servers={str(k): str(v) for k, v in servers.items()},
                         bookmark=str(data.get("bookmark") or ""), framing=str(data.get("framing") or ""),
                         wake=dict(data.get("wake") or {}) if isinstance(data.get("wake"), dict) else {},
                         path=path, extra={k: v for k, v in data.items() if k not in known})


def find(carabiner: str, explicit: Optional[str] = None) -> Optional[str]:
    """Where this carabiner's yaml is, or None."""
    if explicit:
        return os.path.abspath(os.path.expanduser(explicit))
    env = os.environ.get("KBH_CONFIG")
    if env:
        return os.path.abspath(os.path.expanduser(env))
    from .harness import self_command
    cmd = self_command()
    candidates = []
    if len(cmd) == 2 and os.path.isfile(cmd[1]):                 # a .kbh: beside it
        candidates.append(os.path.join(os.path.dirname(cmd[1]), f"{carabiner}.yaml"))
    candidates.append(os.path.join(os.path.expanduser("~"), ".seren", "kbh", f"{carabiner}.yaml"))
    for c in candidates:
        if os.path.isfile(c):
            return c
    return None


def load_for(carabiner: str, argv: list) -> Optional[HarnessConfig]:
    """The config a verb should use: --config PATH, else the found one, else
    None (the verb then needs its flags)."""
    explicit = argv[argv.index("--config") + 1] if "--config" in argv and argv.index("--config") + 1 < len(argv) else None
    path = find(carabiner, explicit)
    if path is None:
        return None
    return load(path)


STARTER = """# {carabiner}.yaml - how the {display} carabiner rolls on this box.
# Read by every verb (kbh {carabiner} <verb> --config this-file, or found beside the .kbh).
# Relative paths are relative to this file's folder.
carabiner: {carabiner}
project: {project}
python: {python}
connections: {connections}
servers:
{servers}bookmark: {bookmark}
framing: framing.md
wake:
  timeout_seconds: 900
"""


def write_starter(carabiner: str, display: str, into: str, project: str, python: str, connections: str,
                  servers: Dict[str, str], bookmark: str, default_framing: str,
                  template: Optional[str] = None) -> Dict[str, str]:
    """Write <into>/<carabiner>.yaml (from the carabiner's config.yaml
    template, else STARTER) and <into>/framing.md (from the package default,
    only if none is there yet). Never overwrites a yaml."""
    into = os.path.abspath(os.path.expanduser(into))
    os.makedirs(into, exist_ok=True)
    yaml_path = os.path.join(into, f"{carabiner}.yaml")
    if os.path.exists(yaml_path):
        raise FileExistsError(f"{yaml_path} already exists; edit it, or move it aside")
    lines = "".join(f"  {k}: {v}\n" for k, v in servers.items()) if servers else "  # wren-workbench: workbench.yaml\n"
    text = (template or STARTER).format(carabiner=carabiner, display=display, project=project or ".",
                                        python=python or sys.executable, connections=connections or ".",
                                        servers=lines.rstrip("\n"), bookmark=bookmark or '""')
    with open(yaml_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    framing_path = os.path.join(into, "framing.md")
    wrote_framing = False
    if not os.path.exists(framing_path):
        with open(framing_path, "w", encoding="utf-8", newline="\n") as f:
            f.write(default_framing)
        wrote_framing = True
    return {"yaml": yaml_path, "framing": framing_path, "framing_written": "yes" if wrote_framing else "kept"}
