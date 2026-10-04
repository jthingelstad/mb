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
  mb blog posts             List your own published posts (--count, --category).
  mb blog posts --drafts    List draft posts.
  mb blog search "query"    Search your own post bodies — not the timeline.
  mb post get <id-or-url>   Fetch full content of a single post by ID or URL.
                            Use this to read back what you wrote before writing something similar.
  mb blog categories        List all tags/categories on your blog.

PUBLISHING
  All post writes require --operation-id TASK_ID. Persist ID and exact arguments before
  invocation; reuse both on retries. Never use a fresh ID after uncertainty. Share one
  --state-file across CLI/MCP. Edit/delete require an owned exact URL or numeric ID.
  mb operation-status ID   Inspect a receipt; unknown/pending requires operator read-back.
  Combined --photo is removed; review and upload separately with a different ID.
  mb post new "Hello" --operation-id TASK_CREATE
                            Create a post. Accepts --title, --file, --draft, --photo-url, --category.
                            Use this for long-form posts or posts with titles.
  mb post short "Hello" --operation-id TASK_SHORT
                            Short-form post, no title. Optional --strict-300 character limit.
                            Use this for microblog-style posts (like tweets). If you are unsure
                            which to use, post new is the safe default.
  mb post edit <id> --operation-id TASK_EDIT ...
                            Edit content, title, or categories on an existing post.
  mb post reply <id> "text" --operation-id TASK_REPLY
                            Reply to a post natively.
  mb post delete <id> --operation-id TASK_DELETE
                            Delete a post.
  mb post new --dry-run "x" Validate without posting. Useful for testing content before committing.

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

CHECKPOINTS
  mb checkpoint list        Show all saved checkpoints (heartbeat, inbox, catchup, timeline).
  mb checkpoint get <name>  Get a specific checkpoint value.
  mb checkpoint set <n> <v> Manually set a checkpoint.
  mb checkpoint clear <n>   Reset a checkpoint.

UPLOADS
  mb --media-root DIR media preview FILE --alt TEXT
                            Review a relative static image, hash, alt and destination.
  mb --media-root DIR media upload FILE --alt TEXT --sha256 HASH --operation-id ID
                            Upload the reviewed image; preserve returned URL and receipt.
                            mb upload is an alias with the same required flags.
                            No remote fetch or implicit absolute-path upload.
                            Then post new --photo-url URL --alt TEXT --operation-id POST_ID.
                            Never repeat upload merely because creating the post failed.

OUTPUT FORMATS
  Default is --format agent (compact text for LLM context windows).
  --human for readable tables. --format json for structured envelopes.
  Set MB_FORMAT=json in env to change the default.
"""


def run(fmt: str = "agent"):
    """Print the workflow guide."""
    # The guide is plain text by design — same content regardless of format.
    # It's meant to be read, not parsed.
    print(GUIDE_TEXT)
