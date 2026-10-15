# SerenCarabiners

Carabiners (`.kbh`, for Karabinerhaken) are the packages that clip the Seren
system onto a model's **harness**: the program a model lives in. Claude Code
first, Codex second (so the clip is proven on more than the one it was cut
for); then whatever else.

One carabiner per harness, never per Seren app. Anything in Seren that needs
the harness asks the carabiner, and nothing else of Seren ever learns which
harness it is talking to:

| Verb | What it does | Who asks |
|---|---|---|
| `register` | tell the harness where the model's MCP server is and how to authenticate, with no token on a command line | the Workbench (the one door), any component wanted direct |
| `wake` | start a headless session with a message, memory tools pre-approved, framed the way *this* harness needs | the Hippocampus (a draft, a brief asked for), Lodestar's scheduler, the Observatory |
| `bookmark` | put Margin's bookmark in front of the model as a session starts | Margin, the Workbench |
| `due` | tell a live session something is waiting, or say `unsupported` | the Hippocampus, the Workbench, Lodestar |
| `belay` | *on belay? belay on. climbing. climb on.* - prove each clip holds before weight goes on it | you, after an install or a move |

The strap has two ends. The harness end is the `.kbh`, on the harness box.
The cluster end already exists and is already uniform: **Lodestar** (inbound
to the model: a ripple to a "window" node whose Observatory runs `kbh wake`)
and the **Workbench** (outbound from the model: the one MCP server `register`
points the harness at).

## Use

```bash
python claude.kbh list
KBH_TOKEN_WREN_WORKBENCH=... python claude.kbh claude install --project ~/work --server wren-workbench=http://nuc:7255 --bookmark http://nuc:7251
python claude.kbh claude bookmark install ~/.seren/nuc/margin.yaml
python claude.kbh claude wake --project ~/work --yaml 2      # the lines for an Observatory's ripple:
python claude.kbh claude belay --project ~/work --connection ~/.seren/nuc/workbench.yaml --margin ~/.seren/nuc/margin.yaml --dry-wake
```

A `.kbh` is a Python zipapp: Python 3.8+ and nothing installed. Standard
library only, on purpose; `seren_meninges` and PyYAML are used when present.

**A connection is a route**: a url and a token, dropped straight into the
clip's yaml. A harness is rarely on the brain's box, and nothing is copied from
that box:

```yaml
servers:
  wren-workbench:
    url: http://nuc:7255
    bearer_token: "..."          # or bearer_token_env: NAME, or bearer_token_keyring: "svc/user"
bookmark:
  url: http://nuc:7251
  bearer_token_env: WREN_MARGIN_TOKEN
```

The harness's headers helper and its session-start hook read the route by
reference (`claude.yaml#wren-workbench`, `claude.yaml#bookmark`) when they run,
so a rotated token needs no re-registration. `install --server NAME=URL` takes
the token from `KBH_TOKEN_<NAME>` in the environment (never a command line)
and makes the yaml 0600. When the service runs on the same box, a **connection
file** (the service's own config, or just its `server:` block) does instead:
`--server NAME=FILE`.

## The shape, installed

One standalone file per harness. You install only the ones you want, like a
wheel; `install` pushes what a person edits out beside it.

```
claude.kbh                      the zip: the binder + the Claude carabiner (+ a shipped custom/, if any)
├─ claude.yaml                  pushed out of the zip's config.yaml and filled in; never overwritten
├─ framing.md                   pushed out of the zip; the first words a woken session reads; yours to edit
└─ custom/                      yours; a newer claude.kbh dropped in never touches it
    ├─ python/                  a module per file: VERBS = {...} adds `kbh claude <verb>`; BELAY_CHECKS adds lines
    ├─ extras/                  anything the yaml points at (a framing per event, a prompt, a script)
    ├─ pre_install/*.py         run before install pushes the config
    └─ post_install/*.py        run after (register apply, bookmark install, belay: the whole clip)
```

```bash
python claude.kbh claude install --project ~/work --python /venv/bin/python \
    --server wren-workbench=workbench.yaml --bookmark margin.yaml     # --into defaults to the zip's own folder
python claude.kbh claude belay                                       # finds claude.yaml beside the zip
```

**Sharing a flavour.** `python build.py claude --with-custom ./mine --as chads-claude`
makes `chads-claude.kbh`: the base plus your `custom/`, one file to hand over.
On install the shipped `custom/` lands beside the zip; if the box already has
one, the box's wins and the shipped one lands as `custom.shipped/` to merge by
hand. **A tricks pack** is a `.kbh` with only `custom/`
(`python build.py --tricks wren-tricks --with-custom ./tricks`): `python
wren-tricks.kbh install --into DIR` layers it onto whatever carabiner is
installed there.

## How it rolls on this box: `claude.yaml`

The `.kbh` is code and is the same everywhere. What differs per install is one
yaml beside it, named for the harness, that every verb reads:

```yaml
# claude.yaml
carabiner: claude
project: D:\work\project                    # where wakes run
python: C:\...\venvs\observatory\Scripts\python.exe   # runs the .kbh from hooks and ripples
connections: C:\Users\alice\seren\brain\routes    # the folder of connection files
servers:                                     # what `register apply` registers
  wren-workbench: workbench.yaml
bookmark: margin.yaml                        # Margin's connection file; blank = no hook
framing: framing.md                          # the text a woken session is given, beside this yaml
wake:
  timeout_seconds: 900
```

`install` writes it from the zip's `config.yaml` template (`init` is the quiet form that writes
only the yaml and the framing), and copies the default `framing.md` beside it for you to edit. **The
framing is not in the carabiner**: it is prose, yours to change, and the yaml
points at it; the package's copy is only the fallback when the yaml names none.
A yaml that names a framing file that is missing refuses to wake rather than
waking unframed. The yaml is found beside the `.kbh`, or at `~/.seren/kbh/claude.yaml`,
or wherever `--config` / `KBH_CONFIG` says; with it, the Observatory's ripple
command is just `kbh claude wake --config claude.yaml --run {message}`, and
changing the yaml changes the next wake.

## Codex: the second harness

`codex.kbh` does what `claude.kbh` does, in Codex's own terms (learned from
codex-cli 0.162.1 and its source, and run end to end against the real binary
with a stand-in model and MCP server, 14 Oct 2026):

| Verb | In Codex |
|---|---|
| `register` | a `[mcp_servers.<name>]` table in `$CODEX_HOME/config.toml` with `http_headers_helper` = `kbh codex headers <connection>`: no token in Codex's files, a rotated one needs no re-registration. The file is edited by whole tables, everything else kept, the old one kept as `config.toml.seren-bak`; one that does not parse, or spells `mcp_servers` as an inline table or dotted keys, is not touched. |
| `wake` | `codex exec -C <project> ... -` with the message on stdin and, **for that run only**, each server `default_tools_approval_mode=approve` and `required=true`. Without the approve, a headless Codex refuses every memory call ("requires approval, but approval policy is never"); with `required`, a memory server that is down stops the run instead of waking the model without it. The sandbox stays exec's read-only default. Margin's bookmark goes in the message itself. |
| `bookmark` | a `SessionStart` hook in `$CODEX_HOME/hooks.json` (matcher `startup\|resume`) for the sessions you open. Codex runs a user hook only after you trust it once under `/hooks`; a wake does not depend on it, and the hook stays quiet inside a wake so the bookmark is not said twice. |
| `due` | unsupported for now. `codex queue --thread <id>` puts a message into an existing session: the channel to try once a live session can be named. |

Two things Codex does differently, both checked by `belay`: it runs the
headers helper through `cmd /C` / `sh -c` with the **environment cleared** to
a short list and 10 seconds to answer, so a route with `bearer_token_env`
cannot reach the helper (keep the token in the yaml, 0600, or the keyring);
and an npm install is a `codex.cmd` shim that needs node, so on Windows the
carabiner follows it to the `codex.exe` it starts.

```bash
KBH_TOKEN_WREN_WORKBENCH=... python codex.kbh codex install --project ~/work --python /venv/bin/python     --server wren-workbench=http://nuc:7255 --bookmark margin.yaml
python codex.kbh codex register apply
python codex.kbh codex bookmark install          # then trust it once: codex, /hooks
python codex.kbh codex belay --dry-wake
```

## Write your own

One carabiner per harness, named for it: `claude.kbh`, `hermes.kbh`,
`codex.kbh`. We ship a few and the template; the world goes wild.

```bash
python claude.kbh new hermes --into ./mine --display "Hermes Agent"   # from the template
#   fill in ./mine/hermes/__init__.py (the verbs you support, belay checks) and framing.md
python claude.kbh --path ./mine hermes manifest                      # loads from your folder
python build.py hermes --from ./mine                                 # -> dist/hermes.kbh
```

The template says what each verb must do and what belay must prove. A
carabiner declares which verbs it supports; the binder answers "unsupported"
for the rest, so a harness with no hooks is still a valid carabiner that does
`register` alone. `KBH_CARABINERS=DIR[:DIR]` is `--path` as an environment
variable, for a box that keeps its carabiners in one place.

## Why

A cutover (a model's brain from a desktop to a NUC) ran every
verb by hand and each broke once: the wake command carried server names from
install day; `claude` was not on the *service's* PATH; the bookmark hook pointed
at a Margin that had moved; five MCP entries became one and a running session
never saw the new name; tokens crossed boxes in files made by hand. A
carabiner is where those assumptions get one home and one test. The design
note and the pain-point list are in the Seren punch list under "Carabiners".

## Layout

```
kbh/                 the binder: cli, connection files + tokens, settings merge, belay
kbh/carabiners/      one subpackage per harness, each with a CARABINER class
  claude/            register.py  wake.py  bookmark.py  config.yaml  framing.md
  codex/             the same, and common.py: config.toml read and edited by whole tables
  _template/         what `kbh new` copies
kbh/install.py       push config, framing, custom; run the hooks     kbh/custom.py  the custom/ layer
build.py             -> dist/<name>.kbh; `python build.py hermes --from ./mine` for your own
tests/               pytest; a fake claude and codex, a stand-in Margin, no live service touched
```

## Build, release, host

A `.kbh` is the whole deliverable, so there is no package index in the loop:
build it, put the file somewhere, point the box at it.

**Build** (any python, standard library only):

```bash
python build.py                      # dist/<name>.kbh for every shipped carabiner
python build.py claude               # just claude.kbh
python build.py --all-in-one         # dist/seren.kbh, every shipped carabiner in one file
python build.py claude --with-custom ./mine --as claude-mine   # your custom/ layer baked in
KBH_DIST=/srv/kbh python build.py    # write somewhere else
```

**Release**: bump `__version__` in `kbh/__init__.py`, commit, tag it `v<that>`,
push the tag. `.github/workflows/release.yml` re-runs the tests on Linux and
Windows, refuses a tag that does not match the version, builds every `.kbh`
plus `seren.kbh`, runs each one standalone from an empty directory, and
publishes them with sha256 files as GitHub release assets:

```
https://github.com/<owner>/SerenCarabiners/releases/download/v0.1.0/claude.kbh
https://github.com/<owner>/SerenCarabiners/releases/download/v0.1.0/claude.kbh.sha256
```

**Host**: the asset name `<carabiner>.kbh` is the contract. Anything that can
serve a file is a host: the GitHub release above, a folder on a share, a plain
`http://` directory (a *wheelhouse*). Starwright's carabiner card speaks all
three, in this order of precedence:

```bash
bash seren-carabiner-setup.sh --kbh ./claude.kbh ...                 # a file you have
bash seren-carabiner-setup.sh --local http://files.lan/kbh ...       # a wheelhouse (dir or URL)
bash seren-carabiner-setup.sh --ref v0.1.0 [--repo you/SerenCarabiners] ...   # a release asset
bash seren-carabiner-setup.sh ...                                    # else: build from a checkout beside it
```

A box with a `.kbh` and python needs nothing from this repository. Updating is
replacing the file: the yaml, framing and `custom/` beside it are never
overwritten by an install, so a new `.kbh` picks up where the old one left off.

## Development

```bash
python -m pytest -q
python build.py && python dist/claude.kbh list
```

## License

See LICENSE.
