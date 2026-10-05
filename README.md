# mb

`mb` is a command-line client for [micro.blog](https://micro.blog), built first for AI agents and scripts and still pleasant for people. It reads your timeline, mentions and threads, publishes and edits posts, uploads images and manages follows. Output is compact and pipeable, nothing prompts interactively, and every write gets a durable receipt so an uncertain result can be checked instead of resent. An optional local MCP server (`mb mcp`) exposes the same services to Claude, Codex and other MCP clients as 23 typed tools.

## Install

### Homebrew (recommended)

```bash
brew install jthingelstad/tap/mb
```

The formula includes MCP support. Supported platforms are Apple Silicon Macs on macOS 15 or later, and Linux on x86_64 or arm64 through Homebrew on Linux. Intel Macs and macOS 14 may work but are unsupported, because Homebrew itself no longer ships bottles for them.

### uv

```bash
uv tool install --from git+https://github.com/jthingelstad/mb 'mb[mcp]'
```

Requires Python 3.11 or later. Drop `[mcp]` if you only want the CLI.

### From a checkout (development)

```bash
git clone https://github.com/jthingelstad/mb && cd mb
uv sync --locked --extra mcp
uv run mb --version
```

## Get a token and sign in

1. On micro.blog, open **Account**, go to **Edit Apps** (the app tokens page), and generate a new app token. Menu labels on micro.blog may differ slightly; look for the place that lists app tokens.
2. Give it to `mb` on stdin, so it never lands in your shell history:

   ```bash
   mb auth -            # paste the token, then press Enter and Ctrl-D
   pbpaste | mb auth -  # or pipe it from the clipboard / a password manager
   ```

   `mb auth TOKEN` also works but leaves the token in shell history. Add `--blog https://you.micro.blog/` to set the profile's default blog.
3. Check it:

   ```bash
   mb whoami    # account and blog
   mb doctor    # full read-only health check
   ```

`mb doctor` reports the version, Python and install method, every `mb` on your `PATH` (and which one shadows the others), whether MCP support is importable, config file permissions and profiles, where the token comes from, a live token check with your blogs and the selected destination, the state file and any pending or unknown write receipts (with how to resolve them), legacy checkpoints and the media root. Use `mb doctor --offline` to skip network checks. It exits 1 if anything is an error.

## Quick start

Nothing below publishes until you drop `--draft` or `--dry-run`.

```bash
mb heartbeat                               # what changed since last time
mb inbox                                   # mentions that may deserve a reply
mb timeline --count 10

mb post new --dry-run "Hello from mb"      # validate only, no request sent
mb post new --draft "Hello from mb"        # saved as a draft on micro.blog
mb post list --drafts
```

When you are ready to publish a draft, review it and publish exactly what you reviewed:

```bash
mb post get https://you.micro.blog/2026/10/05/hello.html --format json   # note source_hash
mb post publish https://you.micro.blog/2026/10/05/hello.html --source-hash HASH
```

Or post directly: `mb post new "Hello from mb"`, or `mb post short "A small thought"` for a title-less short post.

## Use with Claude and other MCP clients

`mb mcp` runs a local stdio MCP server. The client starts the process; nothing listens on the network. Start in `--read-only` mode, which disables remote writes and also local checkpoint acknowledgement (`checkpoint_ack`). Run `mb auth` first: the server uses your saved profile, and desktop apps do not inherit your shell environment, so an exported `MB_TOKEN` will not reach them.

**Claude Code:**

```bash
claude mcp add mb -- mb mcp --consumer claude-code --read-only
```

**Claude Desktop:** add this to `claude_desktop_config.json` (also in [examples/claude-desktop.json](examples/claude-desktop.json)). Use the absolute path to `mb`: `/opt/homebrew/bin/mb` on Apple Silicon Homebrew, `/home/linuxbrew/.linuxbrew/bin/mb` on Linux, or whatever `command -v mb` prints.

```json
{
  "mcpServers": {
    "mb": {
      "command": "/opt/homebrew/bin/mb",
      "args": ["mcp", "--consumer", "claude-desktop", "--read-only"]
    }
  }
}
```

**Codex and OpenClaw:** see [examples/codex-mcp.toml](examples/codex-mcp.toml) and [examples/openclaw-mcp.json](examples/openclaw-mcp.json).

To allow writes, remove `--read-only` deliberately and keep your client's tool approval prompts on; every MCP write needs a caller-chosen `operation_id`. Image tools are off unless you add a global `--media-root` with an absolute path before `mcp`, for example `"args": ["--media-root", "/Users/you/mb-images", "mcp", "--consumer", "claude-desktop"]`; the server can then read only files inside that directory. Each `--consumer` name keeps its own read checkpoints, so two clients can share one account without stealing each other's progress (the default consumer is `default`).

See [docs/mcp.md](docs/mcp.md) for the tool list and contracts. The server also serves its own operating guide as the `mb://guide` resource.

## Configuration

`mb auth` writes `~/.config/mb/config.toml` with owner-only (0600) permissions. Each table is a profile:

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

Select one with `--profile work` (or `-p work`); add a profile with `mb --profile work auth -`. `--blog` picks a destination for one command when an account has several blogs (`mb blogs` lists them).

| Variable | Purpose |
| --- | --- |
| `MB_TOKEN` | Token; overrides the profile's token |
| `MB_BLOG` | Default blog destination; `--blog` still wins |
| `MB_FORMAT` | Default output format: `agent`, `json` or `human` |

Write receipts and MCP read checkpoints live in `~/.config/mb/mcp-state.sqlite3` (0600). Use `--state-file PATH` to choose another file, and point every CLI script and MCP client that writes to the same account at the same file.

## Output formats

The default `agent` format is compact plain text, one line per item:

```text
[123456789] @you (2h): Hello from the command line
```

`--human` (or `MB_FORMAT=human`) prints readable tables. `--format json` prints a stable envelope for scripts:

```json
{
  "ok": true,
  "data": {
    "url": "https://you.micro.blog/2026/10/05/hello.html"
  },
  "operation_id": "cli-4889061347a74f679d58bacc1075c6a1",
  "outcome": "applied"
}
```

That is what `mb post new` returns. Address the new post by its `url` when you edit, publish or delete it later (`id` appears only when micro.blog returns a real numeric ID). Errors look like `{"ok": false, "error": "...", "code": 400}`; rate limits add `retry_after`. Records go to stdout. Metadata lines such as `coverage=`, and per-item errors from `mb lookup users` and `mb lookup posts`, go to stderr (those commands exit 1 if any lookup failed) so the next pipeline stage only sees records. A failed command exits non-zero.

## Command reference

Global options go before or after the command:

```text
-p, --profile NAME     Config profile (default: default)
-b, --blog BLOG        Blog destination, name or URL
-f, --format FORMAT    agent | json | human
--human                Same as --format human
--state-file PATH      Shared write receipts and MCP checkpoints
--media-root DIR       Absolute directory the MCP server may read images from
-V, --version          Print the version
--help                 Help for any command
```

**Setup and diagnostics**

```text
mb auth -|TOKEN [--blog URL]        Save and verify a token (prefer -, read from stdin)
mb whoami                           Signed-in account and blog
mb profiles                         Configured profiles
mb blogs                            Blogs this token can post to
mb doctor [--offline]               Read-only health check; exit 1 on any error
mb guide                            Workflow guide for agents
mb mcp [--consumer NAME] [--read-only]   Run the stdio MCP server
```

**Attention and reading**

```text
mb heartbeat [-n N] [--mention-count N] [--mentions-only] [--no-advance]
mb inbox [-n N] [--reason mention|thread-reply] [--fresh-hours H] [--max-age-days D] [--all] [--advance]
mb catchup [-n N] [--advance]
mb timeline [-n N] [--since ID] [--before ID]
mb timeline mentions | photos
mb timeline discover [-c COLLECTION] [--list] [-n N]
mb discover [-c COLLECTION] [--list] [-n N]      Same as timeline discover
mb timeline check --since ID                    Count new posts since an ID
mb timeline checkpoint [ID]                     Read or save the timeline checkpoint
mb poll --since ID [--interval SECONDS]         Stream JSON events until Ctrl-C
mb conversation ID|URL                          Full thread, root to leaf
```

**Checkpoints** (for heartbeat, inbox, catchup and timeline)

```text
mb checkpoint list
mb checkpoint get NAME
mb checkpoint set NAME ID
mb checkpoint clear [NAME] [--all]
```

**Posts**

```text
mb post new [TEXT|-] [--content TEXT] [--file post.md] [-t TITLE] [--draft]
            [--photo-url URL --alt TEXT] [-c CATEGORY]... [--dry-run] [--operation-id ID]
mb post short [TEXT|-] [same options, no title] [--strict-300]
mb post get ID|URL                              Includes source_hash
mb post edit ID|URL [--content TEXT] [-t TITLE] [-c CATEGORY]... [--operation-id ID]
mb post reply ID|URL TEXT|- [--operation-id ID]
mb post delete ID|URL [--operation-id ID]
mb post publish ID|URL --source-hash HASH [--operation-id ID]   Publish a reviewed draft
mb post list [--drafts]
mb post replies [-n N]                          Replies you have made
```

`post new` takes exactly one content source; with `--file`, a leading `# Heading` becomes the title. `-` reads from stdin.

**Images**

```text
mb media preview PATH --alt TEXT                 Check type, size and sha256; uploads nothing
mb media upload PATH --alt TEXT [--sha256 HASH] [--operation-id ID]
mb upload PATH --alt TEXT [--sha256 HASH] [--operation-id ID]        Alias
```

**Your blog** (selected destination)

```text
mb blog posts [-n N] [-c CATEGORY]
mb blog categories
mb blog search QUERY [-n N] [-c CATEGORY]
```

**People**

```text
mb user show USERNAME [-n N]
mb user following [USERNAME]          Also: mb following
mb user discover [USERNAME]           Accounts they follow that you do not
mb user follow USERNAME|-             Also: mb follow
mb user unfollow USERNAME|-           Also: mb unfollow
mb user is-following USERNAME
mb user mute VALUE [--keyword]
mb user muting
mb user unmute ID
mb user block USERNAME
mb user blocking
mb user unblock ID
```

**Lookups** (explicit, slower enrichment for pipelines)

```text
mb lookup users [USERNAME...] [--last-post] [--days-since-posting] [--concurrency N]
mb lookup posts [ID|URL...] [--post] [--conversation] [--concurrency N]
```

**Write receipts**

```text
mb operation-status ID [--scope blog|reply]
mb operation-status --latest [--scope blog|reply]
mb operation-status ID --resolve applied|not_applied [--scope blog|reply] [--note TEXT]
```

## Write safety and recovery

Every post, reply, edit, delete, publish and upload is recorded in the state file before it is sent. If you don't pass `--operation-id`, `mb` generates one (`cli-` plus 32 hex characters), saves it, and prints it with the result. Running the same plain command twice is two operations and can post twice; `mb` never deduplicates by content.

Scripts and agents should choose a stable ID instead (1 to 128 letters, digits or `_.:-`), store it with the exact arguments before running the command, and reuse both on any retry. A retry with the same ID and arguments returns the saved receipt without sending again; the same ID with different arguments is refused.

When a write times out or the server's answer is unclear, the receipt says `outcome=unknown` and `mb` prints a copyable `mb operation-status ...` command. Then:

1. Inspect the receipt: `mb operation-status ID`, or `mb operation-status --latest` for the newest one in this account and blog.
2. Check micro.blog itself (`mb post list`, `mb blog posts`, `mb post replies`, the conversation) to see whether the write happened.
3. Record what you found: `mb operation-status ID --resolve applied` or `--resolve not_applied`, optionally with `--note "seen on the blog at 10:42"`. This only updates the local receipt; it changes nothing on micro.blog. Resolution is a human step and is not available over MCP.

A process killed mid-write can leave a `pending` receipt, which blocks further writes in that scope until it is resolved. `mb doctor` lists pending and unknown receipts with the command to resolve each. Don't delete the state file to get unstuck, and don't rerun an uncertain write under a new ID.

Images are uploaded exactly as provided: `mb` does not re-encode, resize, rotate, convert or strip anything. **EXIF and GPS metadata in the file is uploaded as-is**, so if you care about location data, strip it before uploading. Supported types are JPEG, PNG, GIF and WebP up to 20 MiB, and the file's contents must match its extension. Remote URLs are never fetched. Pass `--sha256` from `media preview` to have the upload refused if the file changed since you looked at it. Upload and post are separate operations, so a failed post never re-uploads the image:

```bash
mb media upload otter.jpg --alt "An otter on a rock"
mb post new "Otter of the day" --photo-url URL_FROM_UPLOAD --alt "An otter on a rock"
```

## Pipelines

```bash
# Expand the threads behind inbox items
mb inbox | mb lookup posts --conversation -

# Latest post from everyone you follow
mb user following | mb lookup users --last-post

# Unfollow accounts quiet for more than 90 days: review the list first, then act
mb user following | mb lookup users --days-since-posting \
  | awk '$2 ~ /^inactive_days=/ && substr($2, 15) + 0 > 90 { print $1 }' > quiet.txt
cat quiet.txt
mb unfollow - < quiet.txt

# Follow the authors of book posts that mention poetry, after reviewing them
mb discover --collection books --count 50 | grep -i poetry > poets.txt
mb follow - < poets.txt
```

`follow -` and `unfollow -` read one name per line and also accept agent-format post lines, taking the author's `@username`. Blank lines and lines starting with `#` are skipped, so you can comment out names in a reviewed file.

## Skills for agents

`skills/` holds agent skills. Use one operational skill, `mb-cli` (CLI) or `mb-mcp` (MCP), plus exactly one behavior skill: `mb-for-user-delegation` when acting for a person, or `mb-agent-blogger` when the agent posts on its own blog. Copy or symlink the folders into your agent's skills directory.

## Development

```bash
uv sync --locked --extra mcp
uv run --locked --extra mcp ruff check .
uv run --locked --extra mcp ruff format --check .
uv run --locked --extra mcp mypy src/mb --ignore-missing-imports
uv run --locked --extra mcp pytest tests/ -q --cov=mb --cov-report=term-missing --cov-fail-under=70
```

Tests use `httpx.MockTransport`; nothing touches the live API. See [AGENTS.md](AGENTS.md) for repository conventions, [RELEASE.md](RELEASE.md) for release notes, [docs/migration-2.0.md](docs/migration-2.0.md) if you used 1.x, and the design notes on [Homebrew packaging](docs/homebrew-release-plan.md) and a proposed [content index](docs/content-index-plan.md).

## License

MIT. See [LICENSE](LICENSE).
