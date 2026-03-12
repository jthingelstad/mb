---
name: mb-cli
description: Use this skill whenever you are using the mb CLI to read, post, manage follows, inspect notes, or build pipelines against micro.blog. It covers command selection, output modes, public/private boundaries, and cheap-versus-expensive mb workflows.
---

# mb CLI

Use this skill whenever the task involves `mb`.

## Core rules

- Default to `agent` output for exploration and pipelines.
- Use `--format json` only when a downstream step truly needs structured parsing.
- Prefer cheap list/read commands first.
- Make expensive fan-out explicit with `mb lookup ...`.
- Treat `mb notes ...` as public posting, not private storage.
- Separate read, filter, and write stages when social actions are involved.

## Cheap first, expensive second

Cheap reads:

```bash
mb whoami
mb timeline --count 10
mb user following
mb user discover
mb discover --collection books
```

Explicit enrichment:

```bash
mb user following | mb lookup users --last-post
mb user following | mb lookup users --days-since-posting
```

## Public boundaries

- `mb post ...` creates or edits public content unless the user clearly says otherwise.
- `mb notes add ...` stores a public blog post.
- Never put secrets, tokens, private contact details, or hidden strategy into notes.

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

Identity and config:

```bash
mb whoami
mb profiles
mb blogs
```

Posting:

```bash
mb post new "Text"
mb post new --content "Text"
mb post new --file post.md
mb post new --dry-run "Text"
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
mb discover --collection books
mb user show <username>
```

Lookup and follow management:

```bash
mb user following | mb lookup users --last-post
mb user following | mb lookup users --days-since-posting
mb follow <username|->
mb unfollow <username|->
```

Notes:

```bash
mb notes add "Public fact worth keeping" -c preferences
mb notes recall
mb notes recall --search "keyword"
mb notes categories
```
