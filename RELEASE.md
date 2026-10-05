## mb v2.2.1

- **Publishing a draft reports the post's new URL.** Micro.blog moves a draft to a new URL when it is published and the draft URL stops resolving. `post_publish` and `mb post publish` used to report the old URL, so a following read, edit or delete found nothing. The result's `url` is now the published address Micro.blog returns (accepted only on the selected blog), and `draft_url` holds the retired one. The `post_publish` output schema adds `draft_url`.
- **Live smoke test.** A scheduled workflow exercises a dedicated Micro.blog test account end to end: guided `mb auth` in a pseudo-terminal, CLI reads and `mb doctor`, every MCP read validated against its schema, and a draft, edit, publish and delete cycle. Its first run found the bug above. A full suite (`-f suite=full`) covers every read command in each output format, the stdin pipelines, refusal paths, checkpoints and the whole CLI post lifecycle; it passed 151 checks against the test account before this release.

---

## mb v2.2.0

- **Guided sign-in.** Run bare `mb auth` in a terminal: it links the micro.blog app token page, reads the token without echoing it, checks it, and asks again (up to three times) when micro.blog rejects it. A network or server failure is reported instead of re-prompting. If the account can post to more than one blog, it lists them and asks which to use, defaulting to the profile's current blog or the account default; `--blog` skips the question. It saves the profile and prints next steps (`mb doctor`, `mb heartbeat`, adding the MCP server to Claude Code). Prompts go to stderr, and the result envelope still goes to stdout.
- **No prompts for scripts.** Without a terminal, bare `mb auth` exits with a structured error rather than waiting for input. `mb auth -` and `mb auth TOKEN` behave as before.
- **Setup hints.** "No token configured" errors and `mb doctor` now point at `mb auth`.

---

## mb v2.1.0

- **Versioned results.** Every CLI `--format json` envelope and MCP result starts with `"schema_version": 1`. Adding a field keeps the version; removing, renaming or retyping one bumps it.
- **Per-tool output schemas.** Each of the 23 MCP tools publishes the schema of its own result instead of one generic envelope, and [docs/mcp-schemas.json](docs/mcp-schemas.json) collects them. Tests validate real stdio results against them.
- **Compact MCP reads.** Read tools return `content_text`, a flat author, and `links` and `images` lists, without the HTML, the upstream `author` and `_microblog` blocks, feed metadata or the repeated identity. Own-blog lists return a 500-character excerpt. Live, a typical session's results are about a third of their 2.0 size. Pass `verbose: true` for the full shape. `profile_get` adds a flat `profile`, and `blog_posts` now reports `returned_count`. CLI JSON is unchanged apart from `schema_version`.
- **Inbox rebaseline.** When the saved mention has aged out of Micro.blog's recent mentions window, `inbox` reports `anchor_missing: true` and still offers no acknowledgement. After the person agrees, `inbox` with `rebaseline: true` lets the recent window be acknowledged, and `checkpoint_ack` reports `rebaselined` with the `previous_checkpoint`.
- **Heartbeat pages.** The first heartbeat stays a 3-post snapshot; later heartbeats page 20 posts at a time since the checkpoint. `count` still overrides.
- **State file name.** The shared receipt and checkpoint store is now `~/.config/mb/state.sqlite3`. An existing 2.0 `mcp-state.sqlite3` keeps being used while it is the only one, so no receipts or checkpoints are lost; nothing is moved or renamed automatically.
- **Install name.** The Homebrew tap is now `jthingelstad/tap`: `brew install jthingelstad/tap/mb`.

---

## mb v2.0.1

The first release meant for public use, installable with `brew install jthingelstad/tap/mb`.

- **Write recovery hardening.** Ctrl-C or a killed process during a write now records the outcome as unknown instead of leaving a pending claim that blocks every later write. Failures before anything is sent are reported as `not_applied`, and a reply reads its thread before claiming the operation ID. A person can now record the verified outcome with `mb operation-status ID --resolve applied|not_applied [--scope blog|reply] [--note TEXT]`. Resolution only updates the local receipt, is never automatic, and is not available over MCP.
- **`mb doctor [--offline]`.** A read-only health check: version, Python and install method, every `mb` on `PATH` and which one shadows the others, MCP availability, config permissions and profiles, token source, (online) token, blogs and destination, state file permissions, pending/unknown receipts with resolve hints, legacy checkpoints and media root. Exits 1 on any error.
- **`mb --version` / `-V`.**
- **`mb auth -`** reads the token from stdin so it stays out of shell history. `mb auth TOKEN` still works.
- **Config safety.** The config file is written atomically and created 0600 from the start; profile and checkpoint names are limited to letters, digits, `-` and `_`; an unreadable config gives a structured error with its path and line instead of a traceback. With `MB_TOKEN` set, the username comes from that token rather than the cached profile.
- **Edits and results.** An edit with empty content is refused instead of blanking the post. A new post's result reports its `url`; the old `id` (the URL's last path segment, which no command accepted) is gone.
- **CLI fixes.** `--format=json` style options work anywhere; an unknown `--format`/`MB_FORMAT` is an error instead of silently using JSON; `--count` is bounded 1 to 50 and `poll --interval` 1 to 3600; agent output decodes HTML entities.
- **Images upload unchanged.** `mb media upload` / `mb upload` take any local JPEG, PNG, GIF or WebP up to 20 MiB and upload it exactly as provided; `--sha256` is optional and the CLI no longer needs `--media-root`. EXIF/GPS metadata is not stripped. The MCP image tools still require an absolute `--media-root`. The Pillow dependency is removed.
- **Pipeline fixes.** Agent-format `coverage=` metadata goes to stderr; `mb lookup users` and `mb lookup posts` errors go to stderr with a non-zero exit; stdin readers skip blank lines and `#` comments.
- **Verified destination everywhere.** `post get`, `post list` and URL lookups in `lookup posts` verify the account and send the selected blog's canonical Micropub destination, like the other write and read services. `heartbeat --mentions-only` no longer advances the heartbeat checkpoint.
- **MCP:** the default `--consumer` is now `default` (was `dot`). The missing-extra hint points at Homebrew and `uv tool install`.
- **Docs rewritten for public release:** README, MCP contracts, migration notes, `mb guide`, `mb://guide`, skills and client examples (Claude Code, Claude Desktop, Codex, OpenClaw).
- **Release-notes correction:** `mb notes`, documented in v1.0, was removed in 2.0. Use ordinary posts with a category instead.
- **Packaging:** project metadata (readme, URLs, classifiers); CI tests Python 3.11 to 3.14 on Linux and macOS. The Homebrew tap supports every platform Homebrew bottles: Apple Silicon macOS and Linux x86_64/arm64.

---

## mb v2.0.0

Released. Upgrading from 1.x: see [docs/migration-2.0.md](docs/migration-2.0.md).

- Optional local stdio `mb mcp` with 23 typed tools and packaged workflow guidance. The base CLI stays lightweight and imports no MCP runtime.
- Shared post validation/publishing, native reply, thread and mention services. Structured envelopes remain; post/upload calls have explicit major-version changes (see [migration guide](docs/migration-2.0.md)).
- Verified canonical blog identity, consumer-scoped attention state, lossless timeline paging and explicit revision-checked acknowledgement. Recent mentions/source windows report limited coverage. CLI cursor behavior remains independent.
- Native-order attention anchors and revision-CAS acknowledgement support nonmonotonic IDs; exact inbox anchors establish completeness. Additive provenance marks unverified historical checkpoints as review-required without resetting or rewriting them. Mixed-version writes invalidate trust.
- Durable account/blog post receipts and account-scoped native reply receipts with caller operation IDs, argument fingerprints and explicit unknown outcomes. No automatic resend; interrupted pending operations require human reconciliation.
- Review fixes: resolve canonical/custom destination URLs safely; reject malformed feed/source and write confirmations; preserve native pagination order and refuse overlapping or invalid pages; exclude echoed credential values from stored recovery metadata.
- Selected-blog server-side search/categories; bounded Discover/profile/own-reply reads and public URL conversations. Tokens without the scope URL conversations need get HTTP 403 reported as `reason=insufficient_scope`, with no anonymous fallback.
- Guarded existing-draft publish using reviewed source hash. Human CLI post/upload writes generate and persist an ID before dispatch when omitted; explicit stable IDs still deduplicate exact agent/script retries. Unknown outcomes include a copyable read-only recovery command, and `operation-status --latest` inspects the newest claimed receipt. Rerunning a plain command starts a new operation. MCP still requires IDs; ownership/media/source guards and no-auto-resend behavior remain.
- Reviewed local image preview/upload for CLI and MCP, explicit allowed directory, Pillow decoding/normalization, metadata removal, selected destination, file hash guard and separate upload/post receipts. Alt text accompanies the post; HTTP 202 is labelled accepted/processing.
- Removed combined `--photo` and implicit absolute-path/remote uploads with clear migration errors. `upload` aliases the reviewed relative-file media workflow; dry-run needs no ID.
- Keyword mute and DELETE unmute/unblock contract fixes. Content-index and Homebrew packaging plans documented.
- Read-only mode, structured errors and tool annotations; synthetic Codex-style stdio lifecycle tests and OpenClaw configuration example.
- CLI fixes: refuse truncated inbox/catchup advancement; preserve pipeline record boundaries and `auth --blog`; contain transport failures and expose retry metadata; remove the undeclared Click runtime import uncovered by an isolated wheel install. Draft responses retain their preview link on the initial call.

Installing does not import credentials, register clients, change cron or publish anything. `mb notes`, documented in v1.0, was removed. See [MCP contracts](docs/mcp.md).

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

**Notes** (removed in 2.0) -- Public supplementary notes stored as categorized blog posts. `mb notes add`, `recall` (with `--category` and `--search` filters), `forget`, `categories`, `guide`. Designed to complement an agent's private memory, not replace it.

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
