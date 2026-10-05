"""Agent-oriented workflow guide for mb."""

GUIDE_TEXT = """\
mb guide — workflow reference for agents and humans setting up agents.

SESSION START
  mb heartbeat              Compact snapshot: identity, recent timeline, new mentions.
                            Advances the checkpoint by default (use --no-advance to suppress).
                            Use this to decide if anything needs attention — not to read everything.
  mb inbox                  Attention-oriented mention triage with thread classification.
                            Each item includes thread_count and reason (mention or thread-reply).
                            Use this when heartbeat shows new mentions and you need to decide
                            which threads are worth expanding or replying to.
  mb catchup                Bounded timeline reading since last catchup checkpoint.
                            Use this for a fuller read of what you missed.

  Typical flow: heartbeat -> inbox (if mentions > 0) -> catchup (if you want the full picture).
  Each command has its own checkpoint. They do not interfere with each other.

READING AND DISCOVERY
  mb timeline               Full timeline with --count, --since, --before controls.
  mb timeline mentions      Just mentions from the timeline.
  mb timeline discover      Discover collection posts (--collection books, --list for all).
  mb discover               Top-level alias for timeline discover.
  mb conversation <id>      Expand a full thread. Use this after spotting an interesting post
                            in heartbeat or inbox output.

SELF-REVIEW
  mb blog posts             List your own recent posts (--count, --category).
  mb post list --drafts     List draft posts.
  mb blog search "query"    Search your own post bodies — not the timeline.
  mb post get <id-or-url>   Fetch the exact source of one post, including source_hash.
                            Use this to read back what you wrote before writing something similar.
  mb post replies           Replies you have made recently.
  mb blog categories        List all tags/categories on your blog.

PUBLISHING
  Every write is recorded in the state file before it is sent. Human CLI use may omit
  --operation-id; mb generates and saves one, and each plain invocation is a new operation.
  Agents: choose a stable --operation-id, persist it with the exact arguments before running,
  and reuse both on retries. Never use a fresh ID after an uncertain outcome. Share one
  --state-file across CLI and MCP. Edit/delete/publish need an owned exact URL or numeric ID.
  mb post new --dry-run "x" Validate without posting or recording anything.
  mb post new "Hello" --operation-id TASK_CREATE
                            Create a post. Accepts --title, --file, --draft, --photo-url,
                            --alt, --category. Use this for long-form posts or titles.
  mb post short "Hello" --operation-id TASK_SHORT
                            Short-form post, no title. Optional --strict-300 character limit.
                            If you are unsure which to use, post new is the safe default.
  mb post edit <id-or-url> --content "..." --operation-id TASK_EDIT
                            Edit content, title, or categories on an existing post.
  mb post reply <id-or-url> "text" --operation-id TASK_REPLY
                            Reply to a post natively.
  mb post delete <id-or-url> --operation-id TASK_DELETE
                            Delete a post.
  mb post publish <url> --source-hash HASH --operation-id TASK_PUBLISH
                            Publish an existing draft, only if it is unchanged since post get.

RECOVERY
  mb operation-status ID    Inspect a write receipt (--scope blog|reply if ambiguous).
  mb operation-status --latest
                            Newest receipt for this account/blog.
  outcome=unknown means the write may or may not have happened. Read back from micro.blog
  (post list, blog posts, post replies, the conversation). Never resend under a new ID.
  mb operation-status ID --resolve applied|not_applied --note "what you saw"
                            Human-only: record the verified outcome of a pending/unknown
                            receipt. Changes only the local receipt. Not available over MCP.
  mb doctor                 Read-only health check: install, config, token, state file,
                            pending/unknown receipts with resolve hints. --offline skips network.

SOCIAL GRAPH
  mb user following         List who you follow (cheap, no enrichment).
  mb user follow <name>     Follow a user. Use - to read usernames from stdin.
  mb user unfollow <name>   Unfollow a user. Use - to read from stdin.
  mb user is-following <n>  Check if you follow someone.
  mb user discover          Social discovery suggestions.
  mb user mute/block        Moderation commands (mute, unmute, block, unblock).

PIPELINES
  mb user following | mb lookup users --last-post
      Enrich your follow list with each user's last post date.
  mb user following | mb lookup users --days-since-posting
      Find inactive accounts you follow.
  mb inbox | mb lookup posts --conversation -
      Expand full conversations for inbox items.
  mb user follow -    /  mb user unfollow -
      Pipe newline-delimited usernames or agent-format lines.
      Blank lines and lines starting with # are skipped.

CHECKPOINTS
  mb checkpoint list        Show all saved checkpoints (heartbeat, inbox, catchup, timeline).
  mb checkpoint get <name>  Get a specific checkpoint value.
  mb checkpoint set <n> <v> Manually set a checkpoint.
  mb checkpoint clear <n>   Reset a checkpoint.

UPLOADS
  mb media preview FILE --alt TEXT
                            Check type, size and sha256 without uploading.
  mb media upload FILE --alt TEXT [--sha256 HASH] [--operation-id ID]
                            Upload the file exactly as provided (JPEG, PNG, GIF, WebP;
                            up to 20 MiB). Metadata such as EXIF/GPS is NOT stripped.
                            --sha256 refuses a file that changed since preview.
                            mb upload is an alias. Remote URLs are never fetched.
                            Then post new --photo-url URL --alt TEXT with a separate ID.
                            Never repeat an upload merely because creating the post failed.

MCP
  mb mcp --consumer NAME --read-only
                            Local stdio MCP server for agent hosts. --read-only disables
                            writes and checkpoint acknowledgement. Image tools need a global
                            absolute --media-root DIR. The server serves mb://guide.

OUTPUT FORMATS
  Default is --format agent (compact text for LLM context windows).
  --human for readable tables. --format json for structured envelopes.
  Set MB_FORMAT=json in env to change the default. Records go to stdout; coverage=
  metadata and lookup errors go to stderr. Failed commands exit non-zero.
"""


def run(fmt: str = "agent"):
    """Print the workflow guide."""
    # The guide is plain text by design — same content regardless of format.
    # It's meant to be read, not parsed.
    print(GUIDE_TEXT)
