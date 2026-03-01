# CLAUDE.md — `mb` micro.blog CLI

This file provides context and guidance for Claude Code working on the `mb` project.

## Project Overview

`mb` is a command-line client for [micro.blog](https://micro.blog), designed specifically for **agent use**. The primary consumer is an AI agent (not a human), so the design priorities are:

- Machine-readable JSON output by default
- No interactive prompts — ever
- Composable, pipeable commands
- Clear, structured error responses
- Minimal dependencies

## Architecture

```
mb/
├── cli.py           # Typer entrypoint; registers all command groups
├── config.py        # Load/save ~/.config/mb/config.toml; env var fallback
├── api.py           # HTTP client (httpx); accepts base_url override for testing
├── commands/
│   ├── post.py      # Publishing commands
│   ├── timeline.py  # Reading/discovery commands
│   ├── conversation.py  # Thread fetching
│   └── user.py      # Social graph commands
└── formatters.py    # Output modes: json | human | agent
```

## API Layers

micro.blog exposes two relevant APIs — use the right one for each operation:

- **Micropub** (`POST /micropub`, `GET /micropub?q=*`) — all **write** operations: posting, editing, deleting, listing own posts
- **JSON API** (`/posts/*`, `/users/*`) — all **read** operations: timeline, mentions, user info, discover

Base URL: `https://micro.blog`

Authentication: `Authorization: Bearer <token>` header on every request.

## Configuration

Token resolution order:

1. `MB_TOKEN` environment variable
1. `~/.config/mb/config.toml` → `token` key

Config file format:

```toml
token = "your-app-token"
username = "yourusername"   # cached from whoami at auth time
```

`api.py` must accept a `base_url` parameter (default `https://micro.blog`) to support test mocking without hitting live API.

## Output Contract

**All stdout output is JSON.** No exceptions in non-human mode.

### Success

```json
{ "ok": true, "data": { ... } }
```

### Error

```json
{ "ok": false, "error": "human-readable message", "code": 404 }
```

### Rate Limited

```json
{ "ok": false, "error": "rate_limited", "retry_after": 60 }
```

The `--human` flag switches to `rich`-formatted readable output. The `--format agent` flag on read commands produces a condensed plain-text representation optimized for LLM context window efficiency:

```
[12345] @username (2h): Post content here.
[12346] @other (1h): Reply content here.
```

## Commands Reference

### Auth

```
mb auth <token>          Store token and verify it works
mb whoami                Return username + blog URL as JSON
```

### Post

```
mb post new "<content>"
mb post new --title "<t>" --content "<c>"
mb post new --draft
mb post new --file <path.md>        First # Heading = title
mb post new --photo <path> --alt "<text>"
mb post new --dry-run               Validate without posting
mb post reply <id> "<content>"
mb post delete <id>
mb post list
mb post list --drafts
```

Stdin: `echo "hello" | mb post new -`

### Timeline

```
mb timeline                          Following timeline (default 20)
mb timeline --count N
mb timeline --since <id>
mb timeline --before <id>
mb timeline mentions
mb timeline photos
mb timeline discover
mb timeline discover --collection <name>   e.g. books, music
mb timeline check --since <id>       Returns new_count + poll_interval
```

### Conversation

```
mb conversation <id>     Full thread, recursively fetched to root
```

Fetch logic: call `/posts/conversation?id=<id>`, identify parent posts, recurse until root. Return as a flat ordered array from root → leaf with depth field on each item.

### User

```
mb user show <username>
mb user following <username>
mb user discover <username>
mb user follow <username>
mb user unfollow <username>
mb user is-following <username>
mb user mute <username|keyword>
mb user muting
mb user unmute <id>
mb user block <username>
mb user blocking
mb user unblock <id>
```

### Utilities

```
mb poll --since <id> --interval 30   Emit JSON events to stdout; ctrl-c to stop
mb batch <file.jsonl>                Execute commands from JSONL; return array of results
```

## Key Behaviors

**No interactive prompts.** If required information is missing, exit with a JSON error. Never block on user input.

**Idempotency.** `post new` always returns `{ "id": "...", "url": "..." }` so callers can detect and avoid double-posts on retry.

**Rate limit handling.** On HTTP 429, parse `Retry-After` header if present and include in error response.

**HTML stripping.** API responses contain `content_html`. Strip HTML tags before including in `--format agent` output. In JSON output, return both `content_html` and `content_text` (stripped).

**Stdin support.** Any command accepting `"<content>"` should also accept `-` as content arg, reading from stdin.

## Dependencies

```
typer          # CLI framework
httpx          # HTTP client (sync)
rich           # Human-readable output (--human flag only)
tomllib        # Config parsing (stdlib in Python 3.11+; tomli for older)
```

Keep the dependency footprint minimal. Do not add libraries without a clear reason.

## Testing

- `api.py` accepts `base_url` override — point at a local mock server or `httpx.MockTransport` in tests
- No live API calls in the test suite
- Test fixtures should cover: successful post, draft post, rate limit response, auth failure, multi-item timeline paging

## What This Is NOT

- Not a TUI or interactive client
- Not multi-blog aware (single account, single blog)
- Not a bookmark manager (bookmarks excluded by design)
- Not a moderation tool (report command excluded)
- Not stateful — no local cache, no SQLite, no post history stored locally

## micro.blog API Reference

- JSON API: https://help.micro.blog/t/json-api/97
- Posting (Micropub): https://help.micro.blog/t/posting-api/96
- Auth: https://help.micro.blog/t/authentication/98
