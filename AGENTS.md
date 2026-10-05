# AGENTS.md

Guidance for coding agents working in `mb`.

## Project Overview

`mb` is a command-line client for [micro.blog](https://micro.blog), designed for agent and script use.

Core priorities:

- Agent output by default
- Agent output is the primary product surface
- No interactive prompts
- Composable, pipeable commands
- Clear structured errors
- Minimal dependencies

## Local Skills

Project-local skills live under `skills/`:

- `skills/mb-cli/SKILL.md`: core `mb` command usage and workflow guidance
- `skills/mb-mcp/SKILL.md`: operating the `mb mcp` stdio tools (identity, attention, acknowledgement, one authorized write)
- `skills/mb-for-user-delegation/SKILL.md`: guidance for acting on behalf of a human user
- `skills/mb-agent-blogger/SKILL.md`: guidance for an agent managing its own blog identity

When working on skill-related requests, keep the operational skills (`mb-cli`, `mb-mcp`) separate from the social/voice rules in the two behavior skills.

## Repository Layout

```text
src/mb/cli.py                   Typer entrypoint, global options, mcp and operation-status
src/mb/api.py                   HTTP client for micro.blog APIs
src/mb/config.py                Config loading/saving and profile support
src/mb/formatters.py            json | human | agent output modes
src/mb/domain.py                Post normalization, thread ordering, mention classification
src/mb/services.py              Shared CLI/MCP services: identity, attention, writes, receipts
src/mb/shapes.py                schema_version, compact MCP results and per-tool output schemas
src/mb/state.py                 SQLite state file: checkpoints and write receipts
src/mb/media.py                 Local image validation for upload
src/mb/mcp_server.py            Optional stdio MCP server (mcp extra only)
src/mb/guidance/                Packaged guidance served as mb://guide
src/mb/commands/catchup.py      New timeline posts since catchup checkpoint
src/mb/commands/checkpoint.py   Checkpoint list/get/set/clear
src/mb/commands/doctor.py       Read-only health check
src/mb/commands/guide.py        `mb guide` workflow text
src/mb/commands/heartbeat.py    Session-start snapshot
src/mb/commands/inbox.py        Attention-oriented mention triage
src/mb/commands/lookup.py       Pipeline enrichment for users and posts
src/mb/commands/media.py        Image preview and upload
src/mb/commands/post.py         Post new/short/get/edit/reply/delete/list/publish/replies
src/mb/commands/timeline.py     Timeline, discover, check, checkpoint
src/mb/commands/conversation.py Conversation thread formatting
src/mb/commands/user.py         User and social graph commands
src/mb/commands/blog.py         Read own posts, categories, search
src/mb/commands/upload.py       `mb upload` alias for media upload
tests/                          Unit and CLI integration tests
scripts/                        Distribution checks run in CI; live_smoke.py (live test account)
```

## API Split

Use the correct API family for the job:

- Micropub: write operations and own-post management
- JSON API: timeline, user, conversation, and other read operations

Default base URL is `https://micro.blog`. `MicroblogClient` accepts `base_url` for tests.

## Config and Resolution Rules

Config lives at `~/.config/mb/config.toml`.

Profiles:

```toml
[default]
token = "app-token"
username = "you"
blog = "https://you.micro.blog/"

[work]
token = "other-token"
username = "you"
blog = "https://work.micro.blog/"
```

Environment variables:

- `MB_TOKEN`: overrides configured token
- `MB_BLOG`: overrides configured default destination
- `MB_FORMAT`: default output format if `--format/--human` is not explicitly set

Resolution order:

1. Token: `MB_TOKEN`, then config profile token
2. Blog destination: `--blog`, then `MB_BLOG`, then config profile blog
3. Format: `--human`, then explicit `--format`, then `MB_FORMAT`, then `agent`

Legacy flat config is still supported for the default profile and auto-migrates on save.

## CLI Surface

CLI post/upload writes go through the shared services and selected-blog guards and generate and persist an operation ID when omitted. Each plain invocation starts a new operation. Agents should supply a caller-stable `--operation-id` and preserve exact arguments across retries; MCP requires an ID. After uncertainty, inspect the printed recovery command or `mb operation-status --latest`; never rerun a plain write as a recovery attempt. A human reconciles a pending/unknown receipt with `mb operation-status ID --resolve applied|not_applied` (CLI only, never exposed over MCP). Combined `--photo` and remote-URL uploads are removed. See [docs/mcp.md](docs/mcp.md) and the README's write-safety section.

Global flags can appear before or after the command:

```text
--profile, -p
--blog, -b
--format, -f
--human
--state-file
--media-root      (absolute path; needed by MCP image tools)
--version, -V
```

Top-level commands:

```text
mb auth                            Guided setup in a terminal: hidden token prompt, blog picker
mb auth -                          Read the token from stdin (mb auth <token> also works)
mb whoami
mb profiles
mb blogs
mb doctor [--offline]
mb guide
mb mcp [--consumer NAME] [--read-only]
mb operation-status ID [--scope blog|reply]
mb operation-status --latest
mb operation-status ID --resolve applied|not_applied [--note TEXT]
mb heartbeat
mb inbox
mb catchup
mb checkpoint list
mb media preview FILE --alt TEXT
mb media upload FILE --alt TEXT [--sha256 HASH] [--operation-id ID]
mb upload FILE --alt TEXT          Alias for media upload
mb following
mb follow <username|->
mb unfollow <username|->
mb lookup users --last-post
mb lookup posts --conversation
mb discover --list
mb discover --collection books
mb conversation <id>
mb poll --since <id> --interval 30
```

Post commands:

```text
mb post new "Hello"
mb post short "Hello"
mb post new --content "Hello"
mb post new --file post.md
mb post new "Draft text" --draft
mb post short --strict-300 "Hello"
mb post new "Caption" --photo-url https://... --alt "desc"   # Upload with media upload first
mb post new "Tagged text" --category tag
mb post new --dry-run "Hello"
mb post get <id-or-url>
mb post edit <id-or-url> --content "Updated"
mb post edit <id-or-url> --title "Updated"
mb post edit <id-or-url> --category tag
mb post reply <id-or-url> "Reply text"
mb post delete <id-or-url>
mb post list
mb post list --drafts
mb post publish <id-or-url> --source-hash HASH
mb post replies
```

Rules:

- `mb post new` accepts exactly one content source: positional content, `--content`, or `--file`
- `mb post short` is the short-form publishing path: no title, content only
- `-` is accepted as content for stdin reads
- Bare numeric IDs for `get/edit/delete` resolve through the conversation API
- Replies use `POST /posts/reply`

Timeline commands:

```text
mb timeline
mb timeline --count 50
mb timeline --since <id>
mb timeline --before <id>
mb timeline mentions
mb timeline photos
mb timeline discover
mb timeline discover --collection books
mb timeline discover --list
mb timeline check --since <id>
mb timeline checkpoint
mb timeline checkpoint <id>
mb checkpoint list
mb checkpoint get inbox
mb checkpoint set heartbeat 12345
mb checkpoint clear heartbeat
```

User commands:

```text
mb user show <username>
mb user discover
mb user discover <username>
mb user following
mb user following <username>
mb user follow <username>
mb user follow -
mb user unfollow <username>
mb user unfollow -
mb user is-following <username>
mb user mute <username-or-keyword>
mb user muting
mb user unmute <id>
mb user block <username>
mb user blocking
mb user unblock <id>
```

User workflow notes:

- `mb user following` defaults to the signed-in user and stays cheap
- expensive per-user enrichment lives under `mb lookup users`
- expensive per-post enrichment lives under `mb lookup posts`
- `mb user discover` defaults to the signed-in user and uses the social discover API
- `mb user follow -` and `mb user unfollow -` read newline-delimited usernames from stdin
- stdin parsing also accepts agent-format post lines and extracts `@username`

Lookup commands:

```text
mb lookup users --last-post <username>
mb lookup users --days-since-posting <username>
mb lookup posts --post <id-or-url>
mb lookup posts --conversation <id-or-url>
mb user following | mb lookup users --last-post
mb user following | mb lookup users --days-since-posting
mb inbox | mb lookup posts --conversation -
```

Top-level convenience aliases:

- `mb following` delegates to `mb user following`
- `mb follow` delegates to `mb user follow`
- `mb unfollow` delegates to `mb user unfollow`
- `mb discover` delegates to topic-based discover posts, equivalent to `mb timeline discover`
- `mb discover --list` prints the curated built-in Discover collection registry

Heartbeat:

```text
mb heartbeat
mb heartbeat --count 3 --mention-count 3
mb heartbeat --mentions-only
mb heartbeat --no-advance
```

Heartbeat notes:

- `mb heartbeat` is a compact session-start snapshot for agents
- it uses a dedicated `heartbeat_checkpoint`, separate from `timeline checkpoint`
- first run is a bounded bootstrap snapshot; later runs compare against the saved heartbeat checkpoint
- checkpoint advances by default after each heartbeat; use `--no-advance` to suppress
- mention items include `thread_count` to help decide whether a thread is worth expanding

Inbox and catchup:

```text
mb inbox
mb inbox --reason thread-reply
mb inbox --fresh-hours 24
mb inbox --all
mb inbox --advance
mb catchup
mb catchup --advance
```

- `mb inbox` is attention-oriented and built from recent mentions plus lightweight thread classification
- `mb catchup` is bounded timeline reading with its own `catchup_checkpoint`
- `mb inbox` uses its own `inbox_checkpoint`
- `mb checkpoint ...` is the first-class cursor management surface for `timeline`, `heartbeat`, `inbox`, and `catchup`
- selective inbox filters are for inspection, not cursor advancement; do not combine `mb inbox --advance` with `--reason`, `--fresh-hours`, or `--max-age-days`
- `mb upload` aliases `media upload`: a local file uploaded unchanged (no metadata stripping), alt text required, optional `--sha256` guard and retry ID; no remote fetching

Blog commands:

```text
mb blog posts
mb blog posts --count 50
mb blog posts --category tag
mb blog categories
mb blog search "query"
```

## Output Contract

Output mode policy:

- `agent` is the primary design target and the default runtime mode
- `human` is a secondary review mode for readable inspection
- `json` is a compatibility and integration layer, not the primary product surface
- New features should be designed agent-first, then made readable in `human`, then exposed completely in `json`
- Do not remove `json`, but also do not let `json` shape the UX of the CLI
- Tests and external integrations may rely on `json`, so keep its envelopes stable when changing commands

Default output is agent mode:

```text
[12345] @username (2h): Post content here.
```

Use `--format json` for structured output:

```json
{ "schema_version": 1, "ok": true, "data": { ... } }
```

Errors:

```json
{ "schema_version": 1, "ok": false, "error": "message", "code": 400 }
```

Rate limits:

```json
{ "schema_version": 1, "ok": false, "error": "rate_limited", "retry_after": 60 }
```

`schema_version` (in `src/mb/shapes.py`) covers CLI JSON and MCP results. Adding a field keeps it; removing, renaming or retyping a field bumps it. MCP reads are compact by default (`verbose: true` returns the full shape); CLI JSON is always full. When a tool's result shape changes, update `DATA_SCHEMAS` and run `uv run python scripts/export_schemas.py` to refresh `docs/mcp-schemas.json`.

`--format agent` prints condensed plain text for list-like reads and threaded conversations. `content_text` is added to JSON list results when `content_html` is present.

Practical implications:

- New command design should start from the best compact agent output
- `human` can remain a thinner presentation layer over the same data
- `json` should remain complete and deterministic, but it does not need to be the most prominent documented mode

## Development

Install:

```bash
uv sync --locked --extra mcp
```

Run the same checks CI uses:

```bash
uv run --locked --extra mcp ruff check .
uv run --locked --extra mcp ruff format --check .
uv run --locked --extra mcp mypy src/mb --ignore-missing-imports
uv run --locked --extra mcp pytest tests/ -q --cov=mb --cov-report=term-missing --cov-fail-under=70
```

Testing guidance:

- Test suite uses `httpx.MockTransport`
- No live API calls should be added to tests
- Favor CLI tests for argument parsing and output behavior
- Favor API tests for transport and response normalization

Live smoke (`.github/workflows/live-smoke.yml`, `scripts/live_smoke.py`) is the only place mb talks to the real micro.blog API in automation. It runs Mondays and on demand (`gh workflow run live-smoke.yml`) in the `live-smoke` environment, whose `MB_TEST_TOKEN` belongs to a dedicated test account (POAPChallenge), never a real blog. It signs in with guided `mb auth` in a pseudo-terminal, runs CLI reads and `mb doctor`, validates every MCP read against its published schema, then creates, edits, publishes and deletes one post on the test blog. Run it before tagging a release. Set the `MB_TEST_BLOG` environment variable if the test account gains a second blog. Never point it at a real account, and never run it on pull requests.


## MCP

`mb mcp` is a local stdio adapter over shared domain/services, not a shell wrapper. The optional `mcp` extra must not enter the base CLI import path (CI checks this). See `docs/mcp.md` for typed contracts and `examples/` for client configuration. Keep operational guidance (`mb-cli`, `mb-mcp`) separate from the two behavior skills. `src/mb/guidance/mcp.md` ships in the wheel and is exposed as `mb://guide`; `mb guide` text lives in `src/mb/commands/guide.py`. Update both when commands change.

Pure MCP reads never advance. Consumer checkpoints are separate from CLI config cursors; only a complete receipt may be acknowledged. Operation IDs and receipts are shared per verified account/blog in one state file. Unknown writes are never auto-resent, and receipt resolution stays a human CLI action. Do not test with live writes, register persistent clients, or touch a real config/state file as part of verification.
