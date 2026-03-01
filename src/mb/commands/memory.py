"""Memory commands — agent-oriented long-term memory backed by blog posts with categories."""

import typer

app = typer.Typer(no_args_is_help=True)


def _get_client():
    from mb.cli import get_client
    return get_client()


def _get_format(ctx: typer.Context) -> str:
    from mb.cli import get_format
    return get_format(ctx)


def _get_username(ctx: typer.Context) -> str:
    from mb.cli import get_profile
    from mb import config
    from mb.formatters import output

    profile = get_profile(ctx)
    username = config.get_username(profile=profile)
    if username:
        return username

    client = _get_client()
    result = client.verify_token()
    if result["ok"]:
        return result["data"].get("username", "")

    fmt = _get_format(ctx)
    output({"ok": False, "error": "Cannot determine username. Run: mb auth <token>", "code": 401}, fmt)
    raise SystemExit(1)


@app.command("add")
def add(
    ctx: typer.Context,
    content: str = typer.Argument(..., help="Memory content"),
    category: list[str] = typer.Option(["memory"], "--category", "-c", help="Categories for this memory"),
    draft: bool = typer.Option(False, "--draft", help="Store as draft (private)"),
    title: str = typer.Option(None, "--title", "-t", help="Optional title"),
):
    """Store a new memory as a blog post with categories."""
    from mb.formatters import output

    fmt = _get_format(ctx)
    client = _get_client()
    result = client.micropub_create(
        content=content,
        title=title,
        draft=draft,
        categories=category,
    )
    output(result, fmt)
    if not result["ok"]:
        raise SystemExit(1)


@app.command("recall")
def recall(
    ctx: typer.Context,
    category: str = typer.Option("memory", "--category", "-c", help="Category to recall from"),
    count: int = typer.Option(20, "--count", "-n", help="Number of memories to retrieve"),
    search: str = typer.Option(None, "--search", "-s", help="Search within memories"),
):
    """Recall memories by category or search."""
    from mb.formatters import output, strip_html

    fmt = _get_format(ctx)
    client = _get_client()
    username = _get_username(ctx)

    if search:
        result = client.search_blog(username, query=search)
    else:
        result = client.get_blog_posts(username, count=count, category=category)

    if result["ok"]:
        for item in result["data"].get("items", []):
            if "content_html" in item:
                item["content_text"] = strip_html(item["content_html"]).strip()

    output(result, fmt)
    if not result["ok"]:
        raise SystemExit(1)


@app.command("categories")
def categories(ctx: typer.Context):
    """List all memory categories in use."""
    from mb.formatters import output

    fmt = _get_format(ctx)
    client = _get_client()
    result = client.micropub_get_categories()
    output(result, fmt)
    if not result["ok"]:
        raise SystemExit(1)


MEMORY_GUIDE = """\
# mb memory — Agent Long-Term Memory Guide

Your blog is your long-term memory. Every memory is a blog post tagged with
categories you define. There are no hardcoded memory types — you decide what
categories to use and what to remember.

## Quick Start

Store a memory:
  mb memory add "The user prefers dark mode" -c preferences

Recall memories by category:
  mb memory recall -c preferences

Search across all memories:
  mb memory recall --search "dark mode"

List your categories:
  mb memory categories

## Recommended Categories

You can create any categories. Here is a suggested starting taxonomy:

  core-memory    — Critical, long-lived facts (user identity, key preferences)
  preferences    — User preferences and settings
  context        — Conversation context worth persisting across sessions
  journal        — Session logs, reflections, observations
  learned        — Things you learned or corrected
  memory         — General catch-all (default category)

## Patterns

### Session Start
At the beginning of a session, recall core memories to orient yourself:
  mb memory recall -c core-memory
  mb memory recall -c preferences

### Session End
Persist important things you learned during this session:
  mb memory add "User is working on project X with React and TypeScript" -c context
  mb memory add "User prefers concise responses without emoji" -c preferences -c core-memory

### Correcting a Memory
Post a new memory that supersedes the old one. Include enough context for
your future self to understand:
  mb memory add "CORRECTION: User switched from React to Vue in March 2026" -c context -c core-memory

### Private Memories
Use --draft to store memories that won't appear on the public blog:
  mb memory add "API key for service X is stored in ~/.config/x" --draft -c context

### Multi-Category Tagging
A single memory can belong to multiple categories:
  mb memory add "User's name is Jamie" -c core-memory -c preferences

### Titled Memories
For important or structured memories, add a title:
  mb memory add "Prefers TypeScript, uses Neovim, runs macOS" -t "Dev Environment" -c core-memory

## Reading Your Own Blog

Beyond memory commands, you can read your full blog:
  mb blog posts                      # all recent posts
  mb blog posts -c journal           # filter by category
  mb blog search "some topic"        # full-text search
  mb blog categories                 # see all tags in use

## Key Principles

1. **Write often.** Storage is cheap. When in doubt, remember it.
2. **Categorize well.** Future recall depends on good categories.
3. **Be specific.** "User likes X" is better than "noted preference."
4. **Core memories are sacred.** Reserve core-memory for truly important facts.
5. **Review periodically.** Recall and review categories to stay oriented.
"""


@app.command("guide")
def guide(ctx: typer.Context):
    """Print the agent memory usage guide."""
    fmt = _get_format(ctx)
    if fmt == "json":
        from mb.formatters import output_json
        output_json({"ok": True, "data": {"guide": MEMORY_GUIDE}})
    else:
        print(MEMORY_GUIDE)
