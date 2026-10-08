"""
kbh.install - `kbh <carabiner> install --into DIR ...`: the whole clip in one go.

    1. push a shipped custom/ out of the .kbh (the box's own custom/ wins)
    2. run custom/pre_install/*.py
    3. write <carabiner>.yaml from the carabiner's config.yaml template, filled
       with the flags; copy its framing.md beside it. Neither is ever
       overwritten: a re-install keeps what you edited.
    4. run custom/post_install/*.py (register apply, bookmark install, belay
       live here when someone ships a flavour that does it all)
    5. say what to do next

`kbh install --into DIR` with no carabiner is a tricks pack: a .kbh that
carries only custom/, layered onto whatever is installed in DIR.
"""
from __future__ import annotations

import os
import shutil
import sys
from typing import Any, Dict, List, Optional

from . import custom as _custom
from .config import write_starter


def _opt(argv: List[str], flag: str, default: str = "") -> str:
    return argv[argv.index(flag) + 1] if flag in argv and argv.index(flag) + 1 < len(argv) else default


def token_env_for(name: str) -> str:
    """KBH_TOKEN_<NAME>: where a token for an inline route reaches install -
    the environment, never the command line. wren-workbench -> KBH_TOKEN_WREN_WORKBENCH."""
    import re
    return "KBH_TOKEN_" + re.sub(r"[^A-Za-z0-9]", "_", name).upper()


def route_or_file(value: str, name: str, token_env_name: str = "") -> Any:
    """What a --server NAME=VALUE or --bookmark VALUE means: a URL is an
    inline ROUTE (url + the token from KBH_TOKEN_<NAME> in the environment,
    embedded, or a pointer named with --..-token-env); anything else is a
    connection file. When the service is on another box, drop in the uri and
    the token - no config copied from the brain."""
    value = (value or "").strip()
    if not value:
        return ""
    if value.startswith(("http://", "https://")):
        route: Dict[str, Any] = {"url": value.rstrip("/")}
        token = os.environ.get(token_env_for(name), "")
        if token:
            route["bearer_token"] = token
        elif token_env_name:
            route["bearer_token_env"] = token_env_name
        return route
    return value


def parse_servers(argv: List[str]) -> Dict[str, Any]:
    """--server NAME=FILE|URL, repeatable; --server-token-env NAME=VAR names
    the env var the harness box keeps NAME's token in (a pointer, not a value)."""
    pointers: Dict[str, str] = {}
    for i, a in enumerate(argv):
        if i > 0 and argv[i - 1] == "--server-token-env" and "=" in a:
            k, v = a.split("=", 1)
            pointers[k.strip()] = v.strip()
    servers: Dict[str, Any] = {}
    for i, a in enumerate(argv):
        if i > 0 and argv[i - 1] == "--server" and "=" in a:
            k, v = a.split("=", 1)
            servers[k.strip()] = route_or_file(v, k.strip(), pointers.get(k.strip(), ""))
    return servers


def _into(argv: List[str]) -> Optional[str]:
    """--into DIR, else the folder the .kbh itself sits in (when run from a zip)."""
    given = _opt(argv, "--into")
    if given:
        return os.path.abspath(os.path.expanduser(given))
    archive = _custom._archive_path()
    return os.path.dirname(archive) if archive else None


def install(carabiner: Any, argv: List[str]) -> int:
    into = _into(argv)
    if not into:
        print(f"usage: kbh {carabiner.name} install --into DIR --project DIR [--python P] [--connections DIR] "
              f"[--server NAME=FILE ...] [--bookmark FILE]  (run from a .kbh, --into defaults to its own folder)",
              file=sys.stderr)
        return 64
    os.makedirs(into, exist_ok=True)
    env = {"KBH_INTO": into, "KBH_CARABINER": carabiner.name,
           "KBH_CONFIG": os.path.join(into, f"{carabiner.name}.yaml"), "KBH_PYTHON": _opt(argv, "--python") or sys.executable}
    lines: List[str] = []

    # 1. a shipped custom/
    shipped = _custom.push(into, _custom.shipped_files())
    if shipped:
        lines.append(f"custom: {shipped}" + ("  (the box's custom/ was kept; merge by hand)" if shipped.endswith(".shipped") else ""))
    custom_dir = os.path.join(into, _custom.FOLDER)
    custom_dir = custom_dir if os.path.isdir(custom_dir) else None

    # 2. pre-install hooks
    try:
        lines += _custom.run_hooks(custom_dir, "pre_install", env)      # with THIS python; KBH_PYTHON names the configured one
    except RuntimeError as e:
        print("\n".join(lines), file=sys.stderr)
        print(str(e), file=sys.stderr)
        return 1

    # 3. the yaml and the framing, never overwritten
    servers = parse_servers(argv)
    bookmark = route_or_file(_opt(argv, "--bookmark"), "bookmark",
                             token_env_name=_opt(argv, "--bookmark-token-env"))
    yaml_path = os.path.join(into, f"{carabiner.name}.yaml")
    if os.path.exists(yaml_path):
        lines.append(f"config: {yaml_path} kept as it was")
        framing_path = os.path.join(into, "framing.md")
        if not os.path.exists(framing_path):
            with open(framing_path, "w", encoding="utf-8", newline="\n") as f:
                f.write(carabiner.default_framing())
            lines.append(f"framing: {framing_path} written from the default")
    else:
        out = write_starter(carabiner.name, carabiner.display, into, _opt(argv, "--project"), _opt(argv, "--python"),
                            _opt(argv, "--connections"), servers, bookmark, carabiner.default_framing(),
                            template=carabiner.config_template())
        lines.append(f"config: {out['yaml']} written")
        lines.append(f"framing: {out['framing']} {'written from the default' if out['framing_written'] == 'yes' else 'kept as it was'}")

    # 4. post-install hooks
    try:
        lines += _custom.run_hooks(custom_dir, "post_install", env)
    except RuntimeError as e:
        print("\n".join(lines))
        print(str(e), file=sys.stderr)
        return 1

    print("\n".join(lines))
    print(f"next: edit {yaml_path} and framing.md if you like, then  kbh {carabiner.name} belay --config {yaml_path}")
    return 0


def install_tricks(argv: List[str]) -> int:
    """`kbh install --into DIR`: no carabiner, only a custom/ to layer on."""
    into = _into(argv)
    if not into:
        print("usage: kbh install --into DIR   (a .kbh that carries only custom/)", file=sys.stderr)
        return 64
    files = _custom.shipped_files()
    if not files:
        print("this .kbh carries no custom/ and names no carabiner: nothing to install", file=sys.stderr)
        return 1
    dest = _custom.push(into, files)
    print(f"custom: {dest}" + ("  (the box's custom/ was kept; merge by hand)" if dest and dest.endswith(".shipped") else ""))
    return 0
