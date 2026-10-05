# Upgrading from 1.x

`mb` 2.0 keeps the 1.x read commands, config file and output envelopes. The changes are in writes, images and a few removed commands. Your `~/.config/mb/config.toml` and its profiles work unchanged.

## What changed

| 1.x | 2.x |
| --- | --- |
| Post writes were stateless | Every post, reply, edit, delete, publish and upload is recorded in a local state file (`~/.config/mb/mcp-state.sqlite3`) before it is sent. `--operation-id` is optional in the CLI; one is generated when omitted |
| `mb post new "Caption" --photo image.jpg` uploaded and posted in one step | Refused. Upload first with `mb media upload image.jpg --alt TEXT`, then post with `--photo-url` and `--alt` |
| `mb upload` accepted a remote URL | Remote URLs are refused; nothing is fetched. `mb upload PATH --alt TEXT` is an alias for `mb media upload` and uploads the local file unchanged |
| Edit/delete could match a post by slug suffix | Use an exact post URL or native numeric ID owned by the selected blog |
| `mb notes ...` | Removed in 2.0. Use ordinary posts with a category (`mb post new ... -c notes`, `mb blog posts -c notes`) |
| `mb mcp` did not exist | Optional local stdio MCP server; see [mcp.md](mcp.md) |

## For scripts

- If a script retries writes, give each intended action a stable `--operation-id` and store it with the exact arguments before running. Reusing both returns the saved receipt instead of posting twice; a plain rerun without an ID is a new post.
- After `outcome=unknown`, don't retry. Run the printed `mb operation-status ...` command, check micro.blog, and record the result with `mb operation-status ID --resolve applied|not_applied`.
- Point every writer for an account at one state file (`--state-file PATH`) and keep that file; it is how retries are recognized.
- Read errors and `coverage=` metadata from stderr, records from stdout.

Run `mb doctor` after upgrading: it shows which `mb` is first on your `PATH`, flags older copies that shadow it, and checks config, token, state file and checkpoints.

See [RELEASE.md](../RELEASE.md) for the full change list and the [README](../README.md#write-safety-and-recovery) for the recovery flow.
