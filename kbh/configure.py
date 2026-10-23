"""
kbh.configure - `kbh <carabiner> config`: read and change the settings a
carabiner says it has (kbh.schema), in its yaml beside the .kbh.

    kbh <c> config [show] [--json]          every setting, its value, what it means
    kbh <c> config get KEY
    kbh <c> config set KEY=VALUE ... [--expert] [--json]
    kbh <c> config unset KEY ... [--json]
    kbh <c> config apply                    a change as JSON, answered as JSON

`apply` is what the box's Observatory runs for Lodestar's Rack: the request
({"values": {...}, "unset": [...], "expert": false}, the shape of
seren_sinew.carabiners.SettingsRequest) comes in KBH_SETTINGS_REQUEST, or on
stdin when that is unset, because a process started in another person's
Windows session gets no stdin. The answer is one JSON object on stdout.

A change is all or nothing: one refused value and nothing is written, each
refusal with the carabiner's reason, so a form with one bad field never half
lands. After a write, belay runs and its lines ride in the answer: the yaml
changed, and whether the carabiner still holds is part of the answer.
Tokens never pass through here (kbh.schema says why), and `show` names how a
connection's token is kept, never the token.
"""
from __future__ import annotations

import json
import os
import sys
from typing import Any, Dict, List, Optional

from . import belay, full_version, config, schema, yamledit

REQUEST_ENV = "KBH_SETTINGS_REQUEST"
SUBCOMMANDS = ("show", "get", "set", "unset", "apply")


def _opt(argv: List[str], flag: str) -> Optional[str]:
    return argv[argv.index(flag) + 1] if flag in argv and argv.index(flag) + 1 < len(argv) else None


def _token_kind(route: Any) -> str:
    if not isinstance(route, dict):
        return "file" if route else "none"
    for key, kind in (("bearer_token", "inline"), ("bearer_token_env", "env"), ("bearer_token_keyring", "keyring")):
        if route.get(key):
            return kind
    return "none"


def _where(route: Any) -> str:
    if isinstance(route, dict):
        return str(route.get("url") or f"{route.get('host', '')}:{route.get('port', '')}".strip(":"))
    return str(route or "")


def manifest(c, cfg: config.HarnessConfig) -> Dict[str, Any]:
    """What the Rack draws: every setting with its value now. A note's value
    is its file's text (the package default while the yaml names none)."""
    data = config.read_yaml(cfg.path)
    fields = []
    for f in c.settings_fields(cfg, discover=True):
        d = f.to_dict()
        if f.kind == "note":
            d["value"] = _note_text(c, cfg)
        else:
            d["value"] = schema.current(f, data)
        fields.append(d)
    connections = [{"name": name, "where": _where(route), "token": _token_kind(route)}
                   for name, route in cfg.servers.items()]
    if cfg.bookmark:
        connections.append({"name": "bookmark", "where": _where(cfg.bookmark), "token": _token_kind(cfg.bookmark)})
    return {"ok": True, "carabiner": c.name, "display": c.display, "version": full_version(), "config": cfg.path,
            "fields": fields, "connections": connections}


def _note_text(c, cfg: config.HarnessConfig) -> str:
    path = cfg.framing_path()
    if path and os.path.isfile(path):
        with open(path, encoding="utf-8") as f:
            return f.read()
    return c.default_framing()


def _belay_lines(c, path: str) -> Dict[str, Any]:
    argv = ["--config", path]
    checks = list(c.belay_checks(argv))
    if c.custom is not None:
        checks += c.custom.checks(c, argv)
    rep = belay.run(c.name, checks)
    lines = [{"check": f"{k.verb} / {k.name}", "ok": bool(k.held), "said": k.why}
             for k in rep.checks if k.held is not None]
    return {"belay_ok": rep.ok, "belay": lines}


def change(c, cfg: config.HarnessConfig, values: Dict[str, Any], unset: List[str],
           expert: bool = False, run_belay: bool = True) -> Dict[str, Any]:
    """Check every value against the schema, then write them all or none."""
    fields = {f.key: f for f in c.settings_fields(cfg)}
    refused: Dict[str, str] = {}
    clean: Dict[str, Any] = {}
    for key, value in (values or {}).items():
        f = fields.get(key)
        if f is None:
            refused[key] = f"not a setting the {c.display} carabiner has"
            continue
        v, why = schema.validate(f, value, expert)
        if why:
            refused[key] = why
        else:
            clean[key] = v
    for key in unset or []:
        if key not in fields:
            refused[key] = f"not a setting the {c.display} carabiner has"
        elif key in clean:
            refused[key] = "both set and unset in one change"
        elif fields[key].required:
            refused[key] = "has no default to go back to; set it to something else instead"
    out: Dict[str, Any] = {"ok": False, "carabiner": c.name, "config": cfg.path, "applied": [],
                           "refused": refused, "applies": {}, "belay_ok": None, "belay": [], "error": ""}
    if refused:
        out["error"] = "nothing was written: " + "; ".join(f"{k}: {why}" for k, why in refused.items())
        return out

    with open(cfg.path, encoding="utf-8") as fh:
        text = fh.read()
    notes: Dict[str, str] = {}
    try:
        for key, v in clean.items():
            if fields[key].kind == "note":
                notes[key] = v
            else:
                text = yamledit.set(text, key, v)
        for key in unset or []:
            text = yamledit.unset(text, key)
    except ValueError as e:
        out["error"] = f"nothing was written: {e}"
        return out
    if notes and not cfg.framing:                     # the package default until now: a file of its own from here on
        text = yamledit.set(text, "framing", "framing.md")
    # The note first, then the yaml: a note that cannot be written leaves the
    # yaml as it was, and a yaml that cannot be written after a note did says
    # so plainly instead of claiming nothing changed.
    note_path = cfg.framing_path() or os.path.join(cfg.folder, "framing.md")
    wrote_note = False
    try:
        for note in notes.values():
            yamledit.write(note_path, note)
            wrote_note = True
        yamledit.write(cfg.path, text)
    except OSError as e:
        out["error"] = (f"the wake note was written to {note_path} but {cfg.path} could not be: {e}" if wrote_note
                        else f"nothing was written: {e}")
        return out

    applied = list(clean) + list(unset or [])
    out.update(ok=True, applied=applied, applies={k: fields[k].applies for k in applied})
    if run_belay:
        out.update(_belay_lines(c, cfg.path))
    return out


def run(c, argv: List[str]) -> int:
    # Flags may come anywhere (`config --config X apply` as well as
    # `config apply --config X`): the subcommand is the first word that is
    # neither a flag nor --config's value.
    rest = argv
    words = [a for i, a in enumerate(rest) if not a.startswith("--") and (i == 0 or rest[i - 1] != "--config")]
    sub = words.pop(0) if words else "show"
    as_json = sub == "apply" or "--json" in rest

    def fail(msg: str) -> int:
        if as_json:
            print(json.dumps({"ok": False, "carabiner": c.name, "error": msg}))
        else:
            print(msg, file=sys.stderr)
        return 1

    if sub not in SUBCOMMANDS:
        return fail(f"usage: kbh {c.name} config [{'|'.join(SUBCOMMANDS)}] ... (not '{sub}')")
    path = config.find(c.name, _opt(rest, "--config"))
    if not path or not os.path.isfile(path):
        return fail(f"no {c.name}.yaml on this box ({path or 'looked beside the .kbh and in ~/.seren/kbh'}); "
                    f"install the carabiner first")
    try:
        cfg = config.load(path)
    except Exception as e:  # noqa: BLE001 - a yaml that will not parse is an answer, not a traceback
        return fail(f"{path} cannot be read: {type(e).__name__}: {e}")

    if sub == "show":
        m = manifest(c, cfg)
        if "--json" in rest:
            print(json.dumps(m, indent=2))
            return 0
        print(f"{c.display} on this box ({cfg.path})")
        for f in m["fields"]:
            value = f["value"]
            shown = f"{len(value.splitlines())} lines" if f["kind"] == "note" else (
                ", ".join(value) if isinstance(value, list) else ("" if value is None else str(value)))
            print(f"  {f['key']:28s} {shown or '(not set)'}    {f['label']}")
        for conn in m["connections"]:
            print(f"  connection {conn['name']}: {conn['where']} (token: {conn['token']})")
        return 0

    if sub == "get":
        if len(words) != 1:
            print(f"usage: kbh {c.name} config get KEY", file=sys.stderr)
            return 64
        f = next((x for x in c.settings_fields(cfg) if x.key == words[0]), None)
        if f is None:
            print(f"not a setting the {c.display} carabiner has: {words[0]}", file=sys.stderr)
            return 1
        value = _note_text(c, cfg) if f.kind == "note" else schema.current(f, config.read_yaml(cfg.path))
        print(", ".join(value) if isinstance(value, list) else ("" if value is None else value))
        return 0

    if sub in ("set", "unset"):
        if not words:
            print(f"usage: kbh {c.name} config {sub} KEY{'=VALUE' if sub == 'set' else ''} ...", file=sys.stderr)
            return 64
        if sub == "set":
            bad = [w for w in words if "=" not in w]
            if bad:
                print(f"set takes KEY=VALUE, not {bad[0]}", file=sys.stderr)
                return 64
            res = change(c, cfg, dict(w.split("=", 1) for w in words), [], expert="--expert" in rest)
        else:
            res = change(c, cfg, {}, words)
        return _answer(res, "--json" in rest)

    if sub == "apply":
        raw = os.environ.get(REQUEST_ENV)
        if raw is None:
            raw = sys.stdin.read()
        try:
            req = json.loads(raw or "{}")
            if not isinstance(req, dict):
                raise ValueError("not a JSON object")
        except ValueError as e:
            print(json.dumps({"ok": False, "carabiner": c.name, "error": f"the request is not JSON: {e}"}))
            return 1
        values = req.get("values") if isinstance(req.get("values"), dict) else {}
        unset = [str(k) for k in (req.get("unset") or []) if k]
        return _answer(change(c, cfg, values, unset, expert=bool(req.get("expert"))), True)

    print(f"usage: kbh {c.name} config [show|get|set|unset|apply] ...", file=sys.stderr)
    return 64


def _answer(res: Dict[str, Any], as_json: bool) -> int:
    if as_json:
        print(json.dumps(res, indent=2))
    elif res["ok"]:
        print(f"wrote {', '.join(res['applied'])} in {res['config']}")
        for line in res["belay"]:
            print(f"  {'held   ' if line['ok'] else 'LET GO '} {line['check']}  {line['said']}".rstrip())
        print("belay on." if res["belay_ok"] else "belay: something let go - see above")
    else:
        print(res["error"], file=sys.stderr)
    return 0 if res["ok"] else 1
