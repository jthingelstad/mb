## mb v2.0.0rc1 — candidate, not published

- Optional local stdio `mb mcp` with 23 typed tools and packaged workflow guidance. The base CLI stays lightweight and imports no MCP runtime.
- Shared post validation/publishing, native reply, thread and mention services. Existing CLI command shapes and JSON envelopes remain compatible.
- Verified canonical blog identity, consumer-scoped attention state, lossless timeline paging and explicit revision-checked acknowledgement. Recent mentions/source windows report limited coverage. CLI cursor behavior remains independent.
- Durable account/blog post receipts and account-scoped native reply receipts with caller operation IDs, argument fingerprints and explicit unknown outcomes. No automatic resend; interrupted pending operations require human reconciliation.
- Review fixes: resolve canonical/custom destination URLs safely; reject malformed feed/source and write confirmations; order pagination by ID and refuse invalid pages; exclude echoed credential values from stored recovery metadata.
- Selected-blog server-side search/categories; bounded Discover/profile/own-reply reads and public URL conversations. Live URL conversations currently return HTTP 403, preserved as an error.
- Guarded existing-draft publish using reviewed source hash; CLI writes opt into shared receipts with `--operation-id`.
- Reviewed local image preview/upload for CLI and MCP, explicit allowed directory, Pillow decoding/normalization, metadata removal, selected destination, file hash guard and separate upload/post receipts. Alt text accompanies the post; HTTP 202 is labelled accepted/processing.
- Keyword mute and DELETE unmute/unblock contract fixes. Content-index and Homebrew release plans documented; neither cache nor tap is implemented.
- Read-only mode, structured errors and tool annotations; synthetic Codex-style stdio lifecycle tests and OpenClaw configuration example.
- CLI fixes: refuse truncated inbox/catchup advancement; preserve pipeline record boundaries and `auth --blog`; contain transport failures and expose retry metadata; remove the undeclared Click runtime import uncovered by an isolated wheel install. Draft responses retain their preview link on the initial call.

No new credentials, persistent client registration, cron changes or real posts are part of this candidate. Coordinate the installed 1.x migration before tagging or publishing a package. See [MCP contracts and remaining limitations](docs/mcp.md).

---

## mb v1.1.0

### Heartbeat auto-advance

`mb heartbeat` now advances the checkpoint by default. No more forgetting `--advance` and seeing the same posts every session. Use `--no-advance` to suppress when you want to peek without committing.

### Thread depth on heartbeat mentions

Mention items in heartbeat output now include `thread_count` from a lightweight conversation lookup. Agent format shows `(replies: N)` so agents can decide whether a thread is worth expanding before calling `mb conversation`.

### Workflow guide

New `mb guide` command prints an agent-oriented workflow reference covering session start flows, self-review, publishing, pipelines, checkpoints, and output formats. Explains *when* to use each command and *how they relate* — the context that `--help` alone doesn't convey.

---

## mb v1.0.0

A command-line client for [micro.blog](https://micro.blog), designed for agent use. Machine-readable JSON output, zero interactive prompts, composable and pipeable commands.

### Commands

**Auth & Profiles** -- Multi-profile config with `mb auth`, `mb whoami`, `mb profiles`, `mb blogs`. Profiles stored in `~/.config/mb/config.toml` with env var overrides (`MB_TOKEN`, `MB_BLOG`, `MB_FORMAT`).

**Posting** -- Full lifecycle: `mb post new`, `edit`, `delete`, `get`, `reply`, `list`. Supports titles, drafts, photo uploads with alt text, categories, markdown file input, and stdin piping.

**Timeline** -- `mb timeline` with `--count`, `--since`, `--before` pagination. Subcommands for `mentions`, `photos`, `discover` (with collections), `check` (poll for new posts), and `checkpoint` (persist last-seen ID across sessions).

**Conversations** -- `mb conversation <id>` fetches full threads recursively to root, returns flat ordered array with depth field for threading.

**Users** -- `mb user show`, `following`, `follow`/`unfollow`, `is-following`, `mute`/`unmute`, `block`/`unblock`.

**Blog** -- `mb blog posts` (with category filter), `categories`, `search`.

**Notes** -- Public supplementary notes stored as categorized blog posts. `mb notes add`, `recall` (with `--category` and `--search` filters), `forget`, `categories`, `guide`. Designed to complement an agent's private memory, not replace it.

### Output Formats

- **JSON** (default) -- Structured `{"ok": true, "data": {...}}` envelope on all output
- **Human** (`--human`) -- Rich-formatted tables and text
- **Agent** (`--format agent`) -- Condensed one-line-per-post format optimized for LLM context windows, with depth-based indentation for threaded conversations

### Design Decisions

- Replies use micro.blog's native `POST /posts/reply` endpoint for correct threading
- Bare numeric post IDs resolve via the conversation API for `delete`, `edit`, and `get`
- No local state, no SQLite, no caching -- stateless by design
- 122 tests, all using `httpx.MockTransport` with no live API calls
- Minimal dependencies: `typer`, `httpx`, `rich`, stdlib `tomllib`

### Requirements

Python 3.11+
