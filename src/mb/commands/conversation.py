"""Thread fetching — recursively fetch conversation to root."""

import typer

from mb.commands import add_content_text, get_client, get_format
from mb.domain import _build_thread as _build_thread

app = typer.Typer(no_args_is_help=False, invoke_without_command=True, rich_markup_mode=None)


@app.callback(invoke_without_command=True)
def conversation(
    ctx: typer.Context,
    post_id: int = typer.Argument(..., help="Post ID to fetch conversation for"),
):
    """Fetch full thread, recursively to root."""
    from mb.formatters import output

    fmt = get_format(ctx)
    client = get_client(ctx)
    result = client.get_conversation(post_id)

    if not result["ok"]:
        output(result, fmt)
        raise SystemExit(1)

    items = result["data"].get("items", [])
    thread = _build_thread(items)
    thread_data = {"items": thread}
    add_content_text(thread_data)

    output({"ok": True, "data": thread_data}, fmt)
