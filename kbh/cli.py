"""
kbh.cli - the command line.

    kbh list                                  the carabiners this build carries
    kbh <carabiner> <verb> [args]             register | wake | bookmark | due
    kbh <carabiner> headers <connection>      the headersHelper (what a harness runs on connect)
    kbh <carabiner> belay [--json] [args]     on belay? belay on. climbing. climb on.
    kbh <carabiner> manifest                  what it supports, as JSON
    kbh <carabiner> install [--into DIR] ...  the whole clip: push config.yaml -> <carabiner>.yaml, framing.md
                                              and any shipped custom/ beside the .kbh; run custom hooks
    kbh <carabiner> init --into DIR ...       only the yaml + framing (install's quiet form)
    kbh install --into DIR                    a tricks pack: a .kbh with only custom/, layered on
    kbh new NAME [--into DIR]                 a carabiner to start from (the template)
    kbh --path DIR ...                        also look for carabiners in DIR (one folder each);
                                              KBH_CARABINERS=DIR[:DIR] does the same

Exit codes: 0 done; 1 a verb failed and said why; 2 refused (a wake that
would reach nobody, a settings file that is not JSON); 3 the verb is
unsupported by this harness; 64 usage.
"""
from __future__ import annotations

import importlib
import importlib.util
import json
import os
import pkgutil
import sys
from typing import Dict, List, Optional, Type

from . import __version__
from .harness import Carabiner

VERB_NAMES = ("register", "wake", "bookmark", "due", "headers", "belay", "init", "install")


def _external_dirs(extra: Optional[List[str]] = None) -> List[str]:
    dirs = list(extra or [])
    env = os.environ.get("KBH_CARABINERS", "")
    dirs += [d for d in env.split(os.pathsep) if d]
    return [os.path.abspath(os.path.expanduser(d)) for d in dirs]


def _load_external(folder: str) -> Dict[str, Type[Carabiner]]:
    """Every subfolder of `folder` with an __init__.py is a carabiner package;
    imported as kbh.carabiners.<name> so its relative imports (`from ...belay`)
    resolve against the binder it is running in."""
    found: Dict[str, Type[Carabiner]] = {}
    if not os.path.isdir(folder):
        return found
    from . import carabiners as pkg
    for entry in sorted(os.listdir(folder)):
        init = os.path.join(folder, entry, "__init__.py")
        if entry.startswith(("_", ".")) or not os.path.isfile(init):
            continue
        modname = f"{pkg.__name__}.{entry}"
        spec = importlib.util.spec_from_file_location(modname, init, submodule_search_locations=[os.path.join(folder, entry)])
        if spec is None or spec.loader is None:
            continue
        mod = importlib.util.module_from_spec(spec)
        sys.modules[modname] = mod
        try:
            spec.loader.exec_module(mod)
        except Exception as e:  # noqa: BLE001 - one bad carabiner must not hide the rest
            print(f"kbh: {init} did not load: {type(e).__name__}: {e}", file=sys.stderr)
            continue
        cls = getattr(mod, "CARABINER", None)
        if isinstance(cls, type) and issubclass(cls, Carabiner):
            found[cls.name] = cls
    return found


def carabiners(extra_dirs: Optional[List[str]] = None) -> Dict[str, Type[Carabiner]]:
    from . import carabiners as pkg
    found: Dict[str, Type[Carabiner]] = {}
    for info in pkgutil.iter_modules(pkg.__path__):
        if info.name.startswith("_"):                                  # the template
            continue
        mod = importlib.import_module(f"{pkg.__name__}.{info.name}")
        cls = getattr(mod, "CARABINER", None)
        if isinstance(cls, type) and issubclass(cls, Carabiner):
            found[cls.name] = cls
    for folder in _external_dirs(extra_dirs):
        found.update(_load_external(folder))                           # an external one may replace a shipped one
    return found


def main(argv: Optional[List[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    extra: List[str] = []
    while "--path" in argv:
        i = argv.index("--path")
        if i + 1 >= len(argv):
            print("--path needs a folder", file=sys.stderr)
            return 64
        extra.append(argv[i + 1])
        del argv[i:i + 2]
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__.strip(), file=sys.stderr)
        return 64
    if argv[0] in ("-V", "--version"):
        print(f"kbh {__version__}")
        return 0
    if argv[0] == "new":
        from .scaffold import run as new
        return new(argv[1:])
    if argv[0] == "install":                                           # a tricks pack: custom/ only
        from .install import install_tricks
        return install_tricks(argv[1:])
    known = carabiners(extra)
    if argv[0] == "list":
        for name, cls in sorted(known.items()):
            c = cls()
            verbs = ", ".join(v for v, ok in c.supports.items() if ok) or "nothing yet"
            print(f"{name:10s} {c.display}: {verbs}")
        return 0
    name = argv[0]
    cls = known.get(name)
    if cls is None:
        print(f"no carabiner named '{name}'; this build carries: {', '.join(sorted(known)) or 'none'} "
              f"(kbh --path DIR looks in DIR too; kbh new {name} starts one)", file=sys.stderr)
        return 64
    c = cls()
    if len(argv) < 2:
        print(f"usage: kbh {name} <register|wake|bookmark|due|headers|belay|init|manifest> ...", file=sys.stderr)
        return 64
    verb, rest = argv[1], argv[2:]
    # The box's custom/ (beside the config, which is beside the .kbh): extra
    # verbs and belay checks, loaded for every command but install itself.
    if verb != "install":
        from . import config as _config
        from .custom import Custom, folder_beside
        explicit = rest[rest.index("--config") + 1] if "--config" in rest and rest.index("--config") + 1 < len(rest) else None
        c.custom = Custom(folder_beside(_config.find(name, explicit)))
    if verb == "manifest":
        m = c.manifest()
        if c.custom is not None and (c.custom.verbs or c.custom.folder):
            m["custom"] = {"folder": c.custom.folder, "verbs": sorted(c.custom.verbs), "errors": c.custom.errors}
        print(json.dumps(m, indent=2))
        return 0
    fn = getattr(c, verb, None)
    if verb in VERB_NAMES and fn is not None:
        return int(fn(rest))
    if c.custom is not None and verb in c.custom.verbs:
        return int(c.custom.verbs[verb](c, rest))
    print(f"kbh {name}: no verb '{verb}'"
          + (f" (custom/ adds: {', '.join(sorted(c.custom.verbs))})" if c.custom is not None and c.custom.verbs else ""),
          file=sys.stderr)
    return 64
