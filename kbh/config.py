"""
kbh.config - how a carabiner rolls on THIS box.

The .kbh is code and is the same everywhere. What differs per install lives
in one yaml beside it, named for the harness - claude.yaml - and is read by
every verb:

    # claude.yaml - how the Claude Code carabiner rolls on this box
    carabiner: claude
    project: D:\\work\\project          # where wakes run (the model's working folder)
    python: C:\\...\\venvs\\observatory\\Scripts\\python.exe   # runs the .kbh from hooks and ripples
    connections: C:\\Users\\alice\\seren\\brain\\routes    # the folder of connection files (kbh.tokens)
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

import json
import os
import re
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
    """`key: value` at the top, `key:` blocks of `  key: value`, and one level
    more for an inline route (`servers:` / `  name:` / `    url: ...`).
    Comments and blank lines dropped; a `#` inside quotes is kept."""
    out: Dict[str, Any] = {}
    block: Optional[str] = None
    sub: Optional[str] = None
    for raw in text.splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        line = raw.rstrip()
        if " #" in line and not (line.count('"') % 2 or line.count("'") % 2):
            line = line.split(" #", 1)[0].rstrip()
        indent = len(line) - len(line.lstrip(" \t"))
        key, sep, value = line.strip().partition(":")
        if not sep:
            continue
        key = key.strip()
        if indent == 0:
            sub = None
            if value.strip():
                out[key] = _scalar(value)
                block = None
            else:
                block = key
                out[block] = {}
        elif block is not None and isinstance(out.get(block), dict):
            if indent >= 4 and sub is not None and isinstance(out[block].get(sub), dict):
                out[block][sub][key] = _scalar(value)
            elif value.strip():
                out[block][key] = _scalar(value)
                sub = None
            else:
                sub = key
                out[block][sub] = {}
    return out


@dataclass
class HarnessConfig:
    carabiner: str = ""
    project: str = ""
    python: str = ""
    connections: str = ""
    # name -> a connection file (relative to `connections`), or an inline ROUTE
    # {url | host+port, bearer_token | _env | _keyring}: the url and the token
    # dropped straight into this yaml, nothing copied from the brain box.
    servers: Dict[str, Any] = field(default_factory=dict)
    bookmark: Any = ""                                          # Margin: a connection file, an inline route, or ""
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

    def connection(self, name_or_file: Any) -> str:
        """A connection REFERENCE for a server name from `servers:` (a file
        path, or `<this yaml>#<name>` when the route is inline), for the
        bookmark (pass the bookmark value, or "bookmark"), or a file name
        under `connections:`, or a path. What kbh.tokens.read_connection
        takes, and what the harness's helper and hooks are handed."""
        if isinstance(name_or_file, dict):                    # the bookmark route itself
            return f"{self.path}#bookmark"
        name = str(name_or_file)
        if name == "bookmark":
            return self.connection(self.bookmark) if self.bookmark else ""
        target = self.servers.get(name, name)
        if isinstance(target, dict):
            return f"{self.path}#{name}"
        base = self.resolve(self.connections) if self.connections else self.folder
        return self.resolve(str(target), base)

    def routes(self) -> Dict[str, str]:
        """Every server by name -> its connection reference."""
        return {name: self.connection(name) for name in self.servers}

    def has_inline_token(self) -> bool:
        items = list(self.servers.values()) + ([self.bookmark] if isinstance(self.bookmark, dict) else [])
        return any(isinstance(r, dict) and r.get("bearer_token") for r in items)

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
    bookmark = data.get("bookmark")
    return HarnessConfig(carabiner=str(data.get("carabiner") or ""), project=str(data.get("project") or ""),
                         python=str(data.get("python") or ""), connections=str(data.get("connections") or ""),
                         servers={str(k): (dict(v) if isinstance(v, dict) else str(v)) for k, v in servers.items()},
                         bookmark=dict(bookmark) if isinstance(bookmark, dict) else str(bookmark or ""),
                         framing=str(data.get("framing") or ""),
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


def _yaml_scalar(v: Any) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    s = str(v)
    return s if re.fullmatch(r"[A-Za-z0-9_./:\\-]+", s) else json.dumps(s)


def _yaml_entry(name: str, value: Any, indent: int) -> str:
    """One `servers:` entry: a file name, or an inline route block."""
    pad = " " * indent
    if isinstance(value, dict):
        return f"{pad}{name}:\n" + "".join(f"{pad}  {k}: {_yaml_scalar(v)}\n" for k, v in value.items())
    return f"{pad}{name}: {_yaml_scalar(value)}\n"


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
    lines = "".join(_yaml_entry(k, v, 2) for k, v in servers.items()) if servers else "  # wren-workbench: workbench.yaml\n"
    if isinstance(bookmark, dict):
        bookmark_text = "\n" + "".join(f"  {k}: {_yaml_scalar(v)}\n" for k, v in bookmark.items()).rstrip("\n")
    else:
        bookmark_text = _yaml_scalar(bookmark) if bookmark else '""'
    text = (template or STARTER).format(carabiner=carabiner, display=display, project=project or ".",
                                        python=python or sys.executable, connections=connections or ".",
                                        servers=lines.rstrip("\n"), bookmark=bookmark_text)
    with open(yaml_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    # An inline token makes this file a secret; a bare route or a pointer does not.
    inline = any(isinstance(v, dict) and v.get("bearer_token") for v in servers.values()) \
        or (isinstance(bookmark, dict) and bool(bookmark.get("bearer_token")))
    if inline:
        try:
            os.chmod(yaml_path, 0o600)
        except OSError:
            pass
    framing_path = os.path.join(into, "framing.md")
    wrote_framing = False
    if not os.path.exists(framing_path):
        with open(framing_path, "w", encoding="utf-8", newline="\n") as f:
            f.write(default_framing)
        wrote_framing = True
    return {"yaml": yaml_path, "framing": framing_path, "framing_written": "yes" if wrote_framing else "kept"}
