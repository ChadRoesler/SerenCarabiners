"""
Build a .kbh: one zip per carabiner, named for its harness, runnable with any
Python 3.8+.

    python build.py                       -> dist/claude.kbh (one per shipped carabiner)
    python build.py claude                -> dist/claude.kbh
    python build.py hermes --from ./mine  -> dist/hermes.kbh, from ./mine/hermes/ (made by `kbh new hermes`)
    python build.py --all-in-one          -> dist/seren.kbh with every shipped carabiner

A .kbh is a zipapp (PEP 441) of the `kbh` binder plus the carabiner(s) it
carries. Run it like any Python file: `python claude.kbh claude belay`.
Nothing is installed on the harness box; the file can sit beside the service
that calls it (an Observatory's app folder, a person's ~/.seren).
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import zipapp

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.join(HERE, "kbh")
DIST = os.environ.get("KBH_DIST") or os.path.join(HERE, "dist")


def shipped() -> list:
    base = os.path.join(PKG, "carabiners")
    return sorted(d for d in os.listdir(base) if os.path.isdir(os.path.join(base, d)) and not d.startswith("_"))


def build(out_name: str, keep: list, external: dict, with_custom: str = "") -> str:
    """keep: shipped carabiners to carry; external: {name: folder} to add;
    with_custom: a custom/ folder to ship inside (pushed out by install)."""
    os.makedirs(DIST, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        root = os.path.join(tmp, "app")
        shutil.copytree(PKG, os.path.join(root, "kbh"),
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "tests"))
        for d in shipped():
            if d not in keep:
                shutil.rmtree(os.path.join(root, "kbh", "carabiners", d))
        for name, folder in external.items():
            shutil.copytree(folder, os.path.join(root, "kbh", "carabiners", name),
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        if with_custom:
            shutil.copytree(with_custom, os.path.join(root, "custom"),
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        with open(os.path.join(root, "__main__.py"), "w", encoding="utf-8") as f:
            f.write("import sys\nfrom kbh.cli import main\nsys.exit(main())\n")
        out = os.path.join(DIST, f"{out_name}.kbh")
        zipapp.create_archive(root, out, interpreter="/usr/bin/env python3", compressed=True)
    return out


def main(argv: list) -> int:
    """
    python build.py                                   every shipped carabiner, one .kbh each
    python build.py claude [--with-custom DIR] [--as NAME]   claude.kbh, or NAME.kbh carrying DIR as custom/
    python build.py hermes --from DIR                 an external carabiner from DIR/hermes/
    python build.py --tricks NAME --with-custom DIR   NAME.kbh with no carabiner: a tricks pack
    python build.py --all-in-one                      seren.kbh with every shipped carabiner
    """
    flags_with_value = ("--from", "--with-custom", "--as", "--tricks")
    with_custom = argv[argv.index("--with-custom") + 1] if "--with-custom" in argv else ""
    if with_custom:
        with_custom = os.path.abspath(os.path.expanduser(with_custom))
        if not os.path.isdir(with_custom):
            print(f"no custom folder at {with_custom}", file=sys.stderr)
            return 1
    out_as = argv[argv.index("--as") + 1] if "--as" in argv else ""
    if "--all-in-one" in argv:
        print(build(out_as or "seren", shipped(), {}, with_custom))
        return 0
    if "--tricks" in argv:
        name = argv[argv.index("--tricks") + 1]
        if not with_custom:
            print("--tricks needs --with-custom DIR", file=sys.stderr)
            return 1
        print(build(name, [], {}, with_custom))
        return 0
    names = [a for i, a in enumerate(argv) if not a.startswith("--") and (i == 0 or argv[i - 1] not in flags_with_value)]
    from_dir = argv[argv.index("--from") + 1] if "--from" in argv else None
    if not names:
        for c in shipped():
            print(build(c, [c], {}, with_custom))
        return 0
    for name in names:
        if from_dir:
            folder = os.path.join(os.path.abspath(os.path.expanduser(from_dir)), name)
            if not os.path.isfile(os.path.join(folder, "__init__.py")):
                print(f"no carabiner at {folder}", file=sys.stderr)
                return 1
            print(build(out_as or name, [], {name: folder}, with_custom))
        elif name in shipped():
            print(build(out_as or name, [name], {}, with_custom))
        else:
            print(f"no shipped carabiner named '{name}'; for your own, say --from DIR", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
