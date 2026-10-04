# Adopting the 2.0 candidate

This is a major-version candidate. The installed 1.1 tool, existing credentials and running cron have not been changed. Do not replace their executable until the operator completes the adoption checks below.

## Breaking write changes

All CLI post creation (including `short`), replies, edits, deletes, publishing and media uploads use the same services and receipts as MCP. A caller-stable operation ID is required. MB never silently generates one. An ID has 1–128 letters, digits or `_.:-`. Choose it once for the intended action, persist it with the exact arguments **before invocation**, and reuse both after a retry, restart or transport failure. Changed arguments with the same ID conflict. A new ID means a new action, not a retry.

| 1.1 behavior | 2.0 behavior |
| --- | --- |
| `mb post new "Hello"` sends immediately | Refuses without `--operation-id`; `mb post new "Hello" --operation-id task-42-create` uses a durable receipt |
| `mb post short "Hello"` | Add the stable caller ID; `--dry-run` still works without one and creates no receipt |
| `mb post reply 123 "Thanks"` | `mb post reply 123 "Thanks" --operation-id task-42-reply`; account-scoped receipts deduplicate across selected-blog profiles |
| `mb post edit URL --content "Updated"` | Add `--operation-id task-42-edit`; selected-blog ownership and source lookup must succeed before dispatch |
| `mb post delete URL` | Add `--operation-id task-42-delete`; the same ownership guard applies, even to exact URLs |
| Edit/delete can resolve a slug by suffix from a list | Use an exact post URL or native numeric ID; ambiguous slug resolution is removed from writes |
| `mb post new "Caption" --photo image.jpg` uploads then creates | Refuses before upload, even with an ID. Explicitly review/upload, then create with its URL and a separate ID |
| `mb upload /absolute/image.jpg` or a remote URL | Refuses with migration guidance; no automatic remote fetch. Use a relative image under explicit `--media-root` plus reviewed hash, alt and stable ID |
| `mb upload relative.png` | Alias for `media upload`, with the same required review contract and shared receipt |
| 1.x stateless post writes | Durable local SQLite write receipts; preserve and share the state file across cooperating CLI/MCP processes |

For example, after reviewing and authorizing the image and destination:

```sh
mb --profile work --blog https://work.micro.blog/ --media-root ./reviewed --format json media preview image.png --alt "Reviewed description"
# Save the input sha256 from preview and a caller-stable upload ID in the task record.
mb --profile work --blog https://work.micro.blog/ --media-root ./reviewed media upload image.png --alt "Reviewed description" --sha256 REVIEWED_SHA256 --operation-id task-42-image
# Preserve the returned URL. A post failure must not trigger another upload.
mb --profile work --blog https://work.micro.blog/ post new "Caption" --photo-url RETURNED_URL --alt "Reviewed description" --draft --operation-id task-42-create
mb --profile work --blog https://work.micro.blog/ post get RETURNED_POST_URL --format json
# After separately reviewing/authorizing publication, preserve the returned source_hash.
mb --profile work --blog https://work.micro.blog/ post publish RETURNED_POST_URL --source-hash REVIEWED_SOURCE_HASH --operation-id task-42-publish
mb --profile work --blog https://work.micro.blog/ operation-status task-42-publish
```

Use one explicit `--state-file /absolute/mb-state.sqlite3` for cooperating agents, CLI scripts and MCP clients. The default is `~/.config/mb/mcp-state.sqlite3`. Micropub receipts are verified-account/canonical-blog scoped; profile aliases share receipts while different destinations/accounts remain isolated. Native replies are account-scoped. Consumer names isolate attention checkpoints, not write receipts. Files store hashed arguments and recovery metadata, not authentication or post bodies; retain the caller's exact arguments in its task state. Receipt retries return recovery metadata and may omit rich fields from the first response.

An uncertain result (`outcome=unknown`) or pending claim must never be retried under a fresh ID. Inspect `operation-status`, read back remotely and involve the operator if unresolved. A crashed pending claim blocks later writes in its scope; this candidate has no automatic reconciliation/reset tool. Do not erase the database to make a write run again. After a settled failure, a separately authorized new action may use a new ID. Shared local receipts reduce duplicates; they do not provide remote server-side idempotency or atomic upload-plus-post transactions.

## Remaining differences and blockers

CLI social follows/moderation retain their existing direct API contract and have no MCP receipt tools. Legacy CLI `post get/list` reads remain less strict about identity/coverage than MCP source reads; selected-blog `blog posts/search/categories` already use shared services. CLI heartbeat/cursors retain their existing behavior; MCP reads require explicit acknowledgement. Image upload is restricted to reviewed static JPEG/PNG/WebP and strips metadata through decoding/re-encoding. HTTP 202 means accepted/processing, not proof of public availability.

The existing credential returns `403 Token missing required scope` on URL conversations. Ordinary timeline/native conversation reads work. MB reports the refusal with operator guidance; it does not alter credentials or try anonymous/alternate access. An operator must review the Micro.blog app grant before successful URL-thread retrieval can be verified. The server does not identify the exact missing scope. This remains an adoption blocker for workflows depending on URL threads.

## Exact adoption sequence

1. Review the draft PR and migration impacts. Inventory every post/upload caller, including scheduled scripts; teach each to persist IDs/arguments, preserve receipts, handle `unknown` without blind retries and use explicit media steps. Leave existing 1.1 cron and PATH intact during this work.
2. Back up the existing tool/config and any receipt database through the operator's normal private backup process. Do not copy credentials into logs or task documents. Pick the intended profile/blog and one persistent state file; verify `whoami`/MCP `identity` read-only.
3. Install the reviewed candidate in a separate environment (`uv sync --locked --extra mcp` from the candidate checkout), or an isolated tool environment from a reviewed release archive with the `mcp` extra. Record its absolute executable path. Do not reuse the original `.venv` or replace the active `mb` yet.
4. Launch that executable's `mcp` with the explicit profile/blog/state file, unique consumer and `--read-only`. Run the host's lifecycle/catalog/read smoke checks. Review the existing app grant separately if URL threads are required; verify a successful thread only after the operator resolves that permission boundary.
5. When specifically authorized, coordinate one controlled image/draft/create/publish/read-back check with the chosen image, caption, alt, destination and stable IDs. Check actual media availability, stored alt and rendered output. No live upload/publish was performed for this candidate.
6. Register persistent clients and switch callers/PATH/cron only with coordinated operator approval after those checks. Preserve the 1.1 executable for rollback; stop candidate writers before rollback and retain the receipt database. 1.1 does not consult 2.0 receipts, so rollback cannot blindly replay uncertain candidate actions.
7. Tag/package or implement the proposed Homebrew tap only after release review and its separate install/upgrade/bottle checks. The current draft is unmerged and unpublished; no tap or client registration is installed.
