# mb

A bridge to [micro.blog](https://micro.blog), designed for agents: an agent-first CLI and an optional local stdio MCP server.

`mb` prioritizes agent-friendly output, composable commands, and zero interactive prompts, making it a good fit for AI agents and scripts.

The 2.0 release candidate adds 23 typed tools, explicit acknowledgement, shared write receipts, reviewed local images, guarded draft publishing and bounded discovery/search reads. All post/upload writes require caller-stable operation IDs; combined photo posting and remote fetching are removed. See [MCP setup and contracts](docs/mcp.md) and [2.0 migration and adoption](docs/migration-2.0.md).

## Install

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```bash
uv tool install .
```

## Quick Start

```bash
# Authenticate with your micro.blog app token
mb auth YOUR_TOKEN

# Check who you're logged in as
mb whoami

# Post something
mb post new "Hello from the command line" --operation-id example-1

# Read your timeline
mb timeline
```

## Configuration

`mb` stores configuration in `~/.config/mb/config.toml` and supports multiple profiles:

```toml
[default]
token = "your-app-token"
username = "you"
blog = "https://you.micro.blog/"

[work]
token = "another-token"
username = "you"
blog = "https://work.micro.blog/"
```

Switch profiles with `--profile`:

```bash
mb --profile work post new "Posted from work blog" --operation-id example-2
```

### Environment Variables

| Variable    | Purpose                                    |
|-------------|--------------------------------------------|
| `MB_TOKEN`  | Auth token (overrides config file)         |
| `MB_BLOG`   | Default blog destination                   |
| `MB_FORMAT` | Default output format override: `agent`, `json`, or `human` |

## Output Formats

Agent output is the default:

```text
[12345] @you (2h): Hello from the command line
```

Use `--format json` for structured output:

```json
{ "ok": true, "data": { "id": "12345", "url": "https://you.micro.blog/2025/01/01/hello.html" } }
```

Use `--human` for readable output. `--format agent` is still available explicitly, but it is also the default.

Human users can set `export MB_FORMAT=human` in their shell profile. Scripts that require machine-readable output should pass `--format json`.

## Project Skills

This repo includes local skills for agents using `mb`. The intended split is:

- `mb-cli`: the base operational skill for using the CLI safely and effectively
- `mb-mcp`: the operational skill for typed stdio tools and explicit acknowledgement
- `mb-for-user-delegation`: behavior guidance for agents acting on behalf of a human user's account
- `mb-agent-blogger`: behavior guidance for agents posting on their own account as themselves

Use `mb-cli` for CLI operations or `mb-mcp` for MCP operations. Pair it with exactly one behavior skill depending on whose blog is being managed.

Examples:

```text
Human-delegation case:
  use mb-cli + mb-for-user-delegation
  Example: an agent drafts, reviews, and manages follows for Jamie's account

Agent-owned blog case:
  use mb-cli + mb-agent-blogger
  Example: Otto reads, posts, and curates follows for Otto's own blog
```

This separation keeps command usage, social norms, and authorship boundaries distinct. The CLI skill explains how to use `mb`; the behavior skills explain how to behave on micro.blog in each role.

### OpenClaw Setup

In OpenClaw, the simplest way to use multiple skills is to make them available in the specific agent's workspace. There is no special "compose these two skills" syntax. You give an agent access to both skill folders, and OpenClaw loads them together.

Recommended layout:

```text
~/openclaw/workspaces/jamie-assistant/skills/
  mb-cli/
  mb-for-user-delegation/

~/openclaw/workspaces/otto/skills/
  mb-cli/
  mb-agent-blogger/
```

One way to set that up from this repo is with symlinks:

```bash
mkdir -p ~/openclaw/workspaces/jamie-assistant/skills
mkdir -p ~/openclaw/workspaces/otto/skills

ln -s /Users/jamie/Projects/mb/skills/mb-cli ~/openclaw/workspaces/jamie-assistant/skills/mb-cli
ln -s /Users/jamie/Projects/mb/skills/mb-for-user-delegation ~/openclaw/workspaces/jamie-assistant/skills/mb-for-user-delegation

ln -s /Users/jamie/Projects/mb/skills/mb-cli ~/openclaw/workspaces/otto/skills/mb-cli
ln -s /Users/jamie/Projects/mb/skills/mb-agent-blogger ~/openclaw/workspaces/otto/skills/mb-agent-blogger
```

This gives each agent the same core `mb-cli` skill, but only one behavior skill:

- Jamie's delegate agent uses `mb-cli` plus `mb-for-user-delegation`
- Otto uses `mb-cli` plus `mb-agent-blogger`

Avoid loading both behavior skills into the same agent, because they imply different authority and voice rules.

If you prefer shared install locations, OpenClaw can also load skills from global directories such as `~/.openclaw/skills` or paths listed in `skills.load.extraDirs`. Per-agent workspaces are still the better fit when different agents need different behavior.

## Commands

### MCP

```text
mb mcp --consumer dot --read-only
mb --profile work --blog https://work.micro.blog/ mcp --consumer openclaw
```

Install the optional `mcp` extra first. [Client examples](docs/mcp.md#client-examples) are provided for review; MB does not register them or change the existing installation.

### Auth & Profiles

```
mb auth <token>              Store and verify a token
mb whoami                    Show current user info
mb profiles                  List configured profiles
mb blogs                     List available blogs
mb heartbeat                 Compact agent session snapshot
mb inbox                     Attention-oriented mention triage
mb catchup                   New timeline posts since last catchup
mb checkpoint list           List saved workflow checkpoints
mb media preview FILE --alt TEXT   Review under explicit --media-root DIR
mb following                 List who you follow
mb follow <username|->       Follow one or more users
mb unfollow <username|->     Unfollow one or more users
mb lookup users --last-post
mb lookup posts --conversation
mb discover --list
mb discover --collection books
```

### Posting

Example IDs below illustrate caller-assigned task IDs. Persist each intended action's ID and exact arguments before invocation and reuse both on retries. Use one shared state file for CLI/MCP. See [migration guidance](docs/migration-2.0.md).

```
mb post new "Hello world" --operation-id example-3
mb post short "A small thought" --operation-id example-4
mb post new --title "My Post" --content "Body text" --operation-id example-5
mb post new --draft "Draft text" --operation-id example-6             Save as draft
mb post short --strict-300 "A small thought" --operation-id example-7
mb post new --file post.md --operation-id example-8                   Post from file (first # heading = title)
mb --media-root ./reviewed media preview image.jpg --alt "desc"  # Upload separately after review
mb post new "Caption" --photo-url https://... --operation-id example-9          Use a previously uploaded photo URL
mb post new "Tagged text" --category tag --operation-id example-10                   Add category (repeatable)
mb post new --dry-run "Hello world"          Validate without posting
mb post get <id>                             Fetch a post by ID or URL
mb post edit <id> --content "New text" --operation-id example-11       Edit post content
mb post edit <id> --title "New Title" --operation-id example-12        Edit post title
mb post edit <id> --category tag --operation-id example-13             Replace post categories
mb post reply <id> "Reply text" --operation-id example-14
mb post delete <id> --operation-id example-15
mb post list
mb post list --drafts
echo "piped content" | mb post new - --operation-id example-16         Read from stdin
```

### Timeline

```
mb timeline                  Your following timeline
mb timeline --count 50       Control result count
mb timeline mentions         Your mentions
mb timeline photos           Photo timeline
mb timeline discover         Discover feed
mb timeline discover --list  List curated Discover collections
mb discover --collection books Topic discover feed alias
mb timeline check --since <id>   Check for new posts
mb timeline checkpoint           Print saved checkpoint ID
mb timeline checkpoint <id>      Save checkpoint ID to config
mb checkpoint list
mb checkpoint get inbox
mb checkpoint clear inbox
mb heartbeat --count 3 --mention-count 3
mb heartbeat --mentions-only
mb heartbeat
mb inbox --count 10
mb inbox --reason thread-reply
mb inbox --fresh-hours 24
mb inbox --all
mb inbox --advance
mb catchup --count 20
mb catchup --advance
```

### Conversations

```
mb conversation <id>         Fetch full thread from root to leaf
```

### Users

```
mb user show <username>
mb user discover                Social suggestions from your network
mb user discover <username>     Social suggestions seeded from another user's follows
mb user following               List who you follow
mb user following <username>    List who another user follows
mb user follow <username>
mb user follow -                Read usernames from stdin, one per line
mb user unfollow <username>
mb user unfollow -              Read usernames from stdin, one per line
mb user is-following <username>
mb user mute <username|keyword>
mb user muting
mb user unmute <id>
mb user block <username>
mb user blocking
mb user unblock <id>
```

### Lookup

```
mb lookup users --last-post <username>
mb lookup users --days-since-posting <username>
mb lookup posts --post <id-or-url>
mb lookup posts --conversation <id-or-url>
mb user following | mb lookup users --last-post
mb user following | mb lookup users --days-since-posting
mb inbox | mb lookup posts --conversation -
```

### Blog

```
mb blog posts                List your blog posts
mb blog posts --category tag Filter by category
mb blog categories           List categories
mb blog search "query"       Search your posts
```

## Development

```bash
uv sync --locked --extra mcp
uv run --locked --extra mcp ruff check .
uv run --locked --extra mcp ruff format --check .
uv run --locked --extra mcp mypy src/mb --ignore-missing-imports
uv run --locked --extra mcp pytest tests/ -q --cov=mb --cov-report=term-missing --cov-fail-under=70
```

Tests use `httpx.MockTransport` — no live API calls required.

Pipeline examples:

```bash
# Start an agent session with a bounded snapshot
mb heartbeat

# See what likely deserves a reply
mb inbox

# Focus only on fresh thread replies, without advancing the cursor
mb inbox --reason thread-reply --fresh-hours 24

# Read what is new on the timeline since the last catchup cursor
mb catchup

# Inspect or reset agent workflow checkpoints
mb checkpoint list
mb checkpoint clear heartbeat

# Check for new activity and advance the heartbeat cursor
mb heartbeat

# Check the inbox and advance that cursor
mb inbox --advance

# Inspect the full thread behind an inbox item
mb inbox --count 1 | mb lookup posts --conversation -

# Inspect the latest post from everyone you follow
mb user following | mb lookup users --last-post

# Add inactivity metadata, then filter and unfollow in a later pipeline stage
mb user following | mb lookup users --days-since-posting | awk '{split($2,a,"="); if (a[2] > 90) print $1}' | mb unfollow -

# Discover topic posts, filter them, then follow the authors mentioned in the post lines
mb discover --collection books --format agent | grep topic | mb follow -

# Social suggestions from your network remain available under user discover
mb user discover --format agent

# Browse the curated Discover collections before choosing one
mb discover --list

# Upload an image first, then attach it to a post
mb --media-root ./reviewed media preview otter.jpg --alt "An otter beside the water"
# Save the reviewed hash; upload and save its returned URL before creating the post.
mb --media-root ./reviewed media upload otter.jpg --alt "An otter beside the water" --sha256 REVIEWED_SHA --operation-id otter-upload-1
img=RETURNED_UPLOAD_URL
mb post new "An otter for today" --photo-url "$img" --alt "An otter beside the water" --operation-id example-17

# Short-form publishing for conversational micro.blog posts
mb post short "A small thought for today." --operation-id example-18
```

## License

See [LICENSE](LICENSE) for details.

Proposed next stages: [full-blog inventory and category maintenance](docs/content-index-plan.md) and [Homebrew distribution](docs/homebrew-release-plan.md).
