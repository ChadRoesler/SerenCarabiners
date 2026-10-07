"""
kbh.belay - the handshake.

    On belay?   the carabiner checks its own side of each verb
    Belay on.   the harness's side answers
    Climbing.   the carabiner says what it is about to do
    Climb on.   the harness acknowledges

A Check is one line of that: a verb, which side, a name, whether it held,
and a word about why not. `belay` runs every check a carabiner declares and
answers as text or JSON; exit 0 only when every check that is not `skipped`
held. It changes nothing. Run it when the carabiner is installed, when
anything it depends on moves (a card re-run, a service that changed boxes),
and whenever a wake went into the void: the 6-7 Oct 2026 cutover had a stale
wake command, a binary off the service's PATH, a bookmark pointing at a Margin
that had moved and five MCP entries pointing at a dead desktop, and nothing
said so until a draft sat unreviewed.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Callable, Dict, Iterable, List, Optional

SIDES = ("on belay?", "belay on.", "climbing.", "climb on.")


@dataclass
class Check:
    verb: str
    side: str                      # one of SIDES
    name: str
    held: Optional[bool] = None    # None = skipped (verb unsupported, or not asked for)
    why: str = ""
    detail: Dict[str, object] = field(default_factory=dict)

    @property
    def status(self) -> str:
        return "skipped" if self.held is None else ("held" if self.held else "LET GO")


def held(verb: str, side: str, name: str, why: str = "", **detail: object) -> Check:
    return Check(verb, side, name, True, why, dict(detail))


def let_go(verb: str, side: str, name: str, why: str, **detail: object) -> Check:
    return Check(verb, side, name, False, why, dict(detail))


def skipped(verb: str, side: str, name: str, why: str = "") -> Check:
    return Check(verb, side, name, None, why)


@dataclass
class Report:
    carabiner: str
    checks: List[Check] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(c.held for c in self.checks if c.held is not None)

    def text(self) -> str:
        width = max([len(f"{c.verb} / {c.side} / {c.name}") for c in self.checks] + [10])
        lines = [f"belay {self.carabiner}: {'climb on.' if self.ok else 'LET GO - do not put weight on it'}"]
        for c in self.checks:
            label = f"{c.verb} / {c.side} / {c.name}".ljust(width)
            lines.append(f"  {c.status:8s} {label}  {c.why}".rstrip())
        return "\n".join(lines)

    def json(self) -> str:
        return json.dumps({"carabiner": self.carabiner, "ok": self.ok,
                           "checks": [{"verb": c.verb, "side": c.side, "name": c.name, "status": c.status,
                                       "why": c.why, **({"detail": c.detail} if c.detail else {})}
                                      for c in self.checks]}, indent=2)


def run(carabiner: str, checks: Iterable[Callable[[], Check]]) -> Report:
    """Run each check; a check that raises is a check that let go, with the
    exception as its why - a belay must not itself fall off the wall."""
    rep = Report(carabiner)
    for fn in checks:
        try:
            rep.checks.append(fn())
        except Exception as e:  # noqa: BLE001
            rep.checks.append(let_go("belay", "on belay?", getattr(fn, "__name__", "check"),
                                     f"the check itself failed: {type(e).__name__}: {e}"))
    return rep
