"""Blog reading commands — read own posts, categories, search."""

import typer

from mb.commands import get_client, get_format, get_username, output_or_exit, add_content_text

app = typer.Typer(no_args_is_help=True)


@app.command("posts")
def posts(
    ctx: typer.Context,
    count: int = typer.Option(20, "--count", "-n", help="Number of posts"),
    category: str = typer.Option(None, "--category", "-c", help="Filter by category"),
):
    """List your own blog posts."""
    fmt = get_format(ctx)
    client = get_client(ctx)
    username = get_username(ctx)
    result = client.get_blog_posts(username, count=count, category=category)
    if result["ok"]:
        add_content_text(result["data"])
    output_or_exit(result, fmt)


@app.command("categories")
def categories(ctx: typer.Context):
    """List all categories/tags used on your blog."""
    output_or_exit(get_client(ctx).micropub_get_categories(), get_format(ctx))


@app.command("search")
def search(
    ctx: typer.Context,
    query: str = typer.Argument(..., help="Search query"),
):
    """Search your blog posts."""
    fmt = get_format(ctx)
    client = get_client(ctx)
    username = get_username(ctx)
    result = client.search_blog(username, query=query)
    if result["ok"]:
        add_content_text(result["data"])
    output_or_exit(result, fmt)
