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
├── config.py        # Load/save ~/.config/mb/config.toml; multi-profile support
├── api.py           # HTTP client (httpx); accepts base_url override for testing
├── commands/
│   ├── post.py      # Publishing commands
│   ├── timeline.py  # Reading/discovery commands
│   ├── conversation.py  # Thread fetching
│   ├── user.py      # Social graph commands
│   ├── blog.py      # Read own blog posts, categories, search
│   └── memory.py    # Agent long-term memory (posts + categories)
└── formatters.py    # Output modes: json | human | agent
```

## API Layers

micro.blog exposes two relevant APIs — use the right one for each operation:

- **Micropub** (`POST /micropub`, `GET /micropub?q=*`) — all **write** operations: posting, editing, deleting, listing own posts
- **JSON API** (`/posts/*`, `/users/*`) — all **read** operations: timeline, mentions, user info, discover

Base URL: `https://micro.blog`

Authentication: `Authorization: Bearer <token>` header on every request.

## Configuration

### Environment variables

| Variable    | Purpose                                  |
|-------------|------------------------------------------|
| `MB_TOKEN`  | Auth token (overrides config file)       |
| `MB_BLOG`   | Default blog destination                 |
| `MB_FORMAT` | Default output format: `json`, `human`, or `agent` |

Human users can add `export MB_FORMAT=human` to their shell profile for readable output by default. CLI flags (`--format`, `--human`) always override the env var.

### Token resolution order

1. `MB_TOKEN` environment variable (overrides everything)
1. `~/.config/mb/config.toml` → profile-specific `token` key

### Blog destination resolution order

1. `--blog` CLI flag
2. `MB_BLOG` environment variable
3. `~/.config/mb/config.toml` → profile-specific `blog` key
4. Account default (first blog)

### Config file format (multi-profile)

```toml
[default]
token = "your-app-token"
username = "yourusername"   # cached from whoami at auth time
blog = "https://yourusername.micro.blog/"

[test]
token = "your-app-token"   # can be same token, different blog
username = "yourusername"
blog = "https://testblog.micro.blog/"
```

Legacy flat format (no sections) is auto-detected and treated as the `default` profile. Saving a new named profile auto-migrates to the sectioned format.

### Global CLI flags

```
--profile, -p    Config profile to use (default: "default")
--blog, -b       Blog destination override (name or URL)
--format, -f     Output format: json | human | agent
--human          Shortcut for --format human
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

### Auth & Profiles

```
mb auth <token>                      Store token and verify it works
mb auth <token> --blog <url>         Store token with a default blog destination
mb auth <token> --profile test       Store under a named profile
mb whoami                            Return username + blog URL as JSON
mb profiles                          List all configured profiles
mb blogs                             List available blogs for the current token
```

### Post

```
mb post new "<content>"
mb post new --title "<t>" --content "<c>"
mb post new --draft
mb post new --file <path.md>        First # Heading = title
mb post new --photo <path> --alt "<text>"
mb post new --category <tag>        Add category (repeatable)
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

### Blog (read own posts)

```
mb blog posts                        List your own blog posts
mb blog posts --count N
mb blog posts --category <tag>       Filter by category
mb blog categories                   List all categories/tags on your blog
mb blog search "<query>"             Search your blog posts
```

### Memory (agent long-term memory)

The memory system uses blog posts with categories as the storage primitive. The agent decides which categories constitute "memory" — there are no hardcoded memory types.

```
mb memory add "<content>"                         Default category: memory
mb memory add "<content>" --category core-memory
mb memory add "<content>" -c preferences -c memory  Multiple categories
mb memory add "<content>" --draft                   Private memory (draft post)
mb memory add "<content>" --title "User prefs"      Titled memory
mb memory recall                                    Recall from "memory" category
mb memory recall --category core-memory             Recall specific category
mb memory recall --search "dark mode"               Search within memories
mb memory recall --count 50                         Control result count
mb memory categories                                List all categories in use
mb memory guide                                     Print agent usage guide
```

The agent is free to create any categories it needs. Example category taxonomy:
- `memory` — general memories
- `core-memory` — important, persistent facts
- `preferences` — user preferences
- `journal` — session logs or reflections
- `context` — conversation context to remember

### Agent Skill Integration

`mb memory guide` outputs a complete usage guide that an agent can consume at session start. This guide covers recommended categories, common patterns (session start/end, corrections, private memories), and best practices. Agents should run this command once to learn the memory system, then use memory commands throughout their session.

**Recommended agent session lifecycle:**

1. **Session start:** `mb memory recall -c core-memory` and `mb memory recall -c preferences` to load context
2. **During session:** Store important facts as they arise with `mb memory add`
3. **Session end:** Persist learnings with appropriate categories

### Utilities

```
mb poll --since <id> --interval 30   Emit JSON events to stdout; ctrl-c to stop
mb batch <file.jsonl>                Execute commands from JSONL; return array of results (deferred)
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
- Not a bookmark manager (bookmarks excluded by design)
- Not a moderation tool (report command excluded)
- Not stateful — no local cache, no SQLite, no post history stored locally

## Known Issues / TODO

- **`mb batch` command** — Spec'd but deferred. Should execute commands from JSONL and return array of results.
- **`mb post reply` bare ID resolution** — `mb post reply 12345 "content"` constructs `https://micro.blog/12345` which is not a valid post URL. Needs API investigation with a live token to determine the correct way to resolve a numeric post ID to a Micropub-compatible URL.
- **CLI integration tests** — No tests exercise commands through Typer's `CliRunner`. Current coverage is at the API client and utility function level (57 tests). Adding CLI-layer tests would catch argument parsing bugs and error output formatting.
- **`get_user` / `get_discover_user` duplication** — Two identical methods in `api.py` both hit `GET /posts/{username}`. Should be deduplicated.
- **Agent output `@name` vs `@username`** — The `--format agent` output uses `author.name` (display name) with an `@` prefix. The `@` convention implies a handle. Should extract username from `author.url` instead, or drop the `@`.
- **TOML value escaping** — `config.py` writes values with simple `f'{key} = "{value}"'`. Tokens or usernames containing quotes or backslashes would produce malformed TOML.

## micro.blog API Reference

- JSON API: https://help.micro.blog/t/json-api/97
- Posting (Micropub): https://help.micro.blog/t/posting-api/96
- Auth: https://help.micro.blog/t/authentication/98
