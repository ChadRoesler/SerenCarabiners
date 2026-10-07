"""
kbh - the binder every carabiner hangs from.

A carabiner (.kbh, for Karabinerhaken) clips the Seren system onto ONE harness:
the program a model lives in (Claude Code first). Anything in Seren that needs
the harness - the Hippocampus to wake the model, Margin to hand over a bookmark,
the Workbench to be registered, Lodestar's scheduler - asks the carabiner, and
nothing else of Seren ever learns which harness it is talking to.

One carabiner per harness, never per Seren app. Four verbs and a handshake:

    register   tell the harness where the model's MCP server is and how to
               authenticate - without a token on a command line
    wake       start a headless session with a message, memory tools
               pre-approved, framed the way THIS harness needs
    bookmark   put Margin's bookmark in front of the model as a session starts
    due        tell a live session something is waiting (or say: unsupported)
    belay      on belay? belay on. climbing. climb on. - prove every clip
               holds before weight goes on it

This package is the shared part: the command line (`kbh <carabiner> <verb>`),
connection files (where a service is and how to present its token), token
resolution, the settings merge, and the belay framework. Each carabiner is a
subpackage under kbh.carabiners with its own verbs and its own framing.

Standard library only, so a harness box needs Python and nothing else;
seren_meninges and PyYAML are used when they are there and not required.
"""
from __future__ import annotations

__version__ = "0.1.0"
