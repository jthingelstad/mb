# mb

A command-line client for [micro.blog](https://micro.blog), designed for agent use.

`mb` prioritizes agent-friendly output, composable commands, and zero interactive prompts, making it a good fit for AI agents and scripts.

## Install

Requires Python 3.11+.

```bash
pip install .
```

## Quick Start

```bash
# Authenticate with your micro.blog app token
mb auth YOUR_TOKEN

# Check who you're logged in as
mb whoami

# Post something
mb post new "Hello from the command line"

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
mb --profile work post new "Posted from work blog"
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
- `mb-for-user-delegation`: behavior guidance for agents acting on behalf of a human user's account
- `mb-agent-blogger`: behavior guidance for agents posting on their own account as themselves

Use `mb-cli` whenever an agent is operating the tool. Pair it with exactly one behavior skill depending on whose blog is being managed.

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
mb upload <path-or-url>      Upload an image and return its URL
mb following                 List who you follow
mb follow <username|->       Follow one or more users
mb unfollow <username|->     Unfollow one or more users
mb lookup users --last-post
mb lookup posts --conversation
mb discover --list
mb discover --collection books
```

### Posting

```
mb post new "Hello world"
mb post short "A small thought"
mb post new --title "My Post" --content "Body text"
mb post new --draft                          Save as draft
mb post short --strict-300 "A small thought"
mb post new --file post.md                   Post from file (first # heading = title)
mb post new --photo image.jpg --alt "desc"   Post with photo
mb post new --photo-url https://...          Use a previously uploaded photo URL
mb post new --category tag                   Add category (repeatable)
mb post new --dry-run "Hello world"          Validate without posting
mb post get <id>                             Fetch a post by ID or URL
mb post edit <id> --content "New text"       Edit post content
mb post edit <id> --title "New Title"        Edit post title
mb post edit <id> --category tag             Replace post categories
mb post reply <id> "Reply text"
mb post delete <id>
mb post list
mb post list --drafts
echo "piped content" | mb post new -         Read from stdin
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
mb heartbeat --advance
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
pip install -e ".[dev]"
pytest
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
mb heartbeat --advance

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
img=$(mb upload ./otter.jpg --format json | jq -r '.data.url')
mb post new "An otter for today" --photo-url "$img"

# Short-form publishing for conversational micro.blog posts
mb post short "A small thought for today."
```

## License

See [LICENSE](LICENSE) for details.
