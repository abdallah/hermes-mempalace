# MemPalace plugin installed

You can now activate this provider in Hermes.

## Next steps

1. Run `hermes memory setup`
2. Select `mempalace`
3. Verify with `hermes memory status`
4. Start a fresh Hermes session and confirm the provider is still active

## Install the MemPalace CLI

The upstream docs recommend `uv`:

```bash
uv tool install mempalace
```

`pipx install mempalace` is also supported upstream. Use plain `pip install mempalace` only inside an activated virtualenv.

## Quick manual fallback

If you already know you want this provider:

```bash
hermes config set memory.provider mempalace
```
