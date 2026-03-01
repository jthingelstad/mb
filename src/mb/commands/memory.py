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
