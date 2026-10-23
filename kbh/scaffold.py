"""
kbh.scaffold - `kbh new NAME`: a carabiner to start from.

Copies the template carabiner into a folder of its own with the names filled
in, ready for `kbh --path <that folder's parent> NAME manifest` and
`python build.py NAME --from <that folder's parent>`. Anyone can write a
carabiner for the harness they use without forking this repo: we ship a few
and the template, and the world goes wild.
"""
from __future__ import annotations

import os
import pkgutil
import re
import sys
from typing import List, Optional

_NAME = re.compile(r"^[a-z][a-z0-9_]{1,31}$")


# The template's files, named rather than listed: inside a .kbh the template
# is in a zip, where there is no folder to list, only pkgutil to read through.
TEMPLATE = "kbh.carabiners._template"
TEMPLATE_FILES = ("__init__.py", "config.yaml", "framing.md")


def template_files() -> dict:
    return {fname: pkgutil.get_data(TEMPLATE, fname).decode("utf-8") for fname in TEMPLATE_FILES}


def new(name: str, into: Optional[str] = None, display: Optional[str] = None) -> str:
    """Make <into>/<name>/ from the template. Returns the folder made."""
    if not _NAME.match(name):
        raise ValueError(f"'{name}' is not a usable carabiner name: lower_snake_case, 2-32 chars, a letter first")
    display = display or name.replace("_", " ").title()
    into = os.path.abspath(os.path.expanduser(into or "."))
    dest = os.path.join(into, name)
    if os.path.exists(dest):
        raise FileExistsError(f"{dest} already exists")
    files = template_files()                          # read it all before making anything
    os.makedirs(dest)
    for fname, text in files.items():
        text = text.replace("__NAME__", name).replace("__HARNESS__", display)
        text = text.replace("class TemplateCarabiner", f"class {_class_name(name)}")
        text = text.replace("CARABINER = TemplateCarabiner", f"CARABINER = {_class_name(name)}")
        with open(os.path.join(dest, fname), "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
    return dest


def _class_name(name: str) -> str:
    return "".join(p.title() for p in name.split("_")) + "Carabiner"


def run(argv: List[str]) -> int:
    if not argv or argv[0].startswith("-"):
        print("usage: kbh new NAME [--into DIR] [--display 'Harness Name']", file=sys.stderr)
        return 64
    into = argv[argv.index("--into") + 1] if "--into" in argv else None
    display = argv[argv.index("--display") + 1] if "--display" in argv else None
    try:
        dest = new(argv[0], into, display)
    except (ValueError, FileExistsError) as e:
        print(str(e), file=sys.stderr)
        return 1
    print(f"made {dest}")
    print(f"  fill in {os.path.join(dest, '__init__.py')} and framing.md, then:")
    print(f"  kbh --path {os.path.dirname(dest)} {argv[0]} manifest")
    print(f"  python build.py {argv[0]} --from {os.path.dirname(dest)}      -> dist/{argv[0]}.kbh")
    return 0
