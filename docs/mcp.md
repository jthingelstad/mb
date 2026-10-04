# Local stdio MCP candidate

MB 2.0 adds a focused MCP interface alongside its existing agent-first CLI. It reuses the HTTP client and shared publishing/thread/mention services; it does not shell out to the CLI. Install the optional extra in a separate environment while reviewing this candidate:

```sh
uv sync --locked --extra mcp
.venv/bin/mb mcp --help
```

For the eventual installed release, use the `mcp` extra. Keep the existing 1.x tool installation until migration has been coordinated. This candidate does not register clients, change credentials or install a schedule.

## Process and authentication

The client launches `mb mcp` and owns its lifetime. Stdout contains MCP protocol messages only. Arguments bind one `--profile`, `--blog`, `--consumer` and optional `--read-only` policy. The process resolves the canonical blog using account verification and Micropub destinations before servicing a tool. A tool cannot replace that identity or provide a token. Configuration/env resolution matches the CLI (`MB_TOKEN`, `MB_BLOG`); the existing credential file is read, never rewritten. No token or OAuth-management tools are exposed.

`--state-file` selects the local SQLite cursor/receipt file, defaulting to `~/.config/mb/mcp-state.sqlite3`. Use the same file for multiple consumers of one account. Consumers have independent read state; confirmed writes deduplicate across consumers by account/blog and operation ID. CLI cursors remain independent. SQLite uses mode 0600 and stores checkpoint IDs, revisions, hashed operation arguments and recovery metadata, not authentication or post bodies. Draft preview URLs are returned on the initial call but excluded from durable receipts.

Reads are offloaded from the protocol event loop. Requests are serialized within a process, and mention classification uses at most four HTTP workers. Pending SQLite claims also prevent concurrent writes across cooperating processes. Cancellation cannot abandon an already dispatched write's receipt completion; process termination may leave a pending claim. MCP result envelopes retain `ok`, `data`, `error`, `code` and expose `isError`, recovery fields and structured content. Numeric post IDs are strings. Tool inputs reject unknown fields; tools advertise read/write/destructive annotations.

## Tools and resources

| Tool | Purpose |
| --- | --- |
| `identity` | Verify account and immutable destination |
| `heartbeat` | Compact timeline and recent-mention summary |
| `inbox`, `catchup` | Consumer-scoped attention windows |
| `timeline`, `conversation` | Bounded read and full thread expansion |
| `blog_posts`, `post_get` | Recent own posts/drafts and exact source |
| `post_preview` | Validate exact content without publishing |
| `post_create`, `post_reply`, `post_edit`, `post_delete` | One authorized post lifecycle, requiring `operation_id` |
| `checkpoint_ack` | Explicit local acknowledgement of a complete window |
| `operation_status` | Durable receipt and uncertainty recovery |

Resources: `mb://guide` (packaged operational/editorial guidance), `mb://identity` and `mb://discover-collections`. Discovery collections are served as reference data; the fuller discovery/upload/social surface remains available through the CLI.

## Attention contract

Start with `identity`, then `heartbeat`. Use inbox/conversation for a mention that deserves attention; catchup for a fuller timeline read. Follow `next_cursor` until it is absent. Only a complete consumed window receives an `ack_receipt`; pass that to `checkpoint_ack` after reviewing the items. Reads never advance. Receipt revisions prevent stale acknowledgements. Handles expire on process restart or bounded cache eviction, so reread from the durable checkpoint.

The first heartbeat offers a bounded recent baseline. Acknowledging it intentionally starts from the newest returned ID, without claiming historical coverage; a first catchup can page available history. Timeline paging freezes its upper fence and walks backwards until exhaustion, including when the upstream caps a requested page size. Recent mentions and Micropub source listings are finite windows: MB labels that limitation. If the saved inbox checkpoint precedes the available mention window, no acknowledgement is issued. This is an unresolved coverage gap, not proof that there was no activity. Heartbeat's mention sample is separate from inbox acknowledgement. `--read-only` disables remote writes and local acknowledgements.

## Write recovery contract

Preview exact text and destination, obtain the required authorization, and generate one stable operation ID. Persist that ID and exact arguments in the host's task state. The ID is claimed before dispatch; retries return the existing receipt, and changed arguments conflict. A timeout after dispatch or a server error can leave `outcome=unknown`. Query `operation_status`, read back recent posts/source/conversations, and involve the user if evidence cannot settle it. Never automatically retry with a new ID.

A process killed between claim and completion leaves a pending receipt and blocks subsequent writes on that blog. This conservative candidate needs human read-back and local-state repair to reconcile such a claim. It has no automatic reconciliation or operation-reset tool. Separate state files do not coordinate writes. Keep the file, back it up before migration, and do not erase it as a retry workaround. Failed operations also retain their receipt; after resolving the cause, a human may authorize a distinct action with a new ID.

Edit/delete accept exact URLs or native numeric IDs and require that the resolved URL belongs to the selected blog plus a successful Micropub source lookup. Replies are native account-scoped operations and prepend the recipient mention. Follow confirmed writes with read-back. Preview does not confer authority to publish.

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
