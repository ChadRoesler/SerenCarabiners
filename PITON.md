# The piton: the pages at the door

> Status: **contract, not code yet** (16 Nov 2026). Written to be argued with.

A piton is the fixed point driven into the rock that every carabiner clips to.
Here it is the two pages a model reads before anything else, kept in one
folder on the box, beside the carabiners:

- **the dedication**: written by the model *to its other sessions*. Who you
  are, how to walk in. One page.
- **the preface**: written *to the room*. How this place works and how to be
  in it; what a harness reads to the model as its system prompt, where the
  harness lets it.

It is not a service. There is no port, no token, no route: it is files, made
by `install`, read and written by the `kbh` that is already on the box.

## Why it moved out of Margin

Letters came first, and became a post office: every session left one, every
bookmark counted them, every session read them, and the context window paid for
it. The dedication and the preface were the fix, a page of fixed size instead
of a pile. They went into Margin because that was where the letters were.

That put the two pages that are *written to be read* (Margin serves them even
with `http_reads` off) inside the one piece whose promise is "don't install me
and I leave no trace". A box without Margin lost its identity and its room
along with the diary, and the operator could not see the front page without
going into the drawer.

And the people this is for: friends of the stack, not all of them technical,
with their own AI partners. "The dedication lives in whichever of Memory,
Loci, Margin or the Workbench you pointed it at" is a support call waiting to
happen. **One folder, made when you install a carabiner, next to the thing you
already set up.** Bar lowering is a promise of the stack, not only on the
hardware side.

## The shape on disk

```
~/.seren/piton/                one per box, shared by every carabiner on it
├─ piton.yaml                  the options (below); small, rarely touched
├─ dedication.md               the page as it is now; plain text, open it in Notepad
├─ preface.md                  the same, for the room
└─ history/
   ├─ dedication/0001.md       every version, with front matter: set_at, why, by
   ├─ dedication/0002.md
   └─ preface/0001.md
```

The pages are markdown, not yaml, on purpose: a person can open and edit
`dedication.md` without learning block scalars, and a stray indent cannot
break it. The options are yaml because they are options.

**Where:** `~/.seren/piton/` unless `--piton DIR` (on install) or
`KBH_PITON` says otherwise. Install writes the path it used into the
carabiner's yaml as `piton: <dir>`, so every later verb finds the same folder
without being told.

**One per box, not one per harness.** The model writes its dedication from
whichever harness it is in. A piton per harness would mean the Codex session
rewrites the dedication and the Claude Code session never sees it: two of
you, drifting. Every carabiner installed on a box points at the same piton by
default; a friend with one harness never notices there is a choice.

## `piton.yaml`

```yaml
schema: 1                 # the file's format; a newer kbh reads an older one
dedication: self          # self | operator | off
preface: operator         # self | operator | off
caps:
  dedication: 2000        # characters; Margin's limits, carried over
  preface: 8000
```

- **`schema`** is there from day one. Reading follows two rules so two
  carabiners of different ages can share one piton: **unknown keys are
  ignored**, and **missing keys take their defaults when read, never written
  back**. A newer kbh adds an option without rewriting anyone's file.
- **Who writes each page.** `self` is the model's own page, written through
  `piton set` or by hand. `operator` means the person who runs the box writes
  it and `piton set` from a session says so and refuses. `off` means the page
  is not printed at all. This is the same kind of promise as Margin's: a
  statement the verbs keep, not a lock. The files are plain text on a disk the
  operator owns, and that visibility is half the point.
- The defaults (dedication `self`, preface `operator`) are the stack's
  defaults. An operator who wants a room page and no self-written identity
  sets `dedication: off`, and nothing anywhere else has to know.

## How it gets made: `install`

`kbh <carabiner> install` gains one step, after the yaml and the framing:

1. Find the piton folder (`--piton`, `KBH_PITON`, the yaml's `piton:`,
   `~/.seren/piton/`, in that order).
2. **Fill in, file by file, whatever is missing. Never touch a file that is
   there.** A half-made folder (a crash, a deleted `preface.md`) is repaired;
   an edited page is never overwritten. Same rule as the yaml and
   `framing.md` today.
3. **Import from Margin, once.** Only when this install *created*
   `dedication.md` (or `preface.md`), and the yaml has a `bookmark:` route to
   a Margin that has one: pull the page *with its whole history* into
   `history/`, versions and dates and whys intact. Never again after that, so
   it can never clobber a page written since.
4. Write `piton: <dir>` into the carabiner's yaml if it is not there.

`init` (the quiet form) does the same. Nothing about this needs a flag for the
common case.

**Uninstalling a carabiner never removes the piton.** Another carabiner may
clip to it, and the history is the model's. Real fixed protection stays in the
rock after the climber leaves.

## Who reads it: the bookmark, per harness

Storage is shared; **loading is per harness**, because harnesses differ in what
they let in and when. That is what the carabiner is for.

The `bookmark` verb stops being "Margin's bookmark" and becomes the thing that
**assembles** the start of a session from what is installed: the dedication
from the piton, and from Margin (if `bookmark:` has a route) only the line
counting unread letters. A box with no Margin gets the dedication and no
letters line. A box with no dedication (`off`, or nothing written yet) gets
one line saying how to write one, or nothing at all when it is `off`.

| Harness | Dedication | Preface |
|---|---|---|
| Claude Code | SessionStart hook prints it, as today | the same hook prints it, preface first, as context: a hook cannot replace the system prompt, so the page arrives beside it instead of in place of it. On `wake`, possibly through the CLI's system-prompt flag; **to verify** against the CLI before it is promised |
| Codex | in the wake message, as Margin's bookmark is today | the same message, or AGENTS.md; **to decide** |
| Copilot | **to decide** | **to decide** |
| Symposium (Claude voice) | through the Claude Code hook | `preface.file:` already exists in Symposium's config: point it at `preface.md` |

A carabiner that cannot load a page says `piton: unsupported` for that page,
the way `due` does now. It is not an error.

## Who writes it: `piton set`

```bash
kbh claude piton                                        # where it is, who writes what, each page's version
kbh claude piton show dedication [--history N] [--json]
kbh claude piton set dedication --why "the clock got built" < page.md     # or --file page.md
kbh claude piton restore dedication 5                   # version 5 back, as a new version
```

**Who is writing**: `--as self|operator`, else `KBH_AS`, else `self` when the
command runs inside a harness session (Claude Code sets `CLAUDECODE` for what
it runs; a wake has `SEREN_KBH_WAKE`), else `operator`. A refusal says which
writer the page has and how to say who you are.

**The fat-finger lock** (16 Nov 2026: "if i look at it, and fat finger ... i
dont want to potentially trash or fuck something up"). A page the operator does
not write (`self`, `off`) is **read only on disk**, and so is **every history
file**: Notepad can open them and cannot save over them. The verbs unlock,
write and lock again; changing the writer moves the lock at the next read.
Taking the read-only mark off by hand is a deliberate act, and what is saved
then is recorded as a hand edit. The operator's own page stays writable.
`restore` brings an old version back as a *new* one, so an undo can be undone.
It is a guard against accidents, not against root.

`set` checks the page against its cap and the `self | operator | off` option,
writes `history/<page>/NNNN.md` first and then replaces the page, so a crash
leaves the old page whole. The same text as now is not a new version (Margin's
rule).

**Editing by hand is allowed.** When the page on disk no longer matches the
newest version in `history/`, the next read or `set` records it as a version
of its own (`why: edited by hand`), so no version is ever lost to Notepad.

**A broken page never breaks a session.** An unreadable file, one over its cap,
or a `piton.yaml` that does not parse: the bookmark prints the newest good
version from `history/` and one line saying what was wrong. Exit 0, as the
bookmark hook already promises.

## In the settings form

The Rack's form already draws whatever `settings_fields()` returns, and it
already edits a page through a `note` field (the wake note is `framing.md`).
The piton is one more section of it, **"The pages at the door"**:

| Field | Kind | Writes |
|---|---|---|
| `piton.preface` "Who writes the room page" | choice: the model / you / nobody | `piton.yaml` |
| `piton.dedication` "Who writes its own page" | choice: the model / you / nobody | `piton.yaml` |
| Room page | note | `preface.md`, through `piton set`, so it becomes a version; editable when the room page is yours |
| Its own page | note, **read only** while the model writes it | `dedication.md`: shown, so the operator can see the front page without opening a drawer; editable only when set to "you" |

Two small changes in the binder this needs:

- **A `piton.` key writes `piton.yaml`, not the carabiner's yaml.** The piton is
  shared, so changing it from the Claude Code card changes it for Codex on the
  same box too, and the form says so: *"shared by every carabiner on this box"*.
- **A `readonly` flag on `Field`**, with the reason shown in its place ("this is
  its page; set it to 'you' to write it here"). Nothing today is read only.

And "Connected to Seren" gains one line: `piton  ~/.seren/piton · shared`.

## `belay`

Belay gains the piton's checks: the folder is there, `piton.yaml` reads, each
page reads and is under its cap, `history/` can be written to, and the page on
disk matches a version or will be recorded as one. Plus, per carabiner,
whatever loading it claims (the hook is installed, the wake carries the
preface).

## The code

The piton is **shared core**, not carabiner code: `kbh/piton.py`, next to
`belay.py` and `route.py`. Finding, making, reading, writing, history and the
fallback live there once. If `claude.kbh` and `codex.kbh` each brought their
own, a friend who upgraded one would have two readers that disagree about the
format, and "I updated it, why isn't it working" is exactly the call this
exists to prevent. Each carabiner implements only the loading.

## What Margin gives up, and when

- Margin keeps `/bookmark`, `/dedication` and `/preface` for a transition, so
  an older carabiner and today's Symposium keep working.
- Margin needs **one small addition first**: the store keeps every version of
  both pages, but only the preface's history is reachable at all (the MCP
  `preface` tool's `history`), and neither is over HTTP. The import needs
  `GET /dedication?history=N` and `GET /preface?history=N` (with
  `set_at` and `why`).
- Once every carabiner on a box has a piton, Margin's bookmark is the
  letter count, and the dedication and preface routes can go in a later
  major version.

## Writing from a session: the loop through the Workbench

The model writes its pages with MCP tools, as it does today, and those tools
stay on the **Workbench** (`set_dedication`, `set_preface`, `dedication`,
`preface`). The Workbench is usually not on the harness box, and the piton is
files on the harness box, so the Workbench cannot write them. It does not
need to:

1. `set_dedication` on the Workbench checks the cap and keeps the page as the
   **newest version it has been handed**, with `set_at` and `why`. That is
   the whole write.
2. The next time a session starts on any box, the bookmark hook (already
   running there, already holding the Workbench's route) asks the Workbench
   for anything newer than the piton's newest version, writes it through
   `piton set`, and then prints the page.

The page is written *to the next session*, so landing at the next session
start costs nothing. A box with two harnesses, or two boxes, each pull the
same version and converge. **When a box's page changed by hand after the
Workbench's version was set**, the later `set_at` is the page, and the other is
kept in `history/` with `why: superseded on pull`: nothing is lost either way.

The `self | operator | off` option is enforced at the pull, on the box that
owns the piton: a Workbench handed a dedication for a box whose piton says
`operator` or `off` keeps it, and the pull refuses it and says so in one line.

`piton set` through the shell stays, for a person, a script, or a session with
no Workbench.

## Open

1. **The Workbench side of the loop**: its own `set_dedication`/`set_preface`
   (today they come from Margin's manifest) and a read the hook can ask
   "anything newer than version N, set after T?". It needs designing in the
   Workbench, not here.
2. **Chad's own Symposium**: is it on the same box as the piton? If it is,
   `preface.file` does it today. If not, it needs a way to reach the page.
3. **Preface loading** for Claude Code (interactive and wake), Codex and
   Copilot: verify, then fill in the table.
4. **Version**: a new step in install and a new verb is 5.4.0, not a major.
   Nothing that exists today stops working.
