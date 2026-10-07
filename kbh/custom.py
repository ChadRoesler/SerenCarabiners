"""
kbh.custom - the layer anyone adds without touching the base.

    <install dir>/custom/
      python/          a module per file; each may define
                         VERBS = {"name": fn(carabiner, argv) -> int}      extra verbs: kbh claude <name>
                         BELAY_CHECKS = fn(carabiner, argv) -> [check fns]  extra belay lines
      extras/          anything the yaml points at (a framing per event, a prompt, a script)
      pre_install/     *.py run before install pushes the config out
      post_install/    *.py run after (register apply, bookmark install, belay: the whole clip)

TWO PLACES IT COMES FROM. Beside the installed .kbh: the box's own tweaks,
which a newer .kbh dropped in never touches. Inside a .kbh: someone's flavour,
bundled to hand over (`build.py claude --with-custom ./mine` ->
chads-claude.kbh), pushed out beside the zip by `install`; when the box
already has a custom/, the box's wins and the shipped one lands as
custom.shipped/ to merge by hand. A .kbh with no carabiner and only a custom/
is a tricks pack: `python tricks.kbh install --into DIR` layers it onto
whatever carabiner is installed there.

Plain Python on the person's own box, run as them: no sandbox pretence. The
install prints each hook it runs.
"""
from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import zipfile
from typing import Any, Callable, Dict, List, Optional, Tuple

FOLDER = "custom"


class Custom:
    """What the box's custom/ folder adds, loaded once per command."""

    def __init__(self, folder: Optional[str]) -> None:
        self.folder = folder
        self.verbs: Dict[str, Callable[[Any, List[str]], int]] = {}
        self.check_makers: List[Callable[[Any, List[str]], list]] = []
        self.errors: List[str] = []
        if folder and os.path.isdir(os.path.join(folder, "python")):
            self._load(os.path.join(folder, "python"))

    def _load(self, pydir: str) -> None:
        for fname in sorted(os.listdir(pydir)):
            if not fname.endswith(".py") or fname.startswith("_"):
                continue
            path = os.path.join(pydir, fname)
            modname = f"kbh_custom_{os.path.splitext(fname)[0]}"
            try:
                spec = importlib.util.spec_from_file_location(modname, path)
                mod = importlib.util.module_from_spec(spec)                # type: ignore[arg-type]
                sys.modules[modname] = mod
                spec.loader.exec_module(mod)                              # type: ignore[union-attr]
            except Exception as e:  # noqa: BLE001 - one bad file must not take the carabiner down
                self.errors.append(f"{path}: {type(e).__name__}: {e}")
                continue
            for name, fn in (getattr(mod, "VERBS", None) or {}).items():
                if callable(fn):
                    self.verbs[str(name)] = fn
            maker = getattr(mod, "BELAY_CHECKS", None)
            if callable(maker):
                self.check_makers.append(maker)

    def checks(self, carabiner: Any, argv: List[str]) -> list:
        out: list = []
        for maker in self.check_makers:
            try:
                out.extend(maker(carabiner, argv) or [])
            except Exception as e:  # noqa: BLE001
                from .belay import let_go
                out.append(lambda e=e: let_go("custom", "on belay?", "BELAY_CHECKS", f"{type(e).__name__}: {e}"))
        for err in self.errors:
            from .belay import let_go
            out.append(lambda err=err: let_go("custom", "on belay?", "python", err))
        return out


def folder_beside(config_path: Optional[str]) -> Optional[str]:
    """The box's custom/ folder: beside the config (which is beside the .kbh)."""
    if not config_path:
        return None
    return os.path.join(os.path.dirname(os.path.abspath(config_path)), FOLDER)


# ── what a .kbh carries ───────────────────────────────────────────────────────
def _archive_path() -> Optional[str]:
    from .harness import self_command
    cmd = self_command()
    return cmd[1] if len(cmd) == 2 and os.path.isfile(cmd[1]) else None


def shipped_files() -> List[Tuple[str, bytes]]:
    """(relative path, bytes) for every file under custom/ inside the running
    .kbh - or under <repo>/custom/ when running from source. Empty when none."""
    out: List[Tuple[str, bytes]] = []
    archive = _archive_path()
    if archive:
        with zipfile.ZipFile(archive) as z:
            for info in z.infolist():
                if info.filename.startswith(FOLDER + "/") and not info.is_dir():
                    out.append((info.filename[len(FOLDER) + 1:], z.read(info)))
        return out
    root = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), FOLDER)
    if os.path.isdir(root):
        for dirpath, _, files in os.walk(root):
            for f in files:
                p = os.path.join(dirpath, f)
                out.append((os.path.relpath(p, root).replace(os.sep, "/"), open(p, "rb").read()))
    return out


def push(into: str, files: List[Tuple[str, bytes]]) -> Optional[str]:
    """Write a shipped custom/ beside the .kbh. The box's own custom/ wins:
    when one is there, the shipped one lands as custom.shipped/. Returns the
    folder written, or None when nothing was shipped."""
    if not files:
        return None
    into = os.path.abspath(os.path.expanduser(into))
    dest = os.path.join(into, FOLDER)
    if os.path.isdir(dest) and os.listdir(dest):
        dest = os.path.join(into, FOLDER + ".shipped")
    for rel, data in files:
        path = os.path.join(dest, *rel.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(data)
    return dest


def run_hooks(folder: Optional[str], stage: str, env: Dict[str, str], python: Optional[str] = None) -> List[str]:
    """Run custom/<stage>/*.py in name order with the install's python and
    KBH_* in the environment. Returns one line per hook. A failing hook stops
    the install (raises RuntimeError) - a half-run post_install is worse than
    none."""
    lines: List[str] = []
    if not folder:
        return lines
    stage_dir = os.path.join(folder, stage)
    if not os.path.isdir(stage_dir):
        return lines
    py = python or sys.executable
    for fname in sorted(os.listdir(stage_dir)):
        if not fname.endswith(".py"):
            continue
        path = os.path.join(stage_dir, fname)
        done = subprocess.run([py, path], env={**os.environ, **env}, capture_output=True, text=True, encoding="utf-8")
        tail = (done.stdout.strip().splitlines() or [""])[-1][:120]
        lines.append(f"{stage}/{fname}: {'ok' if done.returncode == 0 else f'exit {done.returncode}'}"
                     + (f" - {tail}" if tail else ""))
        if done.returncode != 0:
            raise RuntimeError(f"{stage}/{fname} failed (exit {done.returncode}): {(done.stderr or done.stdout).strip()[:300]}")
    return lines
