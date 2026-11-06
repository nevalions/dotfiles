"""Bind ``/q`` to ``/quit``.

Hermes registers ``q`` as an alias of ``/queue`` in ``hermes_cli.commands``.
Aliases live in that module's lookup table, and there is no public API for
overriding one: a plugin cannot register ``q`` because ``register_command``
refuses names that resolve to a built-in, and ``quick_commands`` only runs when
no built-in handler matched.

So this plugin rewires the in-process registry once, at load: the alias moves
from ``queue`` onto ``quit`` and the registry entries plus the lookup table are
rebuilt, which keeps dispatch, ``/help`` and autocomplete consistent. It is
local state, not a core patch, so ``hermes update`` does not lose it. If a
Hermes upgrade renames these internals the plugin only logs a warning and the
stock ``/q`` (queue) stays in place.
"""

from __future__ import annotations

import dataclasses
import logging

logger = logging.getLogger(__name__)

ALIAS = "q"


def _rewire() -> bool:
    """Move the alias from queue to quit. True when the registry changed."""
    from hermes_cli import commands

    registry = commands.COMMAND_REGISTRY

    def first(name: str):
        return next(((i, c) for i, c in enumerate(registry) if c.name == name), None)

    quit_match = first("quit")
    if quit_match is None:
        return False
    quit_index, quit_cmd = quit_match
    if ALIAS in quit_cmd.aliases:
        return False  # upstream already binds /q to quit

    queue_match = first("queue")
    if queue_match is not None and ALIAS in queue_match[1].aliases:
        queue_index, queue_cmd = queue_match
        registry[queue_index] = dataclasses.replace(
            queue_cmd, aliases=tuple(a for a in queue_cmd.aliases if a != ALIAS)
        )
    registry[quit_index] = dataclasses.replace(
        quit_cmd, aliases=(*quit_cmd.aliases, ALIAS)
    )

    lookup = commands._COMMAND_LOOKUP
    lookup.clear()
    lookup.update({key: cmd for cmd in registry for key in (cmd.name, *cmd.aliases)})
    return True


def _apply() -> None:
    try:
        if _rewire():
            logger.info("/q now exits (alias of /quit) instead of queueing a prompt")
    except Exception:  # internals moved: leave the stock alias alone
        logger.warning("q-quit: could not rebind /q to /quit", exc_info=True)


_apply()


def register(ctx) -> None:
    """Plugin entry point (the import-time call covers early discovery paths)."""
    _apply()
