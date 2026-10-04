# Local stdio MCP candidate

MB 2.0 adds a focused MCP interface alongside its existing agent-first CLI. It reuses the HTTP client and shared publishing/thread/mention services; it does not shell out to the CLI. Install the optional extra in a separate environment while reviewing this candidate:

```sh
uv sync --locked --extra mcp
.venv/bin/mb mcp --help
```

For the eventual installed release, use the `mcp` extra. Keep the existing 1.x tool installation until migration has been coordinated. This candidate does not register clients, change credentials or install a schedule.

## Process and authentication

The client launches `mb mcp` and owns its lifetime. Stdout contains MCP protocol messages only. Arguments bind one `--profile`, `--blog`, `--consumer` and optional `--read-only` policy. The process resolves the canonical blog using account verification and Micropub destinations before servicing a tool. A tool cannot replace that identity or provide a token. Configuration/env resolution matches the CLI (`MB_TOKEN`, `MB_BLOG`); the existing credential file is read, never rewritten. No token or OAuth-management tools are exposed.

`--state-file` selects the local SQLite cursor/receipt file, defaulting to `~/.config/mb/mcp-state.sqlite3`. Use the same file for multiple consumers of one account. Consumers have independent read state; post writes deduplicate across consumers by account/blog and operation ID; native reply receipts deduplicate by account across blog profiles. Profile aliases resolving to the same verified identity intentionally share state; different accounts and destinations remain separate. CLI cursors remain independent. SQLite uses mode 0600 and stores checkpoint IDs, revisions, hashed operation arguments and recovery metadata, not authentication or post bodies. Draft preview URLs are returned on the initial call but excluded from durable receipts.

Reads are offloaded from the protocol event loop. Requests are serialized within a process, and mention classification uses at most four HTTP workers. Pending SQLite claims also prevent concurrent writes across cooperating processes. Cancellation cannot abandon an already dispatched write's receipt completion; process termination may leave a pending claim. MCP result envelopes retain `ok`, `data`, `error`, `code` and expose `isError`, recovery fields and structured content. Numeric post IDs are strings. Tool inputs reject unknown fields; tools advertise read/write/destructive annotations.

## Tools and resources

| Tool | Purpose |
| --- | --- |
| `identity` | Verify account and immutable destination |
| `heartbeat` | Compact timeline and recent-mention summary |
| `inbox`, `catchup` | Consumer-scoped attention windows |
| `timeline`, `conversation` | Bounded timeline and native ID/public URL threads |
| `discover`, `profile_get`, `replies` | Bounded account-scoped social reads |
| `blog_search`, `blog_categories` | Selected-blog server-filtered source search/categories |
| `media_preview`, `media_upload` | Reviewed local image workflow |
| `post_publish` | Guarded existing-draft publication |
| `blog_posts`, `post_get` | Recent own posts/drafts and exact source |
| `post_preview` | Validate exact content without publishing |
| `post_create`, `post_reply`, `post_edit`, `post_delete` | One authorized post lifecycle, requiring `operation_id` |
| `checkpoint_ack` | Explicit local acknowledgement of a complete window |
| `operation_status` | Durable receipt and uncertainty recovery |

Resources: `mb://guide` (packaged operational/editorial guidance), `mb://identity` and `mb://discover-collections`. Discovery collections are served as reference data. Broader relationship/moderation commands remain CLI-only.

## Attention contract

Start with `identity`, then `heartbeat`. Use inbox/conversation for a mention that deserves attention; catchup for a fuller timeline read. Follow `next_cursor` until it is absent. Only a complete consumed window receives an `ack_receipt`; pass that to `checkpoint_ack` after reviewing the items. Reads never advance. Receipt revisions prevent stale acknowledgements. Handles expire on process restart or bounded cache eviction, so reread from the durable checkpoint.

The first heartbeat offers a bounded recent baseline. Acknowledging it intentionally starts from the newest returned ID, without claiming historical coverage; a first catchup can page available history. Timeline paging freezes its upper fence and walks backwards until exhaustion, including when the upstream caps a requested page size. Recent mentions and Micropub source listings are finite windows: MB labels that limitation. If the saved inbox checkpoint precedes the available mention window, no acknowledgement is issued. This is an unresolved coverage gap, not proof that there was no activity. Heartbeat's mention sample is separate from inbox acknowledgement. `--read-only` disables remote writes and local acknowledgements.

## Write recovery contract

Preview exact text and destination, obtain the required authorization, and generate one stable operation ID. Persist that ID and exact arguments in the host's task state. The ID is claimed before dispatch; retries return the existing receipt, and changed arguments conflict. A timeout after dispatch or a server error can leave `outcome=unknown`. Query `operation_status`, read back recent posts/source/conversations, and involve the user if evidence cannot settle it. Never automatically retry with a new ID.

If an ID exists in both selected-blog and account-wide native-reply scopes, `operation_status` returns `reason=ambiguous_operation` rather than choosing a receipt. Supply `scope="blog"` or `scope="reply"` to inspect the intended operation (CLI: `mb operation-status ID --scope reply`). Existing receipts need no migration. A native reply's successful HTTP response must contain a positive numeric `id` to count as confirmed; an unidentifiable success remains unknown and is never resent.

Timeline paging preserves Micro.blog's native feed order and uses the last returned ID as its cursor. Unique IDs need not increase in publication order; sorting them can skip or repeat posts. Repeated exclusive boundaries or exhaustion-probe items yield a structured 502. Attention workflows still use numeric checkpoint fences: nonmonotonic pages or backward-page violations refuse acknowledgement because complete coverage cannot be proven. Use plain timeline for inspection; supporting those attention feeds requires a separate checkpoint design change.

Inbox coverage after a saved checkpoint requires that exact ID in the recent mentions window; smaller IDs do not establish chronology. If the anchor is absent, the full bounded window is inspection only and cannot be acknowledged. Earlier checkpoints derived from numeric maxima may already have an uncertain chronological anchor. This update preserves all existing state: review history with the operator before rebaselining or choosing a new consumer, and never reset it automatically.

A process killed between claim and completion leaves a pending receipt and blocks subsequent writes in that scope (the blog for Micropub, the account for native replies). This conservative candidate needs human read-back and local-state repair to reconcile such a claim. It has no automatic reconciliation or operation-reset tool. Separate state files do not coordinate writes. Keep the file, back it up before migration, and do not erase it as a retry workaround. Failed operations also retain their receipt; after resolving the cause, a human may authorize a distinct action with a new ID.

Edit/delete accept exact URLs or native numeric IDs and require that the resolved URL belongs to the selected blog plus a successful Micropub source lookup. The immutable identity retains the native Micropub UID; a unique custom hostname returned for that destination is accepted for post source/edit/delete, and full custom URLs can select it at startup. Ambiguous aliases and path traversal are refused. Replies are native account-scoped operations and prepend the recipient mention. Follow confirmed writes with read-back. Preview does not confer authority to publish.

## Client examples

[Codex configuration](../examples/codex-mcp.toml) uses the documented `mcp_servers` stdio shape. [OpenClaw configuration](../examples/openclaw-mcp.json) uses its `mcp.servers` registry. Both are examples for an operator to review; neither is installed by MB. Replace `/absolute/path/to/mb2/.venv/bin/mb` and the synthetic destination. They start in read-only mode. When an operator enables publishing, host approval policy must still reflect the user's authorized scope.

Codex syntax was checked against [official OpenAI MCP documentation](https://learn.chatgpt.com/docs/extend/mcp?surface=cli). OpenClaw syntax was checked against its installed runtime documentation and [MCP registry documentation](https://docs.openclaw.ai/cli/mcp/registry). A local stdio server only works on a host that can execute its command; cloud-only ChatGPT access requires a separately supported connection, outside this candidate.

## Verification and release boundary

```sh
uv sync --locked --extra mcp
uv run --locked --extra mcp ruff check .
uv run --locked --extra mcp ruff format --check .
uv run --locked --extra mcp mypy src/mb --ignore-missing-imports
uv run --locked --extra mcp pytest -q --cov=mb --cov-fail-under=70
```

Tests use synthetic HTTP and isolated config/state, including a subprocess running the actual `mb mcp` command. Scenarios cover identity, session changes, thread expansion, own recent posts, preview/publish/read-back, complete backlog paging, independent consumers, stale acknowledgements, rates/timeouts, duplicate prevention, read-only mode and deliberately choosing no write. No live posting is needed. Before replacing 1.x, run a coordinated read-only host smoke check and review actual authorization/receipt recovery. No tag or package publication is part of this candidate.

## Bounded additions and images

The candidate now has 23 typed tools. `discover`, `profile_get`, `replies` and URL conversations are account-scoped reads; selected `--blog` does not retarget a social account. `blog_posts`, `blog_search` and `blog_categories` use the verified Micropub destination. Search sends `q=source&filter=QUERY&mp-destination=UID` server-side; counts/category filters apply to that returned window, which is explicitly incomplete. These reads are not a whole-blog audit. Public URL conversations use the fixed Micro.blog `/conversation.js` JSON Feed endpoint, can include Webmentions, and mark 404 as `not_found=true`. Other failures remain errors. The existing credential returns HTTP 403 with `Token missing required scope`; MB now reports `reason=insufficient_scope` with operator guidance. This is a credential grant limitation, not evidence of an empty thread or a wrong URL. No anonymous fallback, User-Agent impersonation, alternate credential or reauthorization is attempted. The public intro target returns HTTP 200 and native conversation reads work. Successful URL-thread retrieval with appropriately scoped credentials remains unverified.

`post_get` includes a `source_hash`. To publish an existing draft, review its exact content/photos/categories and call `post_publish(identifier, source_hash, operation_id)`. MB verifies ownership, rereads source, requires draft status and the unchanged hash, and updates only `post-status` to `published` at the same URL. Retries return the existing receipt before checking the now-published source. This is a pre-dispatch conflict guard; the remote API provides no server-atomic compare-and-swap guarantee, so a concurrent edit between read and write remains possible.

Local MCP images are disabled by default. An operator explicitly starts with `--media-root /absolute/reviewed/images`; tool inputs are relative paths under it. Child symlinks, traversal, absolute paths and nonregular files are refused. Supported inputs are static JPEG/PNG/WebP, at most 20 MiB and 40 megapixels. Pillow decodes and re-encodes pixels, applies orientation and removes metadata/comments/appended bytes. WebP becomes PNG; JPEG is re-encoded. Animation, SVG, arbitrary files, video and remote URL fetching are excluded from this tool.

1. `media_preview(file, alt)` shows format, dimensions, upload byte count, input/upload hashes, alt text and selected destination. Nothing uploads.
2. After authorization for the image/destination, `media_upload(file, alt, sha256, operation_id)` refuses a changed file and claims a receipt before upload. HTTP 202 means accepted (`processing_pending=true`), not confirmed public availability. Timeout/malformed confirmation yields unknown and is never automatically resent. A retry returns its receipt even after the file is gone.
3. Preserve the returned URL and reviewed alt text. Call `post_preview(content, photo_url=URL, photo_alt=ALT, ...)`, then separately authorized `post_create` with a different stable ID. Alt text is sent on the post (`mp-photo-alt`), not only upload. A failed post does not trigger another upload. There is no transactional upload-plus-post API or automatic orphan-upload cleanup.

```sh
mb --media-root ./reviewed --format json media preview image.png --alt "Description"
mb --media-root ./reviewed media upload image.png --alt "Description" --sha256 REVIEWED_SHA --operation-id image-upload-1
mb post new "Caption" --photo-url RETURNED_URL --alt "Description" --operation-id image-post-1
mb post get EXISTING_DRAFT_URL --format json
mb post publish EXISTING_DRAFT_URL --source-hash REVIEWED_HASH --operation-id publish-draft-1
mb operation-status publish-draft-1
```

CLI create/short/reply/edit/delete/publish and upload now require caller-stable `--operation-id` and always use the shared services. Missing IDs refuse before HTTP; none are silently generated. Edit/delete require exact owned URLs or numeric IDs, not legacy slug suffixes. Combined `--photo` refuses before upload; use reviewed media upload and a separate post ID. `mb upload` is a spelling alias for the same reviewed relative-file/hash/alt/ID workflow; implicit absolute paths and remote fetching are removed. See [concrete 1.x migration and adoption steps](migration-2.0.md).

A coordinated real image-to-post test would be valuable before adoption: choose a specifically approved image, destination, caption/alt and draft/publish choice; check availability, source alt and rendered output. No actual image was uploaded or published during verification. See [content-index proposal](content-index-plan.md) and [Homebrew release plan](homebrew-release-plan.md) for proposed subsequent work.

## Compatibility investigation and CLI receipt parity

The documented request is `GET /conversation.js?url=FULL_POST_URL&format=jsonfeed`, with JSON `Accept`. Official Inkwell additionally sends Bearer authorization and requests `read write` when obtaining its token. MB matches the endpoint/auth/query/header shape and uses httpx's normal identifying User-Agent. The live reply is an explicit scope refusal, not a robots/CDN/UA challenge; varying the UA or trying more targets cannot establish access. A separately permitted public fetch confirms the intro target exists, and the existing native profile/conversation routes succeed. MB stops at the refusal; no attempt was made to remove authentication to get around it. [Micro.blog's public scope documentation](https://help.micro.blog/t/indieauth/99) recommends `read` for reading and `read write` for a full client; older tokens may have differing compatibility permissions. The server does not name the exact missing scope, so an operator should review the app grant rather than MB asserting a particular token's scope set or modifying it.

| Surface | Current receipt policy | Remaining difference |
| --- | --- | --- |
| MCP consequential writes | Caller operation ID required | Shared state is required across processes; remote writes are not server-idempotent |
| CLI post create/short/reply/edit/delete/publish and `media upload`/`upload` | Caller operation ID required | Same shared service, guards and receipts as MCP; dry-run remains pure |
| Combined `post ... --photo` and implicit/remote upload | Refused before side effects | Use reviewed media upload and separate post ID; no automatic fetching |
| CLI follows/moderation | Direct API compatibility path | No MCP tools or durable receipt contract in this bounded candidate |
| CLI `post get/list` | Legacy read path | Less identity/coverage enforcement than shared MCP post source; `blog posts/search/categories` use selected-blog services |

The 2.0 compatibility decision is implemented: no legacy direct post/upload escape path remains. Scripts must persist caller IDs/arguments and share their state file with MCP. Receipts do not make remote writes server-idempotent. Pending/unknown operations need read-back and operator reconciliation; there is no automatic reset. See [migration examples and exact adoption gates](migration-2.0.md). Installed 1.1, cron and credentials are unchanged.
