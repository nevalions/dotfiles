# Local token preflight

Read before any append. Per-field character limits do not guarantee that the complete rendered conclusion fits the server's embedding limit.

On 2026-11-23, the deployed Honcho source revision `0cd37ddbd88f51cdac7c660d7372f4b2fd40a4b3`, `src/schemas/api.py`, `ConclusionCreate.validate_token_count`, used `tiktoken==0.12.0`, `get_encoding("o200k_base").encode(content)` with default flags, and the live `Embedding.MAX_INPUT_TOKENS` limit was 512. A rendered note of 2197 characters counted 531 tokens despite fitting all gateway field limits. These are verified deployment settings, not universal Honcho defaults. If the service changes, verify its tokenizer, version, and limit before using different options; never raise a local limit merely to pass.

Create the exact proposed publisher payload in a private directory outside repositories as an owner-only regular mode-0600 JSON file. Include the exact live granted scope and all four evidence fields. The local helper reuses the installed gateway's validation and rendering through an in-memory capture object; it does not instantiate a REST client, prepare a real session, read credentials, or publish. Scope shape validation is not authorization.

Use `scripts/check_payload.py` relative to this skill directory. With installed `uv`:

```sh
uv run --with tiktoken==0.12.0 python /absolute/skill/scripts/check_payload.py /absolute/private/payload.json --max-tokens 512 --encoding o200k_base
```

Alternatively run it with a Python environment containing exactly `tiktoken==0.12.0`. The default renderer is `~/.codex/honcho/gateway.py`; `--gateway` can select another trusted deployed gateway file. Count with the renderer that will actually publish.

Dependency installation and public tokenizer data preparation may need network access. The helper refuses tokenizer cache misses rather than downloading data while handling a private payload. Prepare public encoding data separately, without a payload:

```sh
uv run --with tiktoken==0.12.0 python -c 'import tiktoken; tiktoken.get_encoding("o200k_base")'
```

Then rerun the helper. It emits only token count, limit, and pass/fail; exit 0 means within budget, 1 means over budget, and 2 means preflight unavailable or invalid. It never prints the note or scope. A successful local check does not grant publication or replace readback.

If over budget, rewrite the fact, source reference, checks, and verification concisely while preserving material qualifications, including historical evidence and unproven root causes. Count again. Do not silently truncate, estimate tokens from characters, omit evidence, or send the payload to a remote tokenizer. Leave memory unsaved if an accurate supported fact cannot fit.
