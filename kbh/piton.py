"""
kbh.piton - the pages at the door, kept on the box (PITON.md).

The dedication (written by the model to its other sessions) and the preface
(written to the room) used to live in Margin, the one piece whose promise is
"don't install me and I leave no trace". They are written to be read, so they
moved out: into a folder beside the carabiners, one per box, shared by every
carabiner on it. Not a service. Files, made by install, read and written by
the kbh already on the box (16 Nov 2026).

    ~/.seren/piton/
    ├─ piton.yaml               the options: who writes each page, the caps
    ├─ dedication.md            the page as it is now
    ├─ preface.md
    └─ history/<page>/0001.md   every version, front matter then the text

This module is the shared core: finding the folder, making what is missing,
the options, reading and writing with history, recording a hand edit, falling
back to the last good version. It is here and not in a carabiner so that two
carabiners of different ages on one box can never disagree about the format.
Each carabiner does only the LOADING (how its harness gets the pages in).

THE RULES, each one a promise PITON.md makes:

  - make() fills in what is missing, file by file, and never touches a file
    that is there.
  - piton.yaml: unknown keys are ignored; a missing key takes its default
    when read and is never written back. A newer kbh adds an option without
    rewriting anyone's file.
  - A write goes to history/ first, then replaces the page through a temp
    file, so a crash leaves the old page whole. The same text as now is not
    a new version (Margin's rule).
  - A page edited by hand (in Notepad, say) is recorded as a version of its
    own the next time it is read, `by: hand`. Nothing is lost to Notepad.
  - A page that cannot be read, or is over its cap, never breaks a session:
    read() hands back the newest good version and one line saying what was
    wrong.
  - Who writes a page (`self`, `operator`, `off`) is a promise the verbs
    keep, not a lock: the files are plain text on a disk the operator owns,
    and that visibility is half the point.
  - BUT A FAT FINGER IS NOT A CHOICE (16 Nov 2026: "if i look at it, and fat
    finger ... i dont want to potentially trash or fuck something up"). A page
    the operator does not write (`self`, `off`) is read only on disk, and
    every history file is: Notepad can open it and cannot save over it. The
    verbs unlock, write and lock again. Taking the read-only mark off by hand
    is a deliberate act, and what is saved then is recorded as a hand edit.
    `restore` brings an old version back as a new one, so even an undo can
    be undone. (Not a lock against root, which writes through anything.)

Standard library only; PyYAML is used for piton.yaml when it is there.
"""
from __future__ import annotations

import json
import os
import re
import stat
import sys
import tempfile
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from .config import _scalar, read_yaml

SCHEMA = 1
ENV = "KBH_PITON"
DEFAULT_DIR = os.path.join("~", ".seren", "piton")
PAGES = ("dedication", "preface")
WRITERS = ("self", "operator", "off")
# Who a version came from. The first two are the writers the options name;
# the rest are records of what happened (a hand edit found on read, the
# one-time import from Margin, a version pulled from the Workbench), never
# refused, because refusing them would only lose a version.
BY = ("self", "operator", "hand", "margin", "pull")
DEFAULTS: Dict[str, Any] = {
    "schema": SCHEMA,
    "dedication": "self",
    "preface": "operator",
    # The dedication cap is the context budget every session pays at the door. 3000
    # since 17 Nov 2026: Margin's 2000 was already 253 under the real v6. The box owns
    # this number; the Workbench only stops runaway writes (8000), so the two never drift.
    "caps": {"dedication": 3000, "preface": 8000},
}
CAP_MAX = 64 * 1024
_VERSION_FILE = re.compile(r"^(\d+)\.md$")

YAML_TEMPLATE = """\
# piton.yaml - the pages at the door, shared by every carabiner on this box.
# The pages themselves are dedication.md and preface.md beside this file;
# every version of each is kept in history/.
schema: 1
# Who writes each page: self (the model), operator (you), or off (not shown).
dedication: self
preface: operator
caps:                     # characters
  dedication: 3000
  preface: 8000
"""


def locate(explicit: str = "", configured: str = "", base: str = "") -> str:
    """The piton folder: --piton, then KBH_PITON, then the carabiner yaml's
    `piton:` (relative to `base`, the yaml's folder), then ~/.seren/piton."""
    for value, rel in ((explicit, ""), (os.environ.get(ENV, ""), ""), (configured, base)):
        value = (value or "").strip()
        if value:
            path = os.path.expanduser(value)
            if rel and not os.path.isabs(path):
                path = os.path.join(rel, path)
            return os.path.abspath(path)
    return os.path.abspath(os.path.expanduser(DEFAULT_DIR))


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _epoch(value: Any) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return datetime.strptime(str(value), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp()
    except ValueError:
        return 0.0


def _clean(text: Any) -> str:
    """A page's text as it is compared and kept: no surrounding blank space,
    LF line endings (a page saved on Windows is the same page)."""
    return str(text or "").replace("\r\n", "\n").replace("\r", "\n").strip()


def _set_locked(path: str, locked: bool) -> None:
    """Read only (no write bit for anyone), or writable by its owner. On
    Windows this is the file's read-only attribute. Never raises."""
    try:
        mode = os.stat(path).st_mode
        new = (mode & ~(stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH)) if locked else (mode | stat.S_IWUSR)
        if new != mode:
            os.chmod(path, new)
    except OSError:
        pass


def is_locked(path: str) -> bool:
    try:
        return not (os.stat(path).st_mode & stat.S_IWUSR)
    except OSError:
        return False


def _locks(writer: str) -> bool:
    """Whether a page with this writer is read only on disk: the model's own
    page, and a page nobody writes. The operator's page is theirs to edit."""
    return writer in ("self", "off")


def _write_atomic(path: str, text: str) -> None:
    folder = os.path.dirname(path)
    fd, tmp = tempfile.mkstemp(prefix=".piton-", dir=folder)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


class PitonError(Exception):
    """A write that was refused: over the cap, empty, or not this writer's page."""


class Piton:
    def __init__(self, root: str):
        self.root = os.path.abspath(os.path.expanduser(root))

    # ── where things are ──
    @property
    def yaml_path(self) -> str:
        return os.path.join(self.root, "piton.yaml")

    def page_path(self, page: str) -> str:
        _check_page(page)
        return os.path.join(self.root, f"{page}.md")

    def history_dir(self, page: str) -> str:
        _check_page(page)
        return os.path.join(self.root, "history", page)

    # ── making it ──
    def make(self) -> List[str]:
        """Fill in whatever is missing, file by file; never touch what is
        there. Returns what was created (paths), so install can say so and
        knows whether a page is new (the one-time import from Margin)."""
        created: List[str] = []
        if not os.path.isdir(self.root):
            os.makedirs(self.root, exist_ok=True)
            created.append(self.root)
        if not os.path.exists(self.yaml_path):
            with open(self.yaml_path, "x", encoding="utf-8", newline="\n") as f:
                f.write(YAML_TEMPLATE)
            created.append(self.yaml_path)
        for page in PAGES:
            hist = self.history_dir(page)
            if not os.path.isdir(hist):
                os.makedirs(hist, exist_ok=True)
                created.append(hist)
            path = self.page_path(page)
            if not os.path.exists(path):
                with open(path, "x", encoding="utf-8", newline="\n") as f:
                    f.write("")
                created.append(path)
        self.apply_locks()
        return created

    def apply_locks(self, opts: Optional[Dict[str, Any]] = None) -> None:
        """Each page read only or writable by who writes it (piton.yaml). Run
        on make and on every read, so a writer changed in piton.yaml (or the
        form) takes effect at the next session without anyone remembering."""
        opts = opts if opts is not None else self.options()[0]
        for page in PAGES:
            path = self.page_path(page)
            if os.path.exists(path):
                _set_locked(path, _locks(opts[page]))

    def exists(self) -> bool:
        return os.path.isdir(self.root)

    # ── the options ──
    def options(self) -> Tuple[Dict[str, Any], List[str]]:
        """(the options, problems). Defaults fill whatever is missing or not
        understood; unknown keys are ignored; nothing is written back."""
        problems: List[str] = []
        data: Dict[str, Any] = {}
        if os.path.exists(self.yaml_path):
            try:
                data = read_yaml(self.yaml_path)
            except Exception as e:  # noqa: BLE001 - a bad file is defaults and a line, never a crash
                problems.append(f"piton.yaml does not read ({type(e).__name__}); using the defaults")
                data = {}
        out: Dict[str, Any] = {"schema": data.get("schema", SCHEMA)}
        for page in PAGES:
            raw = data.get(page, DEFAULTS[page])
            # YAML 1.1 (PyYAML, and kbh's own reader) reads a bare `off` as
            # False: the word the comment tells a person to type has to work.
            v = "off" if raw is False else str(raw if raw is not None else "").strip().lower()
            if v not in WRITERS:
                problems.append(f"piton.yaml: {page}: {v!r} is not one of {', '.join(WRITERS)}; "
                                f"using {DEFAULTS[page]}")
                v = DEFAULTS[page]
            out[page] = v
        caps_in = data.get("caps") if isinstance(data.get("caps"), dict) else {}
        caps: Dict[str, int] = {}
        for page in PAGES:
            raw = caps_in.get(page, DEFAULTS["caps"][page])
            try:
                n = int(raw)
                if not 1 <= n <= CAP_MAX:
                    raise ValueError
            except (TypeError, ValueError):
                problems.append(f"piton.yaml: caps.{page}: {raw!r} is not a number from 1 to {CAP_MAX}; "
                                f"using {DEFAULTS['caps'][page]}")
                n = DEFAULTS["caps"][page]
            caps[page] = n
        out["caps"] = caps
        return out, problems

    # ── history ──
    def _version_files(self, page: str) -> List[Tuple[int, str]]:
        hist = self.history_dir(page)
        try:
            names = os.listdir(hist)
        except OSError:
            return []
        found = [(int(m.group(1)), os.path.join(hist, n)) for n in names if (m := _VERSION_FILE.match(n))]
        return sorted(found)

    def _read_version(self, number: int, path: str) -> Optional[Dict[str, Any]]:
        try:
            raw = open(path, encoding="utf-8").read()
        except (OSError, UnicodeDecodeError):
            return None
        raw = raw.replace("\r\n", "\n")
        meta: Dict[str, Any] = {}
        body = raw
        if raw.startswith("---\n"):
            head, sep, rest = raw[4:].partition("\n---\n")
            if sep:
                body = rest
                for line in head.splitlines():
                    k, s, v = line.partition(":")
                    if s:
                        meta[k.strip()] = _scalar(v)
        return {"version": number, "text": _clean(body), "set_at": _epoch(meta.get("set_at")),
                "why": (str(meta["why"]) if meta.get("why") not in (None, "") else None),
                "by": str(meta.get("by") or "") or None}

    def history(self, page: str, limit: int = 10) -> List[Dict[str, Any]]:
        """The newest `limit` versions, newest first; a version file that does
        not read is skipped."""
        out: List[Dict[str, Any]] = []
        for number, path in reversed(self._version_files(page)):
            entry = self._read_version(number, path)
            if entry is not None:
                out.append(entry)
                if len(out) >= limit:
                    break
        return out

    def latest(self, page: str) -> Optional[Dict[str, Any]]:
        h = self.history(page, limit=1)
        return h[0] if h else None

    def _append_version(self, page: str, text: str, why: Optional[str], by: str,
                        set_at: Optional[float] = None) -> Dict[str, Any]:
        """Write the next history/<page>/NNNN.md, never overwriting one (two
        writers at once each get their own number)."""
        hist = self.history_dir(page)
        os.makedirs(hist, exist_ok=True)
        ts = time.time() if set_at is None else float(set_at)
        why = (why or "").strip()[:500] or None
        files = self._version_files(page)
        number = (files[-1][0] + 1) if files else 1
        for _ in range(100):
            lines = ["---", f"version: {number}", f"set_at: {_iso(ts)}"]
            if why:
                lines.append(f"why: {json.dumps(why, ensure_ascii=False)}")
            lines += [f"by: {by}", "---", text, ""]
            path = os.path.join(hist, f"{number:04d}.md")
            try:
                with open(path, "x", encoding="utf-8", newline="\n") as f:
                    f.write("\n".join(lines))
                _set_locked(path, True)                 # the safety net is never fat-fingered
                return {"version": number, "text": text, "set_at": ts, "why": why, "by": by}
            except FileExistsError:
                number += 1
        raise PitonError(f"could not find a free version number in {hist}")

    # ── reading ──
    def read(self, page: str) -> Dict[str, Any]:
        """The page as a session should see it:

            {page, text, version, set_at, why, by, writer, problems}

        `text` is "" when there is nothing to show (nothing written, or the
        writer is `off`). A page edited by hand is recorded as a version here.
        A page that cannot be read or is over its cap gives the newest good
        version, and a problem line saying so. Never raises for a bad file."""
        _check_page(page)
        opts, problems = self.options()
        writer = opts[page]
        cap = opts["caps"][page]
        self.apply_locks(opts)
        out: Dict[str, Any] = {"page": page, "text": "", "version": None, "set_at": None, "why": None,
                               "by": None, "writer": writer, "problems": problems}
        if writer == "off":
            return out
        latest = self.latest(page)
        path = self.page_path(page)
        bad = ""
        text = ""
        try:
            text = _clean(open(path, encoding="utf-8").read())
        except FileNotFoundError:
            text = ""
        except (OSError, UnicodeDecodeError) as e:
            bad = f"{page}.md does not read ({type(e).__name__})"
        if not bad and len(text) > cap:
            bad = f"{page}.md is {len(text)} characters, over its cap of {cap}"
        if not bad and not text and latest is not None:
            bad = f"{page}.md is empty"
        if bad:
            if latest is not None:
                problems.append(f"{bad}; showing version {latest['version']} from history")
                out.update({k: latest[k] for k in ("text", "version", "set_at", "why", "by")})
            else:
                problems.append(bad)
            return out
        if not text:
            return out
        if latest is None or latest["text"] != text:
            # Edited by hand since the last version (or written before there
            # was a history): it becomes a version of its own.
            try:
                latest = self._append_version(page, text, "edited by hand", "hand")
            except (OSError, PitonError) as e:
                problems.append(f"{page}.md changed by hand but history/ could not take it "
                                f"({type(e).__name__}); shown as it is")
                out.update({"text": text, "by": "hand"})
                return out
        out.update({k: latest[k] for k in ("text", "version", "set_at", "why", "by")})
        return out

    # ── writing ──
    def may_write(self, page: str, by: str) -> Tuple[bool, str]:
        """Whether `by` may write `page`, and why not. Only `self` and
        `operator` are checked; the other sources are records."""
        _check_page(page)
        if by not in BY:
            return False, f"{by!r} is not one of {', '.join(BY)}"
        if by not in ("self", "operator"):
            return True, ""
        opts, _ = self.options()
        writer = opts[page]
        if writer == "off":
            return False, f"the {page} is off on this box (piton.yaml); nobody writes it"
        if writer != by:
            whose = "the model's own page" if writer == "self" else "written by the operator"
            return False, f"the {page} is {whose} on this box (piton.yaml: {page}: {writer})"
        return True, ""

    def set(self, page: str, text: str, why: Optional[str] = None, by: str = "self",
            set_at: Optional[float] = None) -> Tuple[Dict[str, Any], bool]:
        """A new version of `page`: history first, then the page. Returns
        (the version, whether it changed). The same text as now is not a new
        version. Raises PitonError when refused."""
        ok, reason = self.may_write(page, by)
        if not ok:
            raise PitonError(reason)
        text = _clean(text)
        if not text:
            raise PitonError(f"the {page} must not be empty")
        opts, _ = self.options()
        cap = opts["caps"][page]
        if len(text) > cap:
            raise PitonError(f"{len(text)} characters; the {page} is capped at {cap}")
        self.make()
        # A hand edit waiting on disk is recorded before it is replaced.
        self.read(page)
        latest = self.latest(page)
        if latest is not None and latest["text"] == text:
            self._sync_page(page, text)
            return latest, False
        entry = self._append_version(page, text, why, by, set_at)
        self._sync_page(page, text)
        return entry, True

    def restore(self, page: str, version: int, by: str = "self",
                why: Optional[str] = None) -> Tuple[Dict[str, Any], bool]:
        """Bring version N back as a NEW version (so the restore is itself in
        history, and can be undone the same way)."""
        for number, path in self._version_files(page):
            if number == int(version):
                old = self._read_version(number, path)
                if old is None:
                    raise PitonError(f"version {version} of the {page} does not read")
                return self.set(page, old["text"], why=why or f"restored version {number}", by=by)
        raise PitonError(f"the {page} has no version {version}")

    def _sync_page(self, page: str, text: str) -> None:
        path = self.page_path(page)
        try:
            if _clean(open(path, encoding="utf-8").read()) == text:
                return
        except (OSError, UnicodeDecodeError):
            pass
        _set_locked(path, False)                       # a read-only target cannot be replaced on Windows
        try:
            _write_atomic(path, text + "\n")
        finally:
            self.apply_locks()


def _check_page(page: str) -> None:
    if page not in PAGES:
        raise ValueError(f"no page called {page!r}: one of {', '.join(PAGES)}")


# ── the verb: kbh <carabiner> piton ...  ─────────────────────────────────────

USAGE = """\
usage: kbh {c} piton                                   where it is, who writes what, each page's version
       kbh {c} piton show dedication|preface [--history N] [--json]
       kbh {c} piton set dedication|preface [--why TEXT] [--file PATH] [--as self|operator]
                                              (the page from --file, else stdin)
       kbh {c} piton restore dedication|preface N [--why TEXT] [--as self|operator]
       kbh {c} piton import [--from CONNECTION]      take both pages over from Margin with every
                                              version, once (a page the piton has is never touched)
   --piton DIR and --config PATH as everywhere; --json on the bare form too."""

# Set in the environment of a command run from inside a harness session: the
# model is at the keyboard. Claude Code sets CLAUDECODE=1 for what it runs;
# a woken session has SEREN_KBH_WAKE. KBH_AS says it outright.
SESSION_ENV = ("CLAUDECODE", "SEREN_KBH_WAKE")
WHO = {"self": "the model", "operator": "you", "off": "nobody"}
_VALUE_FLAGS = ("--why", "--file", "--as", "--history", "--piton", "--config", "--from")


def who_is_writing(argv: List[str]) -> str:
    """--as, else KBH_AS, else `self` inside a harness session, else `operator`."""
    if "--as" in argv and argv.index("--as") + 1 < len(argv):
        return argv[argv.index("--as") + 1].strip().lower()
    if os.environ.get("KBH_AS"):
        return os.environ["KBH_AS"].strip().lower()
    return "self" if any(os.environ.get(v) for v in SESSION_ENV) else "operator"


def age(ts: Optional[float]) -> str:
    if not ts:
        return ""
    s = max(0, int(time.time() - ts))
    for size, unit in ((86400 * 7, "week"), (86400, "day"), (3600, "hour"), (60, "minute")):
        if s >= size:
            n = s // size
            return f"{n} {unit}{'s' if n != 1 else ''} ago"
    return "just now"


def _opt(argv: List[str], flag: str, default: str = "") -> str:
    return argv[argv.index(flag) + 1] if flag in argv and argv.index(flag) + 1 < len(argv) else default


def root_for(carabiner_name: str, argv: List[str]) -> Tuple[str, bool]:
    """(the piton folder for this command, whether a yaml, a flag or the
    environment named it)."""
    from .config import load_for
    explicit = _opt(argv, "--piton")
    try:
        cfg = load_for(carabiner_name, argv)
    except OSError:
        cfg = None
    if cfg is not None:
        return cfg.piton_dir(explicit), bool(explicit or cfg.piton or os.environ.get(ENV))
    return locate(explicit=explicit), bool(explicit or os.environ.get(ENV))


def summary(p: Piton) -> Dict[str, Any]:
    """Where it is, the options, and each page's state: what `piton` prints
    and what a form reads (--json)."""
    opts, problems = p.options()
    pages: Dict[str, Any] = {}
    for page in PAGES:
        r = p.read(page)
        problems += [x for x in r["problems"] if x not in problems]
        pages[page] = {"writer": opts[page], "version": r["version"], "set_at": r["set_at"], "why": r["why"],
                       "by": r["by"], "chars": len(r["text"]), "cap": opts["caps"][page],
                       "locked": is_locked(p.page_path(page))}
    return {"root": p.root, "exists": p.exists(), "options": opts, "pages": pages, "problems": problems}


def run(carabiner: Any, argv: List[str]) -> int:
    name = getattr(carabiner, "name", "<carabiner>")
    args = [a for i, a in enumerate(argv)
            if not a.startswith("--") and (i == 0 or argv[i - 1] not in _VALUE_FLAGS)]
    sub = args[0] if args else ""
    root, _ = root_for(name, argv)
    p = Piton(root)
    as_json = "--json" in argv

    if sub in ("", "status"):
        if not p.exists():
            print(f"no piton at {root}: kbh {name} install makes one", file=sys.stderr)
            return 1
        s = summary(p)
        if as_json:
            print(json.dumps(s, indent=2))
            return 0
        print(f"piton: {root}  (shared by every carabiner on this box)")
        for page, info in s["pages"].items():
            if info["writer"] == "off":
                state = "not shown"
            elif info["version"]:
                state = f"version {info['version']}, set {age(info['set_at'])}" + (
                    f" ({info['why']})" if info["why"] else "")
            else:
                state = "nothing written yet"
            lock = "  read only" if info["locked"] else ""
            print(f"  {page:10s}  written by {WHO[info['writer']]:9s}  {state}{lock}")
        for line in s["problems"]:
            print(f"  ! {line}")
        return 0

    if sub == "import":
        from .config import load_for
        from .door import import_from_margin
        connection = _opt(argv, "--from")
        if not connection:
            try:
                cfg = load_for(name, argv)
            except OSError:
                cfg = None
            connection = cfg.connection(cfg.bookmark) if cfg is not None and cfg.bookmark else ""
        if not connection:
            print(f"kbh {name} piton import: no Margin to take the pages from (no `bookmark:` in the config; "
                  f"--from CONNECTION names one)", file=sys.stderr)
            return 64
        lines, ok = import_from_margin(p, connection, name)
        print("\n".join(lines), file=sys.stdout if ok else sys.stderr)
        return 0 if ok else 1

    if sub not in ("show", "set", "restore") or len(args) < 2 or args[1] not in PAGES:
        print(USAGE.format(c=name), file=sys.stderr)
        return 64
    page = args[1]

    if sub == "show":
        r = p.read(page)
        try:
            n = int(_opt(argv, "--history", "0") or 0)
        except ValueError:
            n = 0
        hist = p.history(page, n) if n > 0 else []
        if as_json:
            print(json.dumps({**r, "history": hist}, indent=2))
            return 0
        for line in r["problems"]:
            print(f"! {line}", file=sys.stderr)
        print(r["text"] if r["text"] else
              f"(no {page} {'shown: it is off' if r['writer'] == 'off' else 'written yet'})")
        for v in hist:
            print(f"\n--- version {v['version']}, {age(v['set_at'])}, by {v['by'] or '?'}"
                  + (f": {v['why']}" if v["why"] else "") + f" ---\n{v['text']}")
        return 0

    by = who_is_writing(argv)
    if by not in ("self", "operator"):
        print(f"--as takes self or operator, not {by!r}", file=sys.stderr)
        return 64
    why = _opt(argv, "--why") or None
    try:
        if sub == "set":
            src = _opt(argv, "--file")
            if src:
                text = open(os.path.expanduser(src), encoding="utf-8-sig").read()
            elif sys.stdin is None or sys.stdin.isatty():
                print(f"kbh {name} piton set {page}: the page comes from --file PATH or stdin", file=sys.stderr)
                return 64
            else:
                text = sys.stdin.buffer.read().decode("utf-8-sig")
            entry, changed = p.set(page, text, why=why, by=by)
        else:
            if len(args) < 3 or not args[2].isdigit():
                print(USAGE.format(c=name), file=sys.stderr)
                return 64
            entry, changed = p.restore(page, int(args[2]), by=by, why=why)
    except PitonError as e:
        msg = str(e)
        other = "operator" if by == "self" else "self"
        hint = f" - if that is wrong about who you are, --as {other}" if "on this box (piton.yaml" in msg else ""
        print(f"kbh {name} piton {sub} {page}: {msg}{hint}", file=sys.stderr)
        return 1
    except OSError as e:
        print(f"kbh {name} piton {sub} {page}: {type(e).__name__}: {e}", file=sys.stderr)
        return 1
    if as_json:
        print(json.dumps({"ok": True, "page": page, "version": entry["version"], "changed": changed}))
    else:
        print(f"{page}: version {entry['version']}" + ("" if changed else " (the same text as now; nothing new)"))
    return 0


# ── belay: does the piton hold? ──────────────────────────────────────────────

def belay_checks(carabiner_name: str, argv: List[str]) -> list:
    """The piton's lines in `kbh <c> belay`. A box that has never had a piton
    (installed before there was one) is skipped with how to make one, not let
    go: belay is not the place an old box first falls off the wall. A piton a
    yaml names that is not there IS let go."""
    from .belay import held, let_go, skipped
    root, named = root_for(carabiner_name, argv)
    p = Piton(root)

    def piton_folder():
        if p.exists() and os.path.isfile(p.yaml_path):
            return held("piton", "on belay?", "folder", root)
        if not named and not p.exists():
            return skipped("piton", "on belay?", "folder",
                           f"no piton on this box yet: kbh {carabiner_name} install makes one at {root}")
        return let_go("piton", "on belay?", "folder",
                      f"no piton at {root}: kbh {carabiner_name} install fills in what is missing")

    def piton_options():
        if not p.exists():
            return skipped("piton", "on belay?", "piton.yaml", "no piton")
        opts, problems = p.options()
        if problems:
            return let_go("piton", "on belay?", "piton.yaml", "; ".join(problems))
        return held("piton", "on belay?", "piton.yaml", ", ".join(f"{pg}: {WHO[opts[pg]]}" for pg in PAGES))

    def page_check(page: str):
        def check():
            if not p.exists():
                return skipped("piton", "on belay?", page, "no piton")
            r = p.read(page)
            if r["problems"]:
                return let_go("piton", "on belay?", page, "; ".join(r["problems"]))
            if r["writer"] == "off":
                return held("piton", "on belay?", page, "off: not shown")
            if not r["version"]:
                return held("piton", "on belay?", page, "nothing written yet")
            return held("piton", "on belay?", page, f"version {r['version']}, {len(r['text'])} characters")
        check.__name__ = f"piton_{page}"
        return check

    def piton_history():
        if not p.exists():
            return skipped("piton", "on belay?", "history", "no piton")
        for page in PAGES:
            d = p.history_dir(page)
            try:
                fd, tmp = tempfile.mkstemp(prefix=".belay-", dir=d)
                os.close(fd)
                os.unlink(tmp)
            except OSError as e:
                return let_go("piton", "on belay?", "history", f"{d} cannot be written: {type(e).__name__}: {e}")
        return held("piton", "on belay?", "history", "every version can be kept")

    return [piton_folder, piton_options] + [page_check(pg) for pg in PAGES] + [piton_history]
