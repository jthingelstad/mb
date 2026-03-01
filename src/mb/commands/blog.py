"""Blog reading commands — read own posts, categories, search."""

import typer

app = typer.Typer(no_args_is_help=True)


def _get_client():
    from mb.cli import get_client
    return get_client()


def _get_format(ctx: typer.Context) -> str:
    from mb.cli import get_format
    return get_format(ctx)


def _get_username(ctx: typer.Context) -> str:
    """Resolve the current username from config or by verifying the token."""
    from mb.cli import get_profile
    from mb import config
    from mb.formatters import output

    profile = get_profile(ctx)
    username = config.get_username(profile=profile)
    if username:
        return username

    # Fall back to verifying the token
    client = _get_client()
    result = client.verify_token()
    if result["ok"]:
        return result["data"].get("username", "")

    fmt = _get_format(ctx)
    output({"ok": False, "error": "Cannot determine username. Run: mb auth <token>", "code": 401}, fmt)
    raise SystemExit(1)


@app.command("posts")
def posts(
    ctx: typer.Context,
    count: int = typer.Option(20, "--count", "-n", help="Number of posts"),
    category: str = typer.Option(None, "--category", "-c", help="Filter by category"),
):
    """List your own blog posts."""
    from mb.formatters import output, strip_html

    fmt = _get_format(ctx)
    client = _get_client()
    username = _get_username(ctx)
    result = client.get_blog_posts(username, count=count, category=category)

    if result["ok"]:
        # Add content_text to each item
        for item in result["data"].get("items", []):
            if "content_html" in item:
                item["content_text"] = strip_html(item["content_html"]).strip()

    output(result, fmt)
    if not result["ok"]:
        raise SystemExit(1)


@app.command("categories")
def categories(ctx: typer.Context):
    """List all categories/tags used on your blog."""
    from mb.formatters import output

    fmt = _get_format(ctx)
    client = _get_client()
    result = client.micropub_get_categories()
    output(result, fmt)
    if not result["ok"]:
        raise SystemExit(1)


@app.command("search")
def search(
    ctx: typer.Context,
    query: str = typer.Argument(..., help="Search query"),
):
    """Search your blog posts."""
    from mb.formatters import output, strip_html

    fmt = _get_format(ctx)
    client = _get_client()
    username = _get_username(ctx)
    result = client.search_blog(username, query=query)

    if result["ok"]:
        for item in result["data"].get("items", []):
            if "content_html" in item:
                item["content_text"] = strip_html(item["content_html"]).strip()

    output(result, fmt)
    if not result["ok"]:
        raise SystemExit(1)
