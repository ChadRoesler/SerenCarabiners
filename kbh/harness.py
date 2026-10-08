"""
kbh.harness - what every carabiner is.

A Carabiner declares which verbs it supports and implements them as methods
that take the parsed command line. The binder (cli.py) finds carabiners by
name under kbh.carabiners, hands each verb its arguments, and runs belay.

`self_command()` is how a carabiner refers to ITSELF from inside a harness's
settings (a headersHelper, a hook command, an Observatory's ripple command):
the interpreter running now plus the way this code was started - the .kbh
zip's path, or `-m kbh` for an installed package. Whatever the harness runs
later is therefore the same code that registered it.
"""
from __future__ import annotations

import os
import sys
from typing import Dict, List, Optional

from . import belay

VERBS = ("register", "wake", "bookmark", "due")


def self_command(python: Optional[str] = None) -> List[str]:
    """[python, <this code>] - a command line that reaches kbh again later."""
    py = python or sys.executable
    main = sys.modules.get("__main__")
    main_file = getattr(main, "__file__", "") or ""
    # Started as a zipapp (`python seren-claude.kbh ...`): __main__.__file__ is
    # inside the archive; the archive is the first path element that is a file.
    for p in [main_file] + sys.path[:3]:
        if p and os.path.isfile(p) and p.lower().endswith((".kbh", ".pyz", ".zip")):
            return [py, os.path.abspath(p)]
    here = os.path.dirname(os.path.abspath(__file__))
    archive = os.path.dirname(here)
    if os.path.isfile(archive) and archive.lower().endswith((".kbh", ".pyz", ".zip")):
        return [py, archive]
    return [py, "-m", "kbh"]


class Carabiner:
    name = "base"                     # the harness, lower-case: "claude"
    display = "a harness"
    supports: Dict[str, bool] = {v: False for v in VERBS}
    description = ""

    # ── the verbs: each takes the remaining argv and returns an exit code ──
    def register(self, argv: List[str]) -> int:
        return self._unsupported("register")

    def wake(self, argv: List[str]) -> int:
        return self._unsupported("wake")

    def bookmark(self, argv: List[str]) -> int:
        return self._unsupported("bookmark")

    def due(self, argv: List[str]) -> int:
        return self._unsupported("due")

    def headers(self, argv: List[str]) -> int:
        """The headersHelper entry: print the Authorization header for a
        connection file. Shared by every carabiner whose harness takes one."""
        import json
        from .tokens import headers_for
        if len(argv) != 1:
            print(f"usage: kbh {self.name} headers <connection file | config.yaml#server-name>", file=sys.stderr)
            return 64
        try:
            print(json.dumps(headers_for(argv[0])))
        except Exception as e:  # noqa: BLE001 - say why, and fail: no header is a 401 later
            print(f"kbh {self.name} headers: cannot read the bearer from {argv[0]}: {type(e).__name__}: {e}",
                  file=sys.stderr)
            return 1
        return 0

    # ── what a carabiner ships beside its code ──
    custom: Any = None                # kbh.custom.Custom, set by the cli when a custom/ is found

    def _packaged(self, filename: str) -> Optional[str]:
        """A file shipped beside this carabiner's module (framing.md,
        config.yaml), read through pkgutil so it is found inside a .kbh."""
        import pkgutil
        mod = type(self).__module__                        # the package itself when the class is in __init__.py
        for pkg in dict.fromkeys([mod, mod.rsplit(".", 1)[0] if "." in mod else mod]):
            try:
                data = pkgutil.get_data(pkg, filename)
            except Exception:  # noqa: BLE001
                data = None
            if data:
                return data.decode("utf-8")
        return None

    def default_framing(self) -> str:
        """The carabiner's framing.md: the fallback when the yaml names none,
        and what install copies beside the yaml for a person to edit."""
        return self._packaged("framing.md") or "{message}\n"

    def config_template(self) -> Optional[str]:
        """The carabiner's config.yaml template, pushed out as <name>.yaml."""
        return self._packaged("config.yaml")

    def install(self, argv: List[str]) -> int:
        from .install import install
        return install(self, argv)

    # ── init: the yaml that says how this carabiner rolls here ──

    def init(self, argv: List[str]) -> int:
        """kbh <carabiner> init --into DIR --project DIR [--python P] [--connections DIR]
        [--server NAME=FILE ...] [--bookmark FILE]: write <DIR>/<carabiner>.yaml
        and <DIR>/framing.md (the default, to edit). Never overwrites a yaml."""
        from .config import write_starter

        def opt(flag: str, default: str = "") -> str:
            return argv[argv.index(flag) + 1] if flag in argv and argv.index(flag) + 1 < len(argv) else default
        into = opt("--into")
        if not into:
            print(f"usage: kbh {self.name} init --into DIR --project DIR [--python P] [--connections DIR] "
                  f"[--server NAME=FILE ...] [--bookmark FILE]", file=sys.stderr)
            return 64
        from .install import parse_servers, route_or_file
        servers = parse_servers(argv)
        bookmark = route_or_file(opt("--bookmark"), "bookmark", opt("--bookmark-token-env"))
        try:
            out = write_starter(self.name, self.display, into, opt("--project"), opt("--python"),
                                opt("--connections"), servers, bookmark, self.default_framing(),
                                template=self.config_template())
        except FileExistsError as e:
            print(str(e), file=sys.stderr)
            return 1
        print(f"wrote {out['yaml']}")
        print(f"framing: {out['framing']} ({'written from the default' if out['framing_written'] == 'yes' else 'kept as it was'})")
        print(f"next: edit them, then  kbh {self.name} belay --config {out['yaml']}")
        return 0

    # ── belay ──
    def belay_checks(self, argv: List[str]):
        """The checks this carabiner runs; subclasses extend."""
        return []

    def belay(self, argv: List[str]) -> int:
        checks = list(self.belay_checks(argv))
        if self.custom is not None:
            checks += self.custom.checks(self, argv)
        rep = belay.run(self.name, checks)
        print(rep.json() if "--json" in argv else rep.text())
        return 0 if rep.ok else 1

    def _unsupported(self, verb: str) -> int:
        print(f"{self.display} has no {verb}: this carabiner says {verb}: unsupported", file=sys.stderr)
        return 3

    def manifest(self) -> dict:
        return {"name": self.name, "harness": self.display, "verbs": dict(self.supports),
                "description": self.description}
