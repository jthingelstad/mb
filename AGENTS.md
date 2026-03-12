# AGENTS.md

Guidance for coding agents working in `mb`.

## Project Overview

`mb` is a command-line client for [micro.blog](https://micro.blog), designed for agent and script use.

Core priorities:

- JSON output by default
- No interactive prompts
- Composable, pipeable commands
- Clear structured errors
- Minimal dependencies

## Repository Layout

```text
src/mb/cli.py                 Typer entrypoint and global options
src/mb/api.py                 HTTP client for micro.blog APIs
src/mb/config.py              Config loading/saving and profile support
src/mb/formatters.py          json | human | agent output modes
src/mb/commands/post.py       Post create/get/edit/reply/delete/list
src/mb/commands/timeline.py   Timeline, discover, check, checkpoint
src/mb/commands/conversation.py Conversation thread formatting
src/mb/commands/user.py       User and social graph commands
src/mb/commands/blog.py       Read own posts, categories, search
src/mb/commands/notes.py      Public supplementary notes workflow
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
3. Format: `--human`, then explicit `--format`, then `MB_FORMAT`, then `json`

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
mb following
mb follow <username|->
mb unfollow <username|->
mb discover --collection books
mb conversation <id>
mb poll --since <id> --interval 30
```

Post commands:

```text
mb post new "Hello"
mb post new --content "Hello"
mb post new --file post.md
mb post new --draft
mb post new --photo image.jpg --alt "desc"
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
mb timeline check --since <id>
mb timeline checkpoint
mb timeline checkpoint <id>
```

User commands:

```text
mb user show <username>
mb user discover
mb user discover <username>
mb user following
mb user following <username>
mb user following --inactive-days 90
mb user following --filter-days 90
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

- `mb user following` defaults to the signed-in user
- `mb user following --inactive-days N` and `--filter-days N` filter the follow list by most recent post date
- `mb user discover` defaults to the signed-in user and uses the social discover API
- `mb user follow -` and `mb user unfollow -` read newline-delimited usernames from stdin
- stdin parsing also accepts agent-format post lines and extracts `@username`

Top-level convenience aliases:

- `mb following` delegates to `mb user following`
- `mb follow` delegates to `mb user follow`
- `mb unfollow` delegates to `mb user unfollow`
- `mb discover` delegates to topic-based discover posts, equivalent to `mb timeline discover`

Blog commands:

```text
mb blog posts
mb blog posts --count 50
mb blog posts --category tag
mb blog categories
mb blog search "query"
```

Notes commands:

```text
mb notes add "Important fact"
mb notes add "Important fact" -c preferences -c notes
mb notes add "Important fact" --title "Title"
mb notes recall
mb notes recall -c preferences
mb notes recall --search "keyword"
mb notes recall --search "keyword" -c preferences
mb notes forget <id-or-url>
mb notes categories
mb notes guide
```

Notes behavior:

- Notes are public blog posts
- `mb notes recall` without `--search` defaults to category `notes`
- `mb notes recall --search ...` searches across all categories unless `-c/--category` is provided
- Notes supplement internal memory; they do not replace it

## Output Contract

Default output is JSON:

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

## Development

Install:

```bash
pip install -e ".[dev]"
```

Run tests:

```bash
.venv/bin/python -m pytest -q
```

Testing notes:

- Test suite uses `httpx.MockTransport`
- No live API calls should be added to tests
- Favor CLI tests for argument parsing and output behavior
- Favor API tests for transport and response normalization
