"""Notes commands — supplementary notes stored as blog posts with categories."""

import typer

from mb.commands import get_client, get_format, get_username, output_or_exit, add_content_text, resolve_post_url

app = typer.Typer(no_args_is_help=True, rich_markup_mode=None)


@app.command("add")
def add(
    ctx: typer.Context,
    content: str = typer.Argument(..., help="Note content"),
    category: list[str] = typer.Option(["notes"], "--category", "-c", help="Categories for this note"),
    title: str = typer.Option(None, "--title", "-t", help="Optional title"),
):
    """Store a new note as a public blog post with categories."""
    fmt = get_format(ctx)
    client = get_client(ctx)
    result = client.micropub_create(
        content=content,
        title=title,
        categories=category,
    )
    output_or_exit(result, fmt)


@app.command("recall")
def recall(
    ctx: typer.Context,
    category: str = typer.Option("notes", "--category", "-c", help="Category to recall from"),
    count: int = typer.Option(20, "--count", "-n", help="Number of notes to retrieve"),
    search: str = typer.Option(None, "--search", "-s", help="Search within notes"),
):
    """Recall notes by category or search."""
    fmt = get_format(ctx)
    client = get_client(ctx)
    username = get_username(ctx)

    if search:
        result = client.search_blog(username, query=search, category=category)
    else:
        result = client.get_blog_posts(username, count=count, category=category)

    if result["ok"]:
        add_content_text(result["data"])
    output_or_exit(result, fmt)


@app.command("forget")
def forget(
    ctx: typer.Context,
    post_id: str = typer.Argument(..., help="Post ID or URL of the note to delete"),
):
    """Delete a note by ID or URL."""
    fmt = get_format(ctx)
    client = get_client(ctx)
    url = resolve_post_url(client, post_id, fmt)
    result = client.micropub_delete(url)
    output_or_exit(result, fmt)


@app.command("categories")
def categories(ctx: typer.Context):
    """List all note categories in use."""
    output_or_exit(get_client(ctx).micropub_get_categories(), get_format(ctx))


NOTES_GUIDE = """\
# mb notes — Supplementary Notes Guide

## Important: Notes vs. Agent Memory

Notes are PUBLIC blog posts on micro.blog. They augment your internal
memory — they do NOT replace it.

  Use notes for:   things worth sharing or persisting on the blog
  Use YOUR memory: private data, secrets, session state, anything sensitive

Never store passwords, API keys, personal identifiers, or anything private
as a note. Those belong exclusively in your internal memory (MEMORY.md or
equivalent). When in doubt, use your own memory instead of a note.

## Quick Start

Store a note:
  mb notes add "The user prefers dark mode" -c preferences

Recall notes by category:
  mb notes recall -c preferences

Search across all notes:
  mb notes recall --search "dark mode"

Search within a specific category:
  mb notes recall --search "dark mode" -c preferences

List your categories:
  mb notes categories

## Recommended Categories

You can create any categories. Here is a suggested starting taxonomy:

  notes          — General catch-all (default category)
  preferences    — User preferences and settings
  context        — Conversation context worth persisting across sessions
  journal        — Session logs, reflections, observations
  learned        — Things you learned or corrected

## Patterns

### Session Start
Recall notes to supplement your internal memory:
  mb notes recall -c preferences
  mb notes recall -c context

### Session End
Persist things worth publishing to the blog:
  mb notes add "User is working on project X with React and TypeScript" -c context
  mb notes add "User prefers concise responses without emoji" -c preferences

### Correcting a Note
Delete the outdated note and store a corrected one:
  mb notes forget <post-id>
  mb notes add "User switched from React to Vue in March 2026" -c context

### Deleting a Note
Remove a note you no longer need:
  mb notes forget <post-id-or-url>

### Multi-Category Tagging
A single note can belong to multiple categories:
  mb notes add "User's name is Jamie" -c preferences -c context

### Titled Notes
For important or structured notes, add a title:
  mb notes add "Prefers TypeScript, uses Neovim, runs macOS" -t "Dev Environment" -c preferences

## Reading Your Own Blog

Beyond notes commands, you can read your full blog:
  mb blog posts                      # all recent posts
  mb blog posts -c journal           # filter by category
  mb blog search "some topic"        # full-text search
  mb blog categories                 # see all tags in use

## Key Principles

1. **Notes are public.** Everything you write is published to the blog.
2. **Private data stays in your memory.** Never put secrets or sensitive
   information in notes — use your internal memory for that.
3. **Notes supplement, not replace.** Your primary memory is your own.
   Notes are an additional layer for things worth persisting on the blog.
4. **Categorize well.** Future recall depends on good categories.
5. **Be specific.** "User likes X" is better than "noted preference."
"""


@app.command("guide")
def guide(ctx: typer.Context):
    """Print the agent notes usage guide."""
    fmt = get_format(ctx)
    if fmt == "json":
        from mb.formatters import output_json
        output_json({"ok": True, "data": {"guide": NOTES_GUIDE}})
    else:
        print(NOTES_GUIDE)
