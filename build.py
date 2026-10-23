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

EVERY BUILD SAYS WHAT IT IS. A version alone did not: on 22 Oct 2026 a .kbh
from before a round of fixes and the fixed source both said 5.1.3. So the
commit goes in (kbh/_build.py), and `--version` says `kbh 5.1.3+6d5f1eb`. A
build from a tree that is not exactly that commit (uncommitted changes under
kbh/, a --from carabiner, a --with-custom layer) says
`5.1.3+6d5f1eb.dirty.<hash of what went in>`, so two of those can still be
told apart.

THE SAME SOURCE MAKES THE SAME FILE. The zip is written by hand rather than by
zipapp: names in order, one timestamp for every entry (SOURCE_DATE_EPOCH, or
1 Jan 1980), fixed permissions, text files with LF endings whatever the
checkout did, and stored, not deflated: zlib's output is its version's, and
3.11 and 3.14 on one box made two files of one source. Stored, it is ~150KB
instead of ~60KB, and one commit is one sha256 whatever python built it -
the sha256 beside a release names the code, not the builder.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.join(HERE, "kbh")
DIST = os.environ.get("KBH_DIST") or os.path.join(HERE, "dist")
SHEBANG = b"#!/usr/bin/env python3\n"
TEXT = (".py", ".md", ".yaml", ".yml", ".txt", ".json", ".toml", ".cfg", ".ini")
IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc", "tests", "_build.py")


def shipped() -> list:
    base = os.path.join(PKG, "carabiners")
    return sorted(d for d in os.listdir(base) if os.path.isdir(os.path.join(base, d)) and not d.startswith("_"))


def _git(*args: str) -> str:
    try:
        done = subprocess.run(["git", "-C", HERE, *args], capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return ""
    return done.stdout.strip() if done.returncode == 0 else ""


def _entries(root: str) -> list:
    """[(name in the zip, bytes or None for a folder)], in order, text with LF."""
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames.sort()
        rel = os.path.relpath(dirpath, root).replace(os.sep, "/")
        if rel != ".":
            out.append((rel + "/", None))
        for fname in sorted(filenames):
            with open(os.path.join(dirpath, fname), "rb") as f:
                data = f.read()
            if fname.lower().endswith(TEXT):
                data = data.replace(b"\r\n", b"\n")
            out.append(((fname if rel == "." else f"{rel}/{fname}"), data))
    return out


def stamp(root: str, extra: bool) -> str:
    """What this build is: the commit, and when the tree is not just that
    commit, a hash of what went in. `extra`: a --from or --with-custom."""
    commit = _git("rev-parse", "--short=7", "HEAD")
    changed = bool(_git("status", "--porcelain", "--", "kbh")) if commit else True
    if commit and not changed and not extra:
        return commit
    h = hashlib.sha256()
    for name, data in _entries(root):
        h.update(name.encode("utf-8") + b"\0" + (data if data is not None else b"/") + b"\0")
    return f"{commit or 'nogit'}.dirty.{h.hexdigest()[:8]}"


def write_zipapp(root: str, out: str) -> None:
    """root/ as a runnable zip at out, byte for byte the same for the same root."""
    epoch = int(os.environ.get("SOURCE_DATE_EPOCH") or 0)
    when = time.gmtime(max(epoch, 315532800))[:6]                # zip cannot say earlier than 1980
    tmp = out + ".part"
    with open(tmp, "wb") as fd:
        fd.write(SHEBANG)
        with zipfile.ZipFile(fd, "w", zipfile.ZIP_STORED) as zf:
            for name, data in _entries(root):
                info = zipfile.ZipInfo(name, date_time=when)
                info.create_system = 3                            # unix, on every OS: the mode bits below mean it
                if data is None:
                    info.external_attr = (0o40755 << 16) | 0x10
                    zf.writestr(info, b"")
                else:
                    info.external_attr = 0o644 << 16
                    zf.writestr(info, data)
    os.chmod(tmp, 0o755)
    os.replace(tmp, out)


def build(out_name: str, keep: list, external: dict, with_custom: str = "") -> str:
    """keep: shipped carabiners to carry; external: {name: folder} to add;
    with_custom: a custom/ folder to ship inside (pushed out by install)."""
    os.makedirs(DIST, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        root = os.path.join(tmp, "app")
        shutil.copytree(PKG, os.path.join(root, "kbh"), ignore=IGNORE)
        for d in shipped():
            if d not in keep:
                shutil.rmtree(os.path.join(root, "kbh", "carabiners", d))
        for name, folder in external.items():
            shutil.copytree(folder, os.path.join(root, "kbh", "carabiners", name),
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        if with_custom:
            shutil.copytree(with_custom, os.path.join(root, "custom"),
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        with open(os.path.join(root, "__main__.py"), "w", encoding="utf-8", newline="\n") as f:
            f.write("import sys\nfrom kbh.cli import main\nsys.exit(main())\n")
        build_id = stamp(root, bool(external or with_custom))
        with open(os.path.join(root, "kbh", "_build.py"), "w", encoding="utf-8", newline="\n") as f:
            f.write(f'"""Written by build.py: what this .kbh was built from."""\nBUILD = {build_id!r}\n')
        out = os.path.join(DIST, f"{out_name}.kbh")
        write_zipapp(root, out)
    return out


VALUE_FLAGS = ("--from", "--with-custom", "--as", "--tricks")
BARE_FLAGS = ("--all-in-one",)


class Usage(Exception):
    pass


def parse(argv: list) -> tuple:
    """(names, {flag: value}); refuses what it does not know rather than
    building something other than what was asked for."""
    names, opts, i = [], {}, 0
    while i < len(argv):
        a = argv[i]
        if a in VALUE_FLAGS:
            if i + 1 >= len(argv) or argv[i + 1].startswith("--"):
                raise Usage(f"{a} needs a value")
            if a in opts:
                raise Usage(f"{a} given twice")
            opts[a] = argv[i + 1]
            i += 2
            continue
        if a in BARE_FLAGS:
            opts[a] = True
        elif a.startswith("-"):
            raise Usage(f"no such flag: {a}")
        else:
            names.append(a)
        i += 1
    if "--all-in-one" in opts and (names or "--tricks" in opts or "--from" in opts):
        raise Usage("--all-in-one builds every shipped carabiner; name none")
    if "--tricks" in opts and (names or "--from" in opts):
        raise Usage("--tricks builds a pack with no carabiner; name none")
    if "--as" in opts and len(names) != 1 and "--all-in-one" not in opts:
        raise Usage("--as names one file: give exactly one carabiner")
    if "--from" in opts and not names:
        raise Usage("--from DIR needs the carabiner's name: python build.py NAME --from DIR")
    return names, opts


def main(argv: list) -> int:
    """
    python build.py                                   every shipped carabiner, one .kbh each
    python build.py claude [--with-custom DIR] [--as NAME]   claude.kbh, or NAME.kbh carrying DIR as custom/
    python build.py hermes --from DIR                 an external carabiner from DIR/hermes/
    python build.py --tricks NAME --with-custom DIR   NAME.kbh with no carabiner: a tricks pack
    python build.py --all-in-one                      seren.kbh with every shipped carabiner
    """
    try:
        names, opts = parse(argv)
    except Usage as e:
        print(f"build.py: {e}\n{main.__doc__}", file=sys.stderr)
        return 64
    with_custom = opts.get("--with-custom", "")
    if with_custom:
        with_custom = os.path.abspath(os.path.expanduser(with_custom))
        if not os.path.isdir(with_custom):
            print(f"no custom folder at {with_custom}", file=sys.stderr)
            return 1
    out_as = opts.get("--as", "")
    if "--all-in-one" in opts:
        print(build(out_as or "seren", shipped(), {}, with_custom))
        return 0
    if "--tricks" in opts:
        if not with_custom:
            print("--tricks needs --with-custom DIR", file=sys.stderr)
            return 1
        print(build(opts["--tricks"], [], {}, with_custom))
        return 0
    from_dir = opts.get("--from")
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
