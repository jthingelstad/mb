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
