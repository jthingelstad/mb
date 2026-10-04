---
name: mb-cli
description: Use this skill whenever you are using the mb CLI to read, post, manage follows, or build pipelines against micro.blog. It covers command selection, output modes, public boundaries, and cheap-versus-expensive mb workflows.
---

# mb CLI

Use this skill whenever the task involves `mb`.

## Core rules

- Start most agent sessions with `mb heartbeat`.
- Use `mb inbox` when deciding whether something deserves a reply.
- Use `mb catchup` when you want bounded reading rather than a compact summary.
- Default to `agent` output for exploration and pipelines.
- Use `--format json` only when a downstream step truly needs structured parsing.
- Prefer cheap list/read commands first.
- Make expensive fan-out explicit with `mb lookup ...`.
- Separate read, filter, and write stages when social actions are involved.

## Cheap first, expensive second

Cheap reads:

```bash
mb heartbeat
mb inbox
mb catchup
mb whoami
mb timeline --count 10
mb user following
mb user discover
mb discover --list
mb discover --collection books
```

Explicit enrichment:

```bash
mb user following | mb lookup users --last-post
mb user following | mb lookup users --days-since-posting
```

## Heartbeat workflow

- `mb heartbeat` is the default session-start check for agent use.
- First run is bootstrap mode: a bounded snapshot, not a claim that everything shown is new.
- Later runs compare against `heartbeat_checkpoint`, which is separate from `timeline checkpoint`.
- Heartbeat advances by default; use `mb heartbeat --no-advance` to inspect without saving.
- Use `mb heartbeat --mentions-only` when the task is reply triage rather than broad reading.
- Open full threads only after heartbeat identifies something worth attention.

## Inbox and catchup

- `mb inbox` is the reply-triage surface.
- `mb catchup` is the bounded read-what-is-new surface.
- `mb inbox`, `mb catchup`, and `mb heartbeat` each use separate checkpoints.
- Use `mb checkpoint list` when cursor state is unclear.
- Use `mb checkpoint clear <name>` to reset a stuck workflow cursor.
- Use selective inbox filters for inspection only; do not expect filtered inbox runs to advance the cursor.
- Truncated inbox/catchup results cannot advance; increase the CLI count or use MCP paging plus explicit acknowledgement.
- Pipe inbox items into `mb lookup posts --conversation -` when a thread needs more context.

## Public boundaries

- `mb post ...` creates or edits public content unless the user clearly says otherwise.
- Never put secrets, tokens, private contact details, or hidden strategy into public posts.

## Safe social workflow

Show candidates before acting:

```bash
mb user following | mb lookup users --days-since-posting
mb discover --collection books
mb user discover
```

Act only after the intent is clear:

```bash
... | mb unfollow -
... | mb follow -
```

## Useful command patterns

Session start:

```bash
mb heartbeat
mb heartbeat --no-advance
mb heartbeat --mentions-only
mb heartbeat --count 3 --mention-count 3
mb inbox
mb inbox --reason thread-reply
mb inbox --fresh-hours 24
mb inbox --all
mb inbox --advance
mb catchup
mb catchup --advance
mb checkpoint list
mb checkpoint clear inbox
```

Identity and config:

```bash
mb whoami
mb profiles
mb blogs
```

Posting:

```bash
mb post new "Text"
mb post short "Short text"
mb post new --content "Text"
mb post new --file post.md
mb post short --strict-300 "Short text"
mb post new --dry-run "Text"
mb upload ./image.jpg
mb post new "Text" --photo-url https://cdn.micro.blog/...
mb post edit <id> --content "Updated"
mb post reply <id> "Reply text"
```

Reading:

```bash
mb timeline
mb timeline mentions
mb conversation <id>
mb blog posts
mb blog search "query"
mb discover --list
mb discover --collection books
mb user show <username>
```

Lookup and follow management:

```bash
mb user following | mb lookup users --last-post
mb user following | mb lookup users --days-since-posting
mb lookup posts --post 12345
mb lookup posts --conversation 12345
mb inbox | mb lookup posts --conversation -
mb follow <username|->
mb unfollow <username|->
```

## Candidate 2.0 additions

Use `mb media preview FILE --alt TEXT` under an explicitly selected `--media-root DIR` to review a supported static local image, its normalized payload/hash and verified destination. After authorization, `mb media upload FILE --alt TEXT --sha256 HASH --operation-id ID` returns the image reference; HTTP 202 means accepted but possibly still processing. Attach that URL with `mb post new ... --photo-url URL --alt TEXT --operation-id DIFFERENT_ID`. Preserve IDs/arguments across retries and inspect `mb operation-status ID` after uncertainty. Never repeat an upload merely because creating a post failed.

Post create/reply/edit/delete can opt into shared CLI/MCP receipts with `--operation-id` and `--state-file`. Existing-draft publish requires `mb post get URL --format json`, review of its source, then `mb post publish URL --source-hash HASH --operation-id ID`; no automatic live verification writes. `mb post replies`, `mb user show --count N`, `mb discover --count N` and `mb conversation URL` are account reads. `mb blog posts/search/categories` are selected-blog source reads with bounded coverage, not a complete category audit. `mb user mute WORD --keyword` explicitly mutes a keyword.
