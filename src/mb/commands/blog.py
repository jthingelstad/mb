"""Blog reading commands — read own posts, categories, search."""

import typer

from mb.commands import (
    add_content_text,
    get_format,
    get_service,
    output_or_exit,
)

app = typer.Typer(no_args_is_help=True, rich_markup_mode=None)


@app.command("posts")
def posts(
    ctx: typer.Context,
    count: int = typer.Option(20, "--count", "-n", min=1, max=50, help="Number of posts"),
    category: str = typer.Option(None, "--category", "-c", help="Filter by category"),
):
    """List your own blog posts."""
    fmt = get_format(ctx)
    result = get_service(ctx).own_posts(count=count, category=category)
    if result["ok"]:
        add_content_text(result["data"])
    output_or_exit(result, fmt)


@app.command("categories")
def categories(ctx: typer.Context):
    """List all categories/tags used on your blog."""
    output_or_exit(get_service(ctx).blog_categories(), get_format(ctx))


@app.command("search")
def search(
    ctx: typer.Context,
    query: str = typer.Argument(..., help="Search query"),
    count: int = typer.Option(20, "--count", "-n", min=1, max=50),
    category: str | None = typer.Option(None, "--category", "-c"),
):
    """Search your blog posts."""
    fmt = get_format(ctx)
    result = get_service(ctx).blog_search(query, count=count, category=category)
    if result["ok"]:
        add_content_text(result["data"])
    output_or_exit(result, fmt)
