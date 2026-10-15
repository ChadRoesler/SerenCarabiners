"""Shared bits of the Codex carabiner: where its files are, how to quote a
command for it, and the one place its config.toml is read and edited.

Codex keeps its MCP servers as TOML tables in $CODEX_HOME/config.toml
(`[mcp_servers.<name>]`), and kbh runs on Python 3.8+ with nothing installed -
so there is no TOML writer to lean on, and tomllib (3.11+) only reads. The
edit here is by whole tables: ours is found by its header, cut out with its
subtables, and the new one appended; every other line is kept as it was. A
file that does not parse (when tomllib is there to say so), or that spells
mcp_servers some other way (an inline table, dotted keys), is never touched.
"""
from __future__ import annotations

import json
import os
import re
import shlex
import shutil
from typing import Any, Dict, List, Optional

try:                                       # 3.11+: a real parser, to read and to check our edit
    import tomllib as _toml                # type: ignore[import-not-found]
except ImportError:                        # older: the headers and simple keys, by hand
    _toml = None

# A server name kbh will write: a TOML bare key, so it needs no quoting.
NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_\-]{0,63}$")
_HEADER = re.compile(r'^\s*\[\s*mcp_servers\s*\.\s*("?)([A-Za-z0-9_\-]+)\1\s*(\.[^\]]*)?\]\s*(#.*)?$')
_ANY_HEADER = re.compile(r"^\s*\[")
_OTHER_SPELLING = re.compile(r"^\s*mcp_servers\s*(=|\.)")
_KEY = re.compile(r'^\s*([A-Za-z0-9_\-]+)\s*=\s*(.+?)\s*$')


class TomlError(RuntimeError):
    """config.toml could not be changed safely; it was not touched."""


def codex_home() -> str:
    return os.environ.get("CODEX_HOME") or os.path.expanduser("~/.codex")


def config_path() -> str:
    return os.environ.get("SEREN_CODEX_CONFIG") or os.path.join(codex_home(), "config.toml")


def hooks_path() -> str:
    return os.environ.get("SEREN_CODEX_HOOKS") or os.path.join(codex_home(), "hooks.json")


def quote_command(parts: List[str]) -> str:
    """A command line Codex can run: its http_headers_helper and hook commands
    are one string, handed to `cmd /Q /D /C "<it>"` on Windows and `sh -c` elsewhere
    (codex-rs/rmcp-client/src/http_headers.rs). On Windows every part is
    double-quoted, the way cmd reads them; elsewhere shlex does it."""
    if os.name == "nt":
        return " ".join('"' + p.replace('"', '\\"') + '"' for p in parts)
    return shlex.join(parts)


def toml_string(s: str) -> str:
    """A TOML basic string. JSON's escapes are TOML's (\\" \\\\ \\uXXXX)."""
    return json.dumps(s, ensure_ascii=True)


# ── reading ──────────────────────────────────────────────────────────────

def _read(path: str) -> str:
    path = os.path.expanduser(path)
    if not os.path.exists(path):
        return ""
    with open(path, encoding="utf-8") as f:
        return f.read()


def _scalar(raw: str) -> Any:
    raw = raw.split(" #", 1)[0].strip()
    if raw in ("true", "false"):
        return raw == "true"
    if raw.startswith('"') and raw.endswith('"'):
        try:
            return json.loads(raw)
        except ValueError:
            return raw[1:-1]
    if raw.startswith("'") and raw.endswith("'"):
        return raw[1:-1]
    for kind in (int, float):
        try:
            return kind(raw.replace("_", ""))
        except ValueError:
            pass
    return raw


def parse_servers(text: str) -> Dict[str, Dict[str, Any]]:
    """{name: {key: value}} for every [mcp_servers.<name>] in a config.toml."""
    if _toml is not None:
        try:
            data = _toml.loads(text)
        except Exception as e:  # noqa: BLE001
            raise TomlError(f"not valid TOML ({e})")
        servers = data.get("mcp_servers") or {}
        return {str(k): dict(v) for k, v in servers.items() if isinstance(v, dict)}
    out: Dict[str, Dict[str, Any]] = {}
    current: Optional[Dict[str, Any]] = None
    for line in text.splitlines():
        m = _HEADER.match(line)
        if m:
            current = out.setdefault(m.group(2), {}) if not m.group(3) else None
            continue
        if _ANY_HEADER.match(line):
            current = None
            continue
        if current is not None:
            k = _KEY.match(line)
            if k:
                current[k.group(1)] = _scalar(k.group(2))
    return out


def servers_in(path: str) -> Dict[str, Dict[str, Any]]:
    """The servers a config.toml declares (enabled = false ones included).
    Raises FileNotFoundError when there is no file."""
    if not os.path.exists(os.path.expanduser(path)):
        raise FileNotFoundError(path)
    return parse_servers(_read(path))


def servers_for(project: str, config: Optional[str] = None) -> List[str]:
    """Every ENABLED server a session in `project` gets: the user config's,
    and the project's own .codex/config.toml (Codex loads that layer only when
    the project is trusted; it is listed here either way, since a wake asks for
    it by name). Raises FileNotFoundError when neither file exists."""
    found: Dict[str, Dict[str, Any]] = {}
    seen = False
    for path in (config or config_path(),
                 os.path.join(os.path.expanduser(project), ".codex", "config.toml")):
        if os.path.exists(path):
            seen = True
            found.update(servers_in(path))
    if not seen:
        raise FileNotFoundError(config or config_path())
    return sorted(n for n, e in found.items() if e.get("enabled", True) is not False)


# ── editing ──────────────────────────────────────────────────────────────

def _check(text: str, path: str) -> None:
    if _toml is not None:
        try:
            _toml.loads(text)
        except Exception as e:  # noqa: BLE001
            raise TomlError(f"{path} is not valid TOML ({e}); not touching it. Fix it, then run again.")
    for line in text.splitlines():
        if _OTHER_SPELLING.match(line):
            raise TomlError(f"{path} spells mcp_servers as an inline table or dotted keys ({line.strip()[:60]}); "
                            f"kbh edits [mcp_servers.<name>] tables only, so it is not touching it. "
                            f"Move that to tables, or add the entry by hand.")


def _without(lines: List[str], name: str) -> List[str]:
    """The lines with [mcp_servers.<name>] and its subtables cut out."""
    out: List[str] = []
    skipping = False
    for line in lines:
        m = _HEADER.match(line)
        if m:
            skipping = m.group(2) == name
            if skipping:
                while out and out[-1].strip().startswith("# written by kbh codex"):
                    out.pop()                                  # our note above the table goes with it
                continue
        elif _ANY_HEADER.match(line):
            skipping = False
        if not skipping:
            out.append(line)
    while out and not out[-1].strip():
        out.pop()
    return out


def set_server(path: str, name: str, keys: Optional[Dict[str, Any]], note: str = "") -> str:
    """Write [mcp_servers.<name>] with `keys` (strings, numbers, bools), or
    remove it with keys=None. Keeps every other line; backs the file up as
    config.toml.seren-bak; writes atomically. Returns what it did."""
    if not NAME.match(name):
        raise TomlError(f"'{name}' is not a server name kbh writes (letters, digits, - and _)")
    path = os.path.expanduser(path)
    text = _read(path)
    _check(text, path)
    newline = "\r\n" if "\r\n" in text else "\n"
    old = text.replace("\r\n", "\n").split("\n") if text else []
    had = any((m := _HEADER.match(l)) and m.group(2) == name for l in old)
    lines = _without(old, name)
    if keys is not None:
        block = [f"# written by kbh codex register{': ' + note if note else ''}", f"[mcp_servers.{name}]"]
        for k, v in keys.items():
            if isinstance(v, bool):
                block.append(f"{k} = {'true' if v else 'false'}")
            elif isinstance(v, (int, float)):
                block.append(f"{k} = {v}")
            else:
                block.append(f"{k} = {toml_string(str(v))}")
        lines = lines + ([""] if lines else []) + block
    new = newline.join(lines) + newline if lines else ""
    _check(new, path)                                          # our own edit must parse too
    if _toml is not None and keys is not None and name not in parse_servers(new):
        raise TomlError(f"the edit would not declare {name}; not writing it")
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    if os.path.exists(path):
        shutil.copy2(path, path + ".seren-bak")
    tmp = path + ".seren-tmp"
    with open(tmp, "w", encoding="utf-8", newline="") as f:
        f.write(new)
    os.replace(tmp, path)
    if keys is None:
        return f"removed {name} from {path}" if had else f"{name} was not in {path}"
    return f"wrote [mcp_servers.{name}] in {path}"
