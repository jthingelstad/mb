# MCP server

`mb mcp` is a local stdio MCP server built on the same services as the CLI; it does not shell out to `mb`. The Homebrew formula includes it. With uv, install the extra:

```sh
brew install jthingelstad/tap/mb
# or
uv tool install --from git+https://github.com/jthingelstad/mb 'mb[mcp]'
```

Client setup for Claude Code, Claude Desktop, Codex and OpenClaw is in the [README](../README.md#use-with-claude-and-other-mcp-clients) and [examples/](../examples/).

## Process and authentication

The MCP client launches `mb mcp` and owns its lifetime. Stdout carries only MCP protocol messages. Command-line options bind one identity and policy for the life of the process:

```text
mb [--profile NAME] [--blog BLOG] [--state-file PATH] [--media-root DIR] mcp [--consumer NAME] [--read-only]
```

Before serving any tool, the process verifies the account and resolves the canonical blog from Micropub destinations. Tools cannot switch identity or accept a token. The token comes from `MB_TOKEN` or the selected profile in `~/.config/mb/config.toml`, exactly as for the CLI; the server reads the config file and never writes it. There are no token or OAuth management tools. Desktop apps do not inherit your shell environment, so run `mb auth` first rather than relying on an exported `MB_TOKEN`.

`--consumer` (default `default`) names an independent reader: each consumer has its own attention checkpoints, so several clients can share one account. `--read-only` disables remote writes and local checkpoint acknowledgement.

`--state-file` selects the SQLite file for checkpoints and write receipts, default `~/.config/mb/mcp-state.sqlite3`, created with mode 0600. It stores checkpoint IDs, revisions, hashed operation arguments and recovery metadata; it never stores tokens or post bodies. Use one state file for every CLI script and MCP client that writes to the same account, since separate files cannot coordinate writes. CLI config checkpoints (`mb checkpoint`) are separate from MCP consumer checkpoints.

Requests are serialized within a process, reads run off the protocol event loop, and pending SQLite claims stop concurrent writes across processes sharing a state file. Results keep the CLI envelope (`ok`, `data`, `error`, `code`) and also set `isError`, recovery fields and structured content. Numeric post IDs are decimal strings. Tool inputs reject unknown fields, and every tool carries read, write or destructive annotations.

## Tools and resources

| Tool | Purpose |
| --- | --- |
| `identity` | Verify account, canonical blog, consumer and read-only mode |
| `heartbeat` | Compact timeline and recent-mention summary |
| `inbox`, `catchup` | Consumer-scoped attention windows |
| `timeline`, `conversation` | Bounded timeline; threads by native ID or public URL |
| `discover`, `profile_get`, `replies` | Bounded account-scoped social reads |
| `blog_posts`, `post_get` | Recent own posts and drafts; exact source with `source_hash` |
| `blog_search`, `blog_categories` | Server-side search and categories for the selected blog |
| `post_preview` | Validate exact content and destination without sending |
| `post_create`, `post_reply`, `post_edit`, `post_delete` | Single-post writes; `operation_id` required |
| `post_publish` | Publish a reviewed, unchanged draft |
| `media_preview`, `media_upload` | Reviewed local image workflow |
| `checkpoint_ack` | Acknowledge a fully consumed attention window |
| `operation_status` | Inspect a write receipt |

Resources: `mb://guide` (the packaged operating guide), `mb://identity` and `mb://discover-collections`. Follow, mute and block remain CLI-only. Reconciling an uncertain receipt (`mb operation-status --resolve`) is deliberately CLI-only and human-driven.

## Attention

Start with `identity`, then `heartbeat`. Use `inbox` and `conversation` for mentions that deserve attention and `catchup` for a fuller timeline read. Follow `next_cursor` until it is absent. Only a completely consumed window returns an `ack_receipt`; pass it to `checkpoint_ack` after reviewing the items. Reads never advance a checkpoint. Receipts are revision-checked, so a stale receipt conflicts after another acknowledgement, and retrying the same acknowledgement is harmless. Cursors and receipts live in memory and expire on restart; reread from the durable checkpoint.

The first `heartbeat` returns a bounded recent baseline. Acknowledging it starts from the newest returned item without claiming historical coverage. A first `catchup` can page through available history. Heartbeat's mention sample is informational; `inbox` owns mention progress.

Timeline and attention keep Micro.blog's native feed order. IDs are opaque anchors, not numbers to compare: a newer post can have a smaller ID. A window freezes its newest item as the upper fence and pages back until the feed is exhausted or the exact saved anchor is reached, refusing overlapping pages. The mentions API and Micropub source listings only cover a recent window. If a saved inbox checkpoint is older than that window, the result says `coverage_complete=false` and no acknowledgement is offered: report the gap instead of claiming nothing happened.

Checkpoints acknowledged by this version carry native-order provenance. A saved checkpoint without matching provenance (for example, one written by an older client) is reported with `checkpoint_review_required=true` and `coverage=legacy-checkpoint-review-required`. It can still be inspected but gets no completeness claim or acknowledgement receipt. `mb doctor` lists such checkpoints. To move on, review history around the saved anchor and start a new consumer from a fresh baseline; `mb` never resets or migrates old checkpoints on its own.

## Writes and recovery

1. Read recent posts and the target conversation.
2. Call `post_preview` with the exact content. Preview validates; it does not authorize publishing.
3. Get authorization through the host's normal approval flow.
4. Choose one stable `operation_id` (1 to 128 letters, digits or `_.:-`) and keep it with the exact arguments in the task's own state.
5. Call the write. Read back a confirmed result.

The ID is claimed in the state file before the request is sent. Retrying with the same ID and arguments returns the saved receipt without sending again; the same ID with different arguments conflicts. A timeout or server error after sending can leave `outcome=unknown`. Then call `operation_status`, read back posts, source or the conversation, and involve the person if the evidence is not conclusive. Never resend an uncertain write under a new ID. A failed write keeps its receipt; once the cause is fixed, a new, separately authorized action uses a new ID.

A process killed between claim and completion leaves a `pending` receipt that blocks further writes in its scope. A person resolves it from the CLI after checking micro.blog: `mb operation-status ID --resolve applied|not_applied [--note TEXT]`. That only updates the local receipt. Don't delete the state file to get unstuck.

Receipt scopes: Micropub writes (create, edit, delete, publish, upload) are scoped to the verified account and canonical blog; native replies are scoped to the account across blog profiles. Profile aliases for the same identity share receipts. If an ID exists in both scopes, `operation_status` returns `reason=ambiguous_operation`; pass `scope="blog"` or `scope="reply"` (CLI: `--scope`). A reply only counts as confirmed when the response contains a positive numeric `id`.

Edit, delete and publish take an exact post URL or a native numeric ID. The resolved URL must belong to the selected blog and its Micropub source must load before anything is sent. A custom domain returned for the destination is accepted; ambiguous aliases and path traversal are refused. Replies use the native reply API and prepend the recipient's mention.

To publish a draft, review `post_get` and pass its `source_hash` to `post_publish`. `mb` rereads the source, requires it to still be a draft with the same hash, and changes only `post-status`. The remote API has no compare-and-swap, so an edit landing between that check and the write is still possible.

### CLI and MCP

| Surface | Operation ID | Notes |
| --- | --- | --- |
| MCP writes | Required | Same services, guards and receipts as the CLI |
| CLI `post new/short/reply/edit/delete/publish`, `media upload`, `upload` | Optional; generated (`cli-…`) and saved when omitted | Each plain invocation is a new operation; scripts should pass a stable ID. `--dry-run` sends nothing and records nothing |
| CLI `operation-status --resolve` | Existing ID | Human-only reconciliation; no MCP equivalent |
| CLI follows and moderation | None | Direct API calls without receipts; no MCP tools |
| CLI `post get`, `post list` | n/a | Simpler read path; `blog posts/search/categories` use the selected-blog services |

Receipts prevent duplicate local retries; they do not make micro.blog itself idempotent.

## Images

Local images are disabled unless the server starts with `--media-root DIR`. The path must be absolute; the root itself may be a symlink. Tool inputs are paths relative to it; traversal, absolute paths, symlinks inside the root and non-regular files are refused. Supported types are JPEG, PNG, GIF and WebP up to 20 MiB, and the file's contents must match its extension. Files are uploaded byte for byte: `mb` does not re-encode, rotate, convert or strip metadata, so EXIF and GPS data in the file is published with it. Keep only files that are safe to publish under the media root. Remote URLs are never fetched.

1. `media_preview(file, alt)` reports `file`, `filename`, `mime_type`, `byte_count`, `sha256`, `alt` and the destination. Nothing is uploaded.
2. After authorization, `media_upload(file, alt, sha256, operation_id)` requires the preview's `sha256`, refuses a file that changed since preview, and claims a receipt before uploading. HTTP 202 means accepted and still processing (`processing_pending=true`), not proven public. A retry returns the receipt even if the file is gone.
3. Keep the returned URL and alt text and call `post_preview`/`post_create` with `photo_url` and `photo_alt` under a different operation ID. Alt text is sent with the post. A failed post must not trigger another upload; there is no combined upload-and-post transaction or orphan cleanup.

## Bounded reads

`discover`, `profile_get`, `replies` and URL conversations act as the account; `--blog` does not change them. `blog_posts`, `blog_search` and `blog_categories` use the verified Micropub destination. Search runs server-side (`q=source&filter=QUERY`), and counts and category filters apply to the returned window, which is labelled incomplete. None of these is a whole-blog audit.

Conversations by public URL use Micro.blog's `/conversation.js` JSON Feed endpoint and can include Webmentions. A 404 is reported as `not_found=true`; other failures stay errors. Some app tokens lack the scope this endpoint requires. You then get HTTP 403 with `reason=insufficient_scope`: review the app token's permissions on micro.blog, or use the native numeric conversation ID. `mb` does not retry anonymously or vary its User-Agent.

## Tests

The suite uses synthetic HTTP and isolated config and state, including a subprocess running the real `mb mcp` command over stdio. It covers identity, attention paging and acknowledgement, independent consumers, stale receipts, rate limits and timeouts, duplicate prevention, read-only mode, images and draft publishing. No test touches the live API.
