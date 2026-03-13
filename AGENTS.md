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
- `skills/mb-for-user-delegation/SKILL.md`: guidance for acting on behalf of a human user
- `skills/mb-agent-blogger/SKILL.md`: guidance for an agent managing its own blog identity

When working on skill-related requests, keep the command workflow in `mb-cli` separate from the social/voice rules in the two behavior skills.

## Repository Layout

```text
src/mb/cli.py                 Typer entrypoint and global options
src/mb/api.py                 HTTP client for micro.blog APIs
src/mb/config.py              Config loading/saving and profile support
src/mb/formatters.py          json | human | agent output modes
src/mb/commands/catchup.py    New timeline posts since catchup checkpoint
src/mb/commands/inbox.py      Attention-oriented mention triage
src/mb/commands/post.py       Post create/get/edit/reply/delete/list
src/mb/commands/timeline.py   Timeline, discover, check, checkpoint
src/mb/commands/conversation.py Conversation thread formatting
src/mb/commands/user.py       User and social graph commands
src/mb/commands/blog.py       Read own posts, categories, search
src/mb/commands/upload.py     Image uploads from local files or URLs
tests/                        Unit and CLI integration tests
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

Global flags can appear before or after the command:

```text
--profile, -p
--blog, -b
--format, -f
--human
```

Top-level commands:

```text
mb auth <token>
mb whoami
mb profiles
mb blogs
mb heartbeat
mb inbox
mb catchup
mb checkpoint list
mb upload <path-or-url>
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
mb post new --draft
mb post short --strict-300 "Hello"
mb post new --photo image.jpg --alt "desc"
mb post new --photo-url https://...
mb post new --category tag
mb post new --dry-run "Hello"
mb post get <id-or-url>
mb post edit <id-or-url> --content "Updated"
mb post edit <id-or-url> --title "Updated"
mb post edit <id-or-url> --category tag
mb post reply <id-or-url> "Reply text"
mb post delete <id-or-url>
mb post list
mb post list --drafts
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
mb heartbeat --advance
```

Heartbeat notes:

- `mb heartbeat` is a compact session-start snapshot for agents
- it uses a dedicated `heartbeat_checkpoint`, separate from `timeline checkpoint`
- first run is a bounded bootstrap snapshot; later runs compare against the saved heartbeat checkpoint
- `--advance` saves the newest seen post ID after the snapshot is generated

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
- `mb upload` accepts either a local image path or a remote image URL

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
{ "ok": true, "data": { ... } }
```

Errors:

```json
{ "ok": false, "error": "message", "code": 400 }
```

Rate limits:

```json
{ "ok": false, "error": "rate_limited", "retry_after": 60 }
```

`--format agent` prints condensed plain text for list-like reads and threaded conversations. `content_text` is added to JSON list results when `content_html` is present.

Practical implications:

- New command design should start from the best compact agent output
- `human` can remain a thinner presentation layer over the same data
- `json` should remain complete and deterministic, but it does not need to be the most prominent documented mode

## Development

Install:

```bash
pip install -e ".[dev]"
```

Run tests:

```bash
.venv/bin/python -m pytest -q
```

Testing guidance:

- Test suite uses `httpx.MockTransport`
- No live API calls should be added to tests
- Favor CLI tests for argument parsing and output behavior
- Favor API tests for transport and response normalization
