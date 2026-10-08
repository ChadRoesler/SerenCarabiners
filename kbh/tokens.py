"""
kbh.tokens - connection files, and the token they point at.

A CONNECTION is a ROUTE: where one Seren service is and how to present its
bearer - a URL and a token (or a pointer to one). It has three homes:

  - inline in the carabiner's own yaml (the usual form when the service is on
    another box: drop in the uri and the token):

        servers:
          wren-workbench:
            url: http://nuc:7255
            bearer_token: "..."          # or bearer_token_env / bearer_token_keyring
        bookmark:
          url: http://nuc:7251
          bearer_token_env: WREN_MARGIN_TOKEN

    and is referred to as `<that yaml>#wren-workbench` (or `#bookmark`) by the
    harness's headers helper and hooks, so nothing is copied anywhere.

  - a CONNECTION FILE: a `server:` block, which a service's own full config is
    too - the on-box form, when the service runs where the harness does:

        server:
          host: nuc           # or url: http://nuc:7255
          port: 7255
          bearer_token: "..."

  - a token bundle entry (register bundle): {"url" | "host"+"port", "bearer_token..."}

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
from urllib.parse import urlsplit

LOOPBACK = ("", "0.0.0.0", "::", None)


@dataclass
class Connection:
    host: str = "127.0.0.1"
    port: int = 0
    bearer_token: str = ""
    bearer_token_env: str = ""
    bearer_token_keyring: str = ""
    path: str = ""                       # the file it came from

    url: str = ""                        # set = the route as given; else built from host + port

    @property
    def base_url(self) -> str:
        if self.url:
            return self.url.rstrip("/")
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
        d: Dict[str, Any] = {"url": self.url} if self.url else {"host": self.host, "port": self.port}
        for k in ("bearer_token", "bearer_token_env", "bearer_token_keyring"):
            if getattr(self, k):
                d[k] = getattr(self, k)
        return d

    @property
    def where(self) -> str:
        return self.url or f"{self.host}:{self.port}"


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


def connection_from_route(d: Dict[str, Any], path: str = "") -> Connection:
    """A Connection from a route mapping: `url`, or `host` + `port`, plus the
    token or its pointer. Raises ValueError when it names nowhere."""
    url = str(d.get("url") or "").strip()
    try:
        port = int(d.get("port") or 0)
    except (TypeError, ValueError):
        port = 0
    if url:
        u = urlsplit(url)
        if u.scheme not in ("http", "https") or not u.hostname:
            raise ValueError(f"not a usable url: {url}")
        if u.username or u.password:
            raise ValueError("a token never rides in the url: use bearer_token / bearer_token_env / bearer_token_keyring")
        host, port = u.hostname, u.port or (443 if u.scheme == "https" else 80)
    else:
        host = str(d.get("host") or "127.0.0.1")
        if port <= 0:
            raise ValueError("a route needs a url, or a host and a port")
    return Connection(host=host, port=port, url=url.rstrip("/"),
                      bearer_token=str(d.get("bearer_token") or ""),
                      bearer_token_env=str(d.get("bearer_token_env") or ""),
                      bearer_token_keyring=str(d.get("bearer_token_keyring") or ""),
                      path=path)


def read_connection(ref: str) -> Connection:
    """The connection a reference names. Two forms:

        <file>            a connection file (a `server:` block)
        <yaml>#<name>     a route inline in a carabiner's yaml: servers.<name>,
                          or its bookmark when <name> is "bookmark"

    Raises (never a silent default) when it cannot be read: a connection on
    defaults is a 401 later, with nothing in the log to say why."""
    ref = os.path.expanduser(ref)
    if "#" in ref and not os.path.isfile(ref):
        path, _, name = ref.rpartition("#")
        from .config import load                              # lazy: config imports this module
        cfg = load(path)
        route = cfg.bookmark if name == "bookmark" else cfg.servers.get(name)
        if route is None or route == "":
            raise KeyError(f"{path} has no server or bookmark named '{name}'")
        if isinstance(route, dict):
            return connection_from_route(route, path=ref)
        return read_connection(cfg.connection(name))      # a file after all
    data = _read_yaml(ref)                                   # OSError if missing: on purpose
    server = data.get("server") if isinstance(data.get("server"), dict) else {}
    if not server:
        raise ValueError(f"{ref} has no server: block")
    return connection_from_route(server, path=ref)


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
    """One entry of a token bundle: {"url" | "host"+"port", "bearer_token" | "..._env" | "..._keyring"}."""
    if not _SAFE.match(name):
        raise ValueError(f"'{name}' is not a usable service name (letters, digits, _ . -)")
    try:
        return connection_from_route(entry)
    except ValueError as e:
        raise ValueError(f"{name}: {e}") from None


def headers_for(path: str) -> Dict[str, str]:
    """What a headersHelper prints: {"Authorization": "Bearer ..."} or {}.
    Raises when the file cannot be read (the helper then exits 1 and the
    harness reports a failed helper, not a silent 401)."""
    token = read_connection(path).resolve_token()
    return {"Authorization": f"Bearer {token}"} if token else {}
