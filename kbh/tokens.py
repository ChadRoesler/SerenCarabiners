"""
kbh.tokens - connection files, and the token they point at.

A CONNECTION FILE says where one Seren service is and how to present its
bearer. It is the `server:` block of that service's own config, and nothing
else - which is why a service's full config works as one too:

    server:
      host: nuc
      port: 7255
      bearer_token: "..."              # or bearer_token_env / bearer_token_keyring

WHY FILES. The harness is rarely on the brain's box. Claude Code on the desktop
has to present the NUC's Workbench its token; Claude Code keeps an MCP server's
headers in ~/.claude.json, and the only command-line way to put one there is a
token on the command line, which this family never does. So the registration
holds a headersHelper instead - `kbh <carabiner> headers <connection file>` -
and the token is read from the file when the harness connects. The first
cutover (6 Oct 2026) made these files by hand, by scp-ing every NUC yaml and
cutting it to its server block; `register` writes them.

Token precedence is seren_meninges's: inline, then keyring, then env var.
seren_meninges is used when importable; otherwise the same rules, here.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Any, Dict, Optional

LOOPBACK = ("", "0.0.0.0", "::", None)


@dataclass
class Connection:
    host: str = "127.0.0.1"
    port: int = 0
    bearer_token: str = ""
    bearer_token_env: str = ""
    bearer_token_keyring: str = ""
    path: str = ""                       # the file it came from

    @property
    def base_url(self) -> str:
        host = self.host if self.host not in LOOPBACK else "127.0.0.1"
        return f"http://{host}:{self.port}"

    @property
    def mcp_url(self) -> str:
        return self.base_url + "/mcp"

    def has_token_pointer(self) -> bool:
        return bool(self.bearer_token or self.bearer_token_env or self.bearer_token_keyring)

    def resolve_token(self) -> str:
        return resolve_token(self.bearer_token, self.bearer_token_keyring, self.bearer_token_env)

    def to_server_block(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {"host": self.host, "port": self.port}
        for k in ("bearer_token", "bearer_token_env", "bearer_token_keyring"):
            if getattr(self, k):
                d[k] = getattr(self, k)
        return d


def resolve_token(inline: str = "", keyring_ref: str = "", env_var: str = "") -> str:
    """inline > keyring > env var. seren_meninges's resolve_token when it is
    importable (the same rules, the family's one implementation); else here."""
    try:
        from seren_meninges.credentials import resolve_token as _family  # type: ignore
        return _family(inline=inline or None, keyring_ref=keyring_ref or None, env_var=env_var or None) or ""
    except Exception:  # noqa: BLE001 - not installed, or an older meninges
        pass
    if inline:
        return inline
    if keyring_ref and "/" in keyring_ref:
        try:
            import keyring  # type: ignore
            service, user = keyring_ref.split("/", 1)
            got = keyring.get_password(service, user)
            if got:
                return got
        except Exception:  # noqa: BLE001
            pass
    if env_var:
        return os.environ.get(env_var, "") or ""
    return ""


# ── reading ───────────────────────────────────────────────────────────────────
def _read_yaml(path: str) -> Dict[str, Any]:
    text = open(path, encoding="utf-8").read()
    try:
        import yaml  # type: ignore
        data = yaml.safe_load(text)
        return data if isinstance(data, dict) else {}
    except ImportError:
        return _server_block_by_hand(text)


def _server_block_by_hand(text: str) -> Dict[str, Any]:
    """Enough YAML for a connection file, with no PyYAML: a top-level
    `server:` block of `key: value` lines, quotes stripped, comments dropped.
    A full service config gives the same server block back."""
    out: Dict[str, Any] = {}
    block: Dict[str, Any] = {}
    in_server = False
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].rstrip() if not raw.lstrip().startswith("#") else ""
        if not line.strip():
            continue
        if not line.startswith((" ", "\t")):
            in_server = line.strip() == "server:"
            continue
        if not in_server or ":" not in line:
            continue
        key, _, value = line.strip().partition(":")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        block[key.strip()] = value
    if block:
        out["server"] = block
    return out


def read_connection(path: str) -> Connection:
    """The connection a file describes. Raises (does not return a silent
    default) when the file cannot be read: a connection on defaults is a 401
    later, with nothing in the log to say why."""
    path = os.path.expanduser(path)
    data = _read_yaml(path)                                  # OSError if missing: on purpose
    server = data.get("server") if isinstance(data.get("server"), dict) else {}
    try:
        port = int(server.get("port") or 0)
    except (TypeError, ValueError):
        port = 0
    return Connection(host=str(server.get("host") or "127.0.0.1"), port=port,
                      bearer_token=str(server.get("bearer_token") or ""),
                      bearer_token_env=str(server.get("bearer_token_env") or ""),
                      bearer_token_keyring=str(server.get("bearer_token_keyring") or ""),
                      path=path)


# ── writing ───────────────────────────────────────────────────────────────────
_SAFE = re.compile(r"^[A-Za-z0-9_.\-]+$")


def write_connection(path: str, conn: Connection, note: str = "") -> str:
    """Write a connection file: a `server:` block and nothing else, readable
    by this module with or without PyYAML, 0600 where the OS has modes. The
    folder is made. Returns the path written."""
    path = os.path.expanduser(path)
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    lines = ["# A Seren connection file: where one service is and how to present its token.",
             "# Written by kbh register; read by the harness's headers helper when it connects."]
    if note:
        lines.append(f"# {note}")
    lines.append("server:")
    for k, v in conn.to_server_block().items():
        lines.append(f"  {k}: {json.dumps(v) if isinstance(v, str) else v}")
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    os.replace(tmp, path)
    return path


def connection_from_bundle_entry(name: str, entry: Dict[str, Any]) -> Connection:
    """One entry of a token bundle: {"host", "port", "bearer_token" | "..._env" | "..._keyring"}."""
    if not _SAFE.match(name):
        raise ValueError(f"'{name}' is not a usable service name (letters, digits, _ . -)")
    try:
        port = int(entry.get("port") or 0)
    except (TypeError, ValueError):
        raise ValueError(f"{name}: port is not a number") from None
    if port <= 0:
        raise ValueError(f"{name}: no port")
    return Connection(host=str(entry.get("host") or "127.0.0.1"), port=port,
                      bearer_token=str(entry.get("bearer_token") or ""),
                      bearer_token_env=str(entry.get("bearer_token_env") or ""),
                      bearer_token_keyring=str(entry.get("bearer_token_keyring") or ""))


def headers_for(path: str) -> Dict[str, str]:
    """What a headersHelper prints: {"Authorization": "Bearer ..."} or {}.
    Raises when the file cannot be read (the helper then exits 1 and the
    harness reports a failed helper, not a silent 401)."""
    token = read_connection(path).resolve_token()
    return {"Authorization": f"Bearer {token}"} if token else {}
