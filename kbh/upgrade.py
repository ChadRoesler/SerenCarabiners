"""
kbh.upgrade - `kbh upgrade --from NEW.kbh`: put a new .kbh where this one is,
and put this one back if the new one does not hold.

    python claude.kbh upgrade --from NEW.kbh [--sha256 HEX] [--config Y] [--into PATH] [--downgrade] [--json]

THE OLD ONE DOES IT. It is the file already trusted on this box, so it checks
the new one's sha256 before anything of the new one runs (its --version is the
first thing that does). A new file vouching for itself would vouch for
anything. Leave --sha256 off and the answer says nothing was checked.

    1. the hash, when given; then the zip: it must carry every carabiner this
       one carries (no codex.kbh dropped over a claude.kbh)
    2. belay, with this one, for each carabiner that has a yaml here
    3. this one kept as <file>.bak-<its version>; the new one swapped in whole
    4. belay again, with the new one
    5. anything that held in 2 and lets go in 4: the old one goes back

Step 5 compares, it does not demand a clean belay. A brain box that is down
lets go of the same checks before and after, and that is not the new build's
fault; a check only the new build has is reported, not held against it.

The swap happens under the running process, so everything this module needs
is imported before it: after step 3 nothing more is read from the zip.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import zipfile
from typing import Any, Dict, List, Optional, Tuple

from . import full_version

BELAY_TIMEOUT = 180


def _opt(argv: List[str], flag: str) -> Optional[str]:
    return argv[argv.index(flag) + 1] if flag in argv and argv.index(flag) + 1 < len(argv) else None


def sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 16), b""):
            h.update(block)
    return h.hexdigest()


def carried(path: str) -> List[str]:
    """The carabiners a .kbh carries, read from the zip without running it."""
    names = set()
    with zipfile.ZipFile(path) as zf:
        for n in zf.namelist():
            m = re.match(r"^kbh/carabiners/([A-Za-z0-9_]+)/__init__\.py$", n)
            if m and not m.group(1).startswith("_"):
                names.add(m.group(1))
    return sorted(names)


def version_of(path: str) -> str:
    """`kbh 5.1.3+6d5f1eb` -> '5.1.3+6d5f1eb'; '' when it will not say."""
    try:
        done = subprocess.run([sys.executable, path, "--version"], capture_output=True, text=True,
                              encoding="utf-8", timeout=60)
    except (OSError, subprocess.SubprocessError):
        return ""
    m = re.match(r"^kbh (\S+)", done.stdout.strip())
    return m.group(1) if done.returncode == 0 and m else ""


def _release(v: str) -> Tuple[int, ...]:
    return tuple(int(p) for p in re.findall(r"\d+", v.split("+", 1)[0])[:3])


def configs_for(target: str, names: List[str], explicit: Optional[str]) -> Dict[str, str]:
    """{carabiner: its yaml} for the carabiners set up on this box: --config
    (one carabiner), KBH_CONFIG, beside the .kbh, or ~/.seren/kbh."""
    one = len(names) == 1
    if explicit:
        return {names[0]: os.path.abspath(explicit)} if one else {}
    found = {}
    for n in names:
        candidates = [os.path.join(os.path.dirname(target), f"{n}.yaml"),
                      os.path.join(os.path.expanduser("~"), ".seren", "kbh", f"{n}.yaml")]
        if one and os.environ.get("KBH_CONFIG"):
            candidates.insert(0, os.environ["KBH_CONFIG"])
        here = next((c for c in candidates if os.path.isfile(c)), None)
        if here:
            found[n] = here
    return found


def belay_with(kbh_path: str, carabiner: str, yaml: str) -> Optional[Dict[str, Any]]:
    """`belay --json` with that file; None when it could not answer at all."""
    try:
        done = subprocess.run([sys.executable, kbh_path, carabiner, "belay", "--json", "--config", yaml],
                              capture_output=True, text=True, encoding="utf-8", timeout=BELAY_TIMEOUT)
        rep = json.loads(done.stdout)
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    return rep if isinstance(rep, dict) and isinstance(rep.get("checks"), list) else None


def _held(rep: Optional[Dict[str, Any]]) -> set:
    return {(c.get("verb"), c.get("name")) for c in (rep or {}).get("checks", []) if c.get("status") == "held"}


def _let_go(rep: Optional[Dict[str, Any]]) -> set:
    return {(c.get("verb"), c.get("name")) for c in (rep or {}).get("checks", []) if c.get("status") == "LET GO"}


def _swap_in(src: str, target: str) -> None:
    """src's bytes at target, whole or not at all. Windows refuses to replace
    a file something has open (a wake mid-start, a headersHelper): a few
    tries, then the error."""
    part = target + ".part"
    shutil.copyfile(src, part)
    try:
        shutil.copymode(target, part)
    except OSError:
        pass
    for attempt in range(10):
        try:
            os.replace(part, target)
            return
        except PermissionError:
            if attempt == 9:
                os.remove(part)
                raise
            time.sleep(0.5)


def upgrade(new: str, target: str, want_sha: str = "", explicit_config: Optional[str] = None,
            downgrade: bool = False) -> Dict[str, Any]:
    out: Dict[str, Any] = {"ok": False, "target": target, "from_file": new, "was": "", "now": "",
                           "sha256": "", "sha256_checked": False, "backup": "", "belay": {},
                           "rolled_back": False, "changed": False, "error": ""}
    if not os.path.isfile(new):
        out["error"] = f"no file at {new}"
        return out
    if not os.path.isfile(target):
        out["error"] = f"nothing to upgrade at {target}: install the carabiner first"
        return out
    got = sha256(new)
    out["sha256"] = got
    if want_sha:
        if got.lower() != want_sha.strip().lower():
            out["error"] = f"refused: {new} has sha256 {got}, not {want_sha.strip().lower()}; nothing of it was run"
            return out
        out["sha256_checked"] = True
    try:
        has, will = carried(target), carried(new)
    except zipfile.BadZipFile as e:
        out["error"] = f"refused: not a .kbh ({e})"
        return out
    missing = [n for n in has if n not in will]
    if missing:
        out["error"] = (f"refused: {os.path.basename(new)} does not carry {', '.join(missing)}, which "
                        f"{os.path.basename(target)} does")
        return out
    out["was"] = version_of(target)
    if got == sha256(target):
        out.update(ok=True, now=out["was"], error="")
        return out                                                    # already this build: nothing to do
    out["now"] = version_of(new)
    if not out["now"]:
        out["error"] = f"refused: {new} does not answer --version, so it does not run here"
        return out
    if out["was"] and _release(out["now"]) < _release(out["was"]) and not downgrade:
        out["error"] = f"refused: {out['now']} is older than {out['was']} (--downgrade if that is the point)"
        return out

    configs = configs_for(target, has, explicit_config)
    before = {n: belay_with(target, n, y) for n, y in configs.items()}

    stamp = re.sub(r"[^A-Za-z0-9._+-]", "_", out["was"] or time.strftime("unknown-%Y%m%d-%H%M%S"))
    backup = f"{target}.bak-{stamp}"
    try:
        shutil.copy2(target, backup)
        _swap_in(new, target)
    except OSError as e:
        out["error"] = f"{target} was left as it was: {type(e).__name__}: {e}"
        return out
    out.update(backup=backup, changed=True)

    regressed = False
    for n, y in configs.items():
        after = belay_with(target, n, y)
        lost = sorted(_held(before[n]) & _let_go(after)) if before[n] is not None else []
        broke = after is None and before[n] is not None              # the old one answered; the new one cannot
        new_let_go = sorted(_let_go(after) - _held(before[n]) - _let_go(before[n]))
        out["belay"][n] = {"config": y, "before_ok": None if before[n] is None else bool(before[n].get("ok")),
                           "after_ok": None if after is None else bool(after.get("ok")),
                           "lost": [f"{v} / {nm}" for v, nm in lost],
                           "new_let_go": [f"{v} / {nm}" for v, nm in new_let_go],
                           "after": (after or {}).get("checks", [])}
        if lost or broke:
            regressed = True
    if regressed:
        try:
            _swap_in(backup, target)
        except OSError as e:
            out["error"] = (f"the new build let go of what the old one held, and putting the old one back "
                            f"failed: {e}. The old one is at {backup}; copy it over {target} by hand.")
            return out
        out.update(rolled_back=True, changed=False,
                   error="the new build let go of what the old one held; the old one is back")
        return out
    out["ok"] = True
    return out


def this_kbh() -> Optional[str]:
    from .harness import self_command
    cmd = self_command()
    return cmd[1] if len(cmd) == 2 and os.path.isfile(cmd[1]) else None


def run(argv: List[str]) -> int:
    new = _opt(argv, "--from")
    target = _opt(argv, "--into") or this_kbh()
    if not new or not target:
        print("usage: python <installed>.kbh upgrade --from NEW.kbh [--sha256 HEX] [--config Y] [--into PATH] "
              "[--downgrade] [--json]\n(run it with the .kbh being replaced, or name that file with --into)",
              file=sys.stderr)
        return 64
    by = full_version()                                               # read now: after the swap the zip is another
    res = upgrade(os.path.abspath(os.path.expanduser(new)), os.path.abspath(os.path.expanduser(target)),
                  _opt(argv, "--sha256") or "", _opt(argv, "--config"), "--downgrade" in argv)
    res["by"] = by
    if "--json" in argv:
        print(json.dumps(res, indent=2))
    else:
        _say(res)
    return 0 if res["ok"] else (2 if res["error"].startswith("refused") else 1)


def _say(res: Dict[str, Any]) -> None:
    if res["ok"] and not res["changed"]:
        print(f"{res['target']} is already {res['now'] or 'that build'}; nothing to do")
        return
    if res["ok"]:
        print(f"upgraded {res['target']}: {res['was'] or '?'} -> {res['now']}")
        print(f"  the old one is at {res['backup']}")
    else:
        print(res["error"], file=sys.stderr)
    if not res["sha256_checked"] and res["sha256"]:
        print(f"  sha256 {res['sha256']} (not checked: no --sha256 given)")
    for n, b in res["belay"].items():
        state = "held" if b["after_ok"] else ("could not run" if b["after_ok"] is None else "let go")
        print(f"  belay {n}: {state}")
        for line in b["lost"]:
            print(f"    lost:  {line} (held before)")
        for line in b["new_let_go"]:
            print(f"    new:   {line} lets go (a check the old build did not run, or that did not answer before)")
    if res["changed"] and not res["belay"]:
        print("  no yaml here for its carabiners, so no belay ran; kbh <carabiner> belay when there is one")
