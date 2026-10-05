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
mb doctor --offline
```

Posting:

```bash
mb post new "Text" --operation-id example-1
mb post short "Short text" --operation-id example-2
mb post new --content "Text" --operation-id example-3
mb post new --file post.md --operation-id example-4
mb post short --strict-300 "Short text" --operation-id example-5
mb post new --dry-run "Text"
mb media upload image.jpg --alt "Description" --operation-id example-6
mb post new "Text" --photo-url https://cdn.micro.blog/... --alt "Description" --operation-id example-7
mb post edit <id-or-url> --content "Updated" --operation-id example-8
mb post reply <id-or-url> "Reply text" --operation-id example-9
mb post publish <url> --source-hash HASH --operation-id example-10
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

## Write requirements

- Persist the intended action's `--operation-id` and exact arguments before invoking a write. Reuse both on retries; never generate a fresh ID after an uncertain outcome. Ordinary human CLI use may omit the ID (one is generated and saved per invocation), so a plain rerun is a new write.
- Use one persistent state file (`--state-file`) shared with any MCP client on the same account.
- After `outcome=unknown`, run the printed `mb operation-status ...` command (or `mb operation-status --latest`) and read back from micro.blog. Do not resend. Recording the verified outcome with `mb operation-status ID --resolve applied|not_applied` is the human's decision; propose it, don't run it on your own judgment.
- `mb doctor` lists pending and unknown receipts with resolve hints.
- Edit, delete and publish need an exact owned URL or numeric ID. To publish a draft: `mb post get URL --format json`, review the source, then `mb post publish URL --source-hash HASH --operation-id ID`. Publishing moves the post to a new URL; use the result's `url` afterwards (`draft_url` is the retired one).

## Images

`mb media upload FILE --alt TEXT` uploads a local JPEG, PNG, GIF or WebP (up to 20 MiB) exactly as provided. It does not strip EXIF or GPS metadata; check with the user before uploading a photo that may carry location data. `mb media preview FILE --alt TEXT` shows type, size and sha256 without uploading; pass that `--sha256` to upload to refuse a changed file. HTTP 202 means accepted but possibly still processing. Attach the returned URL with `mb post new ... --photo-url URL --alt TEXT` under a different operation ID. Never repeat an upload merely because creating the post failed. Combined `--photo` and remote-URL uploads are removed.

## Other reads

`mb post replies`, `mb user show NAME --count N`, `mb discover --count N` and `mb conversation URL` are account reads. `mb blog posts/search/categories` are selected-blog reads over a bounded window, not a complete category audit. `mb user mute WORD --keyword` mutes a keyword. Metadata such as `coverage=` and `mb lookup users` errors go to stderr; stdout carries only records.
