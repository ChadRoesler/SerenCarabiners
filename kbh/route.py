"""
kbh.route - `kbh <carabiner> route`: add, move or drop a connection after the
install, without opening the yaml.

    kbh <c> route list [--json]
    kbh <c> route add NAME URL|FILE [--token-env VAR | --token-keyring SVC/USER | --no-token]
                                    [--partner P] [--hand H] [--no-apply] [--json]
    kbh <c> route remove NAME [--no-apply] [--json]

NAME is a server the model will see (`memory`, `ada-workbench`), or one of
the two that are not servers: `bookmark` (Margin) and `kitchen` (presence).

WHY. `install --server NAME=URL` writes a route once, and never again: the
yaml is never overwritten. A service added later (a kitchen, 10 Nov 2026), or
one that moved, meant opening the yaml and typing a token into it. `config`
cannot do it, on purpose: a token must never travel through a form. This is
the command a form's "add service" button runs, and the whole of it on a box
with no Lodestar to draw the form.

THE TOKEN NEVER RIDES ON THE COMMAND LINE. In order: KBH_TOKEN_<NAME> in the
environment (written into the yaml, as install does); --token-env or
--token-keyring (a pointer, nothing secret written); a hidden prompt when a
person is at a terminal; --no-token for an open service. Adding a NAME that is
already there keeps its token unless a new one is given: a service that moved
has a new url, not a new token. With none of those and nobody to ask, nothing
is written: a route on no token is a 401 later with nothing to say why.

THEN IT IS APPLIED, unless --no-apply: a server is registered with the harness
(`register apply`), a bookmark or a kitchen gets its hooks, a removed one loses
them; and belay runs, because the yaml changed and whether the carabiner still
holds is part of the answer. The yaml's comments are kept (kbh.yamledit), the
old file is beside it as <name>.seren-bak, and a yaml that now holds a token
is made 0600.
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import re
import sys
from typing import Any, Dict, List, Optional, Tuple

from . import belay, config, yamledit
from .configure import _token_kind, _where
from .install import route_or_file, token_env_for
from .tokens import connection_from_route

SPECIAL = ("bookmark", "kitchen")
_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.\-]{0,63}$")
_TOKEN_KEYS = ("bearer_token", "bearer_token_env", "bearer_token_keyring")
USAGE = ("usage: kbh {c} route (list | add NAME URL|FILE [--token-env VAR | --token-keyring SVC/USER | --no-token] "
         "[--partner P] [--hand H] | remove NAME) [--no-apply] [--json]   NAME: a server, bookmark, or kitchen")


def _opt(argv: List[str], flag: str) -> str:
    return argv[argv.index(flag) + 1] if flag in argv and argv.index(flag) + 1 < len(argv) else ""


def _current(cfg: config.HarnessConfig, name: str) -> Any:
    if name in SPECIAL:
        return getattr(cfg, name) or None
    return cfg.servers.get(name)


def _ask() -> Optional[str]:
    """A token typed at a hidden prompt, or None when nobody is there to ask."""
    try:
        if not sys.stdin or not sys.stdin.isatty():
            return None
        import getpass
        return getpass.getpass("token (hidden; leave empty for an open service): ").strip()
    except (EOFError, KeyboardInterrupt, OSError):
        return None


def build(name: str, value: str, argv: List[str], old: Any) -> Tuple[Any, str]:
    """(the route to write, "") or (None, why not). A FILE comes back as its name."""
    route = route_or_file(value, name, _opt(argv, "--token-env"))
    if not isinstance(route, dict):
        if name == "kitchen":
            return None, "the kitchen is given as a url (its partner and hand sit beside it in the yaml)"
        return route, ""
    try:
        connection_from_route(route)
    except ValueError as e:
        return None, str(e)
    if _opt(argv, "--token-keyring") and not route.get("bearer_token"):
        route.pop("bearer_token_env", None)
        route["bearer_token_keyring"] = _opt(argv, "--token-keyring")
    if not any(route.get(k) for k in _TOKEN_KEYS) and "--no-token" not in argv:
        kept = {k: old[k] for k in _TOKEN_KEYS if isinstance(old, dict) and old.get(k)}
        if kept:
            route.update(kept)
        else:
            typed = _ask()
            if typed is None:
                return None, (f"no token for {name}: set {token_env_for(name)} in the environment, or say --token-env VAR, "
                              f"--token-keyring SVC/USER, or --no-token for an open service")
            if typed:
                route["bearer_token"] = typed
    if name == "kitchen":
        for key in ("partner", "hand"):
            given = _opt(argv, f"--{key}") or (old.get(key) if isinstance(old, dict) else "")
            if given:
                route[key] = given
        if not route.get("partner"):
            return None, "a kitchen needs to know whose sessions these are: --partner NAME"
    return route, ""


def _apply(c, name: str, path: str, removed: bool) -> Tuple[int, str]:
    """Tell the harness. (exit code, what the verb said)."""
    if name == "bookmark":
        verb, args = "bookmark", (["remove"] if removed else ["install", "--config", path])
    elif name == "kitchen":
        verb, args = "presence", (["remove"] if removed else ["install", "--config", path])
    else:
        verb, args = "register", (["remove", name] if removed else ["apply", "--config", path])
    if not c.supports.get(verb):
        return 0, f"{c.display} has no {verb}: the yaml is changed and nothing else was"
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
        rc = int(getattr(c, verb)(args))
    return rc, out.getvalue().strip()


def _listing(cfg: config.HarnessConfig) -> List[Dict[str, str]]:
    rows = [{"name": n, "kind": "server", "where": _where(r), "token": _token_kind(r)} for n, r in cfg.servers.items()]
    for n in SPECIAL:
        r = getattr(cfg, n)
        if r:
            rows.append({"name": n, "kind": n, "where": _where(r), "token": _token_kind(r)})
    return rows


def run(c, argv: List[str]) -> int:
    as_json = "--json" in argv
    if not argv or argv[0] not in ("list", "add", "remove"):
        print(USAGE.format(c=c.name), file=sys.stderr)
        return 64
    try:
        cfg = config.load_for(c.name, argv)
    except OSError as e:
        print(f"cannot read the config: {e}", file=sys.stderr)
        return 1
    if cfg is None:
        print(f"no config found: say --config {c.name}.yaml (kbh {c.name} install writes one)", file=sys.stderr)
        return 64
    if argv[0] == "list":
        rows = _listing(cfg)
        if as_json:
            print(json.dumps({"config": cfg.path, "routes": rows}, indent=2))
        else:
            for r in rows:
                print(f"{r['name']:24s} {r['where']:40s} [{r['kind']}, token: {r['token']}]")
            if not rows:
                print(f"{cfg.path} names no routes")
        return 0

    positional = []
    skip = False
    for a in argv[1:]:
        if skip:
            skip = False
        elif a in ("--config", "--token-env", "--token-keyring", "--partner", "--hand"):
            skip = True
        elif not a.startswith("--"):
            positional.append(a)
    removing = argv[0] == "remove"
    if len(positional) != (1 if removing else 2) or not _NAME.match(positional[0]):
        print(USAGE.format(c=c.name), file=sys.stderr)
        return 64
    name = positional[0]
    old = _current(cfg, name)
    text = open(cfg.path, encoding="utf-8").read()
    if removing:
        if old is None:
            print(f"{cfg.path} has no route named {name}", file=sys.stderr)
            return 1
        new_text, route = yamledit.drop_route(text, name, top=name in SPECIAL), None
    else:
        route, why = build(name, positional[1], argv, old)
        if route is None:
            print(why, file=sys.stderr)
            return 64
        new_text = yamledit.put_route(text, name, route, top=name in SPECIAL)
    yamledit.write(cfg.path, new_text)
    if config.load(cfg.path).has_inline_token():
        try:
            os.chmod(cfg.path, 0o600)                       # an inline token makes the file a secret
        except OSError:
            pass
    answer: Dict[str, Any] = {"ok": True, "config": cfg.path, "name": name,
                              "did": "removed" if removing else ("changed" if old is not None else "added")}
    if not removing:
        answer["where"], answer["token"] = _where(route), _token_kind(route)
    rc = 0
    if "--no-apply" not in argv:
        rc, said = _apply(c, name, cfg.path, removing)
        answer["applied"] = {"ok": rc == 0, "said": said}
        checks = list(c.belay_checks(["--config", cfg.path]))
        if c.custom is not None:
            checks += c.custom.checks(c, ["--config", cfg.path])
        rep = belay.run(c.name, checks)
        answer["belay"] = json.loads(rep.json())
        answer["ok"] = rc == 0
    if as_json:
        print(json.dumps(answer, indent=2))
    else:
        line = f"{answer['did']} {name}" + (f" -> {answer['where']} (token: {answer['token']})" if not removing else "")
        print(f"{line} in {cfg.path}")
        if "applied" in answer:
            if answer["applied"]["said"]:
                print(answer["applied"]["said"])
            print(rep.text())
    return 0 if rc == 0 else 1
