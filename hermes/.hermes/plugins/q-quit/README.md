# q-quit

`/q` exits the CLI, same as `/quit`.

Hermes ships `/q` as an alias of `/queue`, and aliases are resolved from the
built-in registry before plugin commands, skills or `quick_commands` get a turn
— so no supported config key can move it. This plugin moves the alias at load
time instead:

- `hermes_cli.commands.COMMAND_REGISTRY`: `q` is dropped from `queue` and added
  to `quit` (entries replaced, since `CommandDef` is frozen).
- `_COMMAND_LOOKUP` is rebuilt, so dispatch, `/help` and autocomplete agree.

It registers no commands of its own and is safe to load twice. If a Hermes
upgrade changes these internals, it logs `q-quit: could not rebind /q to /quit`
and leaves `/q` as queue.

Tracked in dotfiles under `hermes/.hermes/plugins/q-quit/`, stowed to
`~/.hermes/plugins/q-quit`, and enabled through `plugins.enabled` by
`hermes/install.py`. Applies to the CLI/TUI; a desktop or gateway process only
sees it after it loads plugins.
