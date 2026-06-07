# Hermes MemPalace Memory Plugin

A standalone Hermes memory-provider plugin that uses [MemPalace](https://github.com/MemPalace/mempalace) for local-first, profile-scoped persistent memory.

## What it does

- buffers conversation turns during a session
- mines finished conversations into a profile-scoped MemPalace palace
- exposes three Hermes tools:
  - `mempalace_search`
  - `mempalace_wake_up`
  - `mempalace_status`
- stores everything under the active `HERMES_HOME`, so separate Hermes profiles stay isolated

## Install

### Fast path for Hermes users

```bash
hermes plugins install abdallah/hermes-mempalace --enable
hermes memory setup
```

If the MemPalace CLI is missing, Hermes will prompt for the dependency defined in `plugin.yaml`.

### Manual path

The MemPalace docs recommend installing the CLI with `uv`:

```bash
uv tool install mempalace
```

If you prefer `pipx`, the upstream docs say that also works:

```bash
pipx install mempalace
```

Only use plain `pip install mempalace` inside an activated virtual environment when you explicitly want the importable package available.

Then install the plugin repo into Hermes with your preferred plugin workflow.

## Verify

```bash
hermes memory status
hermes plugins list
```

Expected result:
- the active memory provider is `mempalace`
- the plugin is installed and available
- Hermes can surface the three MemPalace tools

## How Hermes uses this plugin

This provider is intentionally simple and predictable:

1. `system_prompt_block()` adds a short memory reminder to the prompt.
2. `prefetch()` runs a MemPalace search before the first model call when useful.
3. `sync_turn()` buffers the completed turn without blocking the chat loop.
4. `on_session_end()` writes the buffered turns to a markdown transcript and mines it into the palace.
5. `shutdown()` flushes any remaining buffered turns.

## Storage layout

All storage is profile-scoped under the active `HERMES_HOME`:

- `mempalace/palace/` — palace index
- `mempalace/conversations/` — mined conversation transcripts

## Repository layout

- `__init__.py` — plugin implementation
- `plugin.yaml` — Hermes plugin manifest
- `README.md` — setup and usage docs
- `after-install.md` — short post-install guidance

## Smoke test

After install, run:

```bash
hermes memory status
hermes memory setup
```

Then ask Hermes to remember a small fact and confirm that the next session can recover it through MemPalace search or wake-up.

## Notes

- This repository is a standalone plugin repo, not a fork of Hermes core.
- It is designed so Hermes can install it directly from GitHub and then select it as the active memory provider.
- No API key is required.
