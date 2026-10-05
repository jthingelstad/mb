# Full-blog inventory and category maintenance: proposed follow-on

MB serves both a human using a local agent and an agent managing its own identity. A local content index would make whole-blog audits practical and cheap. A focused inventory milestone should follow the 2.0 bridge and correctness work. This document is a design proposal; no content cache, archive sync or bulk category apply exists in 2.x.

## Verified retrieval contracts

- [Micro.blog creator's Micropub paging example](https://help.micro.blog/t/json-api-paging-and-access-to-pages/2336/2) explicitly uses `q=source&offset=0&limit=50`. Add the verified `mp-destination` to every page. This makes a shared Micropub inventory adapter the first choice; confirm limits, post statuses, page channels, ordering and termination against a known export before promising completeness.
- The [official XML-RPC API](https://help.micro.blog/t/micro-blog-xml-rpc-api/108) explicitly documents `microblog.getPosts(blogID, username, password, count, offset)` and separate `getPages`, with modification dates, categories and status. BlogID comes from RSD discovery; do not assume it equals the Micropub UID. This is a fallback/reference, not a reason to introduce a second authentication flow now.
- [Official exports](https://help.micro.blog/t/exporting-from-micro-blog/557) provide WXR and a Blog Archive ZIP containing all posts and uploads. Replies export separately; macOS can export Markdown with front matter. Use an explicitly supplied export as an independent completeness check or bootstrap. Do not scrape account HTML or invent an undocumented export endpoint.
- Public feeds and native account posts are useful for social reads, but cannot establish selected-blog source completeness, pages, drafts or deletion coverage. Current `blog_posts` and `blog_search` intentionally label their returned window; search never silently scans a local recent sample.

## Stage 1: shared inventory, then a separate index

Build one `inventory` service for CLI/MCP with a bounded page contract, destination identity, remote offsets, counts, source hashes, run ID and coverage. Expose progress and resume incomplete scans; reject repeated/nonprogressing pages, malformed pages and arbitrary limits before marking a run exhausted. Offset pagination has no documented snapshot isolation: insertions/deletions during a scan can shift rows. Deduplicate stable URLs, overlap pages, recheck the leading fence and reconcile with a second pass/export. Label a best-effort exhausted scan as such; do not call it an atomic snapshot.

Use a separate `content.sqlite3`, not the operational `state.sqlite3`. The existing database coordinates attention checkpoints and hashed write receipts and deliberately contains no content. A content index holds private drafts and readable source; use explicit enablement, mode 0600, documented retention/deletion and independent backups. Keep credentials outside both databases.

Suggested schema:

- `accounts` and `blogs`: verified principal + canonical destination UID; profile names are aliases, never isolation keys. Track custom URL aliases separately. A configured profile cannot read another account's index accidentally.
- `sync_runs`: account/blog, selected channel/status coverage, started/completed times, offset/resume state, last remote fence, counts, error/gap, coverage classification and generation.
- `posts`: account/blog + canonical URL, remote IDs as strings, title, content/source JSON, source hash, status, remote modification time when supplied, observed time and last-seen generation. Optional FTS for local query.
- `post_categories`: exact remote labels and post associations. Keep case/Unicode distinctions until a reviewed plan chooses to merge them.
- `plans`/`plan_items`: immutable proposed category changes, before/after labels, source hash, reason, review digest, approval reference and per-item operation ID/result. Link to operational receipts without copying credentials.

Refresh newly published/recent posts cheaply, but old edits are not guaranteed to appear in a recent window. Schedule or explicitly run full reconciliation and report freshness per scope. Missing from an interrupted/filtered/recent scan is never a deletion. Mark a deletion candidate only after a successful unfiltered full scan plus targeted remote confirmation; retain a tombstone and distinguish 404 from authorization/network errors. Do not silently evict drafts or pages excluded by a scan.

## Stage 2: audit -> reviewed plan -> bounded apply

1. Audit a named inventory generation. Report coverage, freshness, counts and representative URLs: near-duplicate categories, case variants, unused labels and uncategorized posts. Recommendations are proposals, not mutations.
2. Produce an explicit immutable plan/diff: each URL, before categories, after categories, source hash and justification. Compute a plan digest and display account/blog, item count and coverage. Export a reviewable JSON/text artifact through the shared CLI/MCP interface.
3. Apply only the specifically approved digest, in small bounded batches with an item cap. Reverify account/destination and fresh Micropub source immediately before each write. On mismatched hash/categories, report a conflict and require a new review; never overwrite unrelated edits from cached source. Send only category replacements, preserving title/content/photo/status. Micro.blog's reviewed API does not supply a server-side compare-and-swap guarantee, so a narrow read/write race remains; document it and use post-write verification.
4. Claim each stable operation ID before dispatch; reuse the current unknown-outcome and duplicate rules. Stop on uncertainty/rate limits/material identity changes. Resume from receipts, not by resending all rows. Refresh each applied row from remote source and retain an audit trail of applied, refused, conflicted and unknown outcomes. Reversal is a new reviewed plan with current remote guards, not an unconditional rollback.

Suggested paired interfaces are `mb inventory sync/status/query`, `mb category audit/plan/apply` and corresponding typed tools calling the same services. Names are proposals, not promises of existing commands. Start with read-only inventory and audit; add approved apply only after completeness/conflict fixtures and real export comparison pass. This should be useful for auditing a real blog without turning the social timeline into a publishing database.
