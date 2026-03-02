# mb

A command-line client for [micro.blog](https://micro.blog), designed for agent use.

`mb` prioritizes machine-readable JSON output, composable commands, and zero interactive prompts — making it ideal as a tool for AI agents and scripts.

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
| `MB_FORMAT` | Default output format: `json`, `human`, or `agent` |

## Output Formats

All output is JSON by default:

```json
{ "ok": true, "data": { "id": "12345", "url": "https://you.micro.blog/2025/01/01/hello.html" } }
```

Use `--human` for readable output, or `--format agent` for a condensed format optimized for LLM context windows:

```
[12345] @you (2h): Hello from the command line
```

Human users can set `export MB_FORMAT=human` in their shell profile.

## Commands

### Auth & Profiles

```
mb auth <token>              Store and verify a token
mb whoami                    Show current user info
mb profiles                  List configured profiles
mb blogs                     List available blogs
```

### Posting

```
mb post new "Hello world"
mb post new --title "My Post" --content "Body text"
mb post new --draft                          Save as draft
mb post new --file post.md                   Post from file (first # heading = title)
mb post new --photo image.jpg --alt "desc"   Post with photo
mb post new --category tag                   Add category (repeatable)
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
mb timeline check --since <id>   Check for new posts
```

### Conversations

```
mb conversation <id>         Fetch full thread from root to leaf
```

### Users

```
mb user show <username>
mb user following <username>
mb user follow <username>
mb user unfollow <username>
mb user is-following <username>
mb user mute <username>
mb user muting
mb user unmute <id>
mb user block <username>
mb user blocking
mb user unblock <id>
```

### Blog

```
mb blog posts                List your blog posts
mb blog posts --category tag Filter by category
mb blog categories           List categories
mb blog search "query"       Search your posts
```

### Memory

An agent memory system that uses blog posts with categories as storage:

```
mb memory add "Important fact" --category core-memory
mb memory recall --category core-memory
mb memory recall --search "keyword"
mb memory forget <id>        Delete a memory by ID or URL
mb memory categories
mb memory guide              Print the full agent usage guide
```

## Development

```bash
pip install -e ".[dev]"
pytest
```

Tests use `httpx.MockTransport` — no live API calls required.

## License

See [LICENSE](LICENSE) for details.
