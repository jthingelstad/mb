"""Thread fetching — recursively fetch conversation to root."""

import typer

from mb.commands import add_content_text, get_client, get_format

app = typer.Typer(no_args_is_help=False, invoke_without_command=True, rich_markup_mode=None)


@app.callback(invoke_without_command=True)
def conversation(
    ctx: typer.Context,
    post_id: str = typer.Argument(..., help="Numeric post ID or public URL"),
):
    """Fetch full thread, recursively to root."""
    from mb.formatters import output

    fmt = get_format(ctx)
    client = get_client(ctx)
    from mb.services import read_conversation

    result = read_conversation(client, post_id)

    if not result["ok"]:
        output(result, fmt)
        raise SystemExit(1)

    # read_conversation already orders the thread root to leaf with depth.
    thread_data = dict(result["data"])
    add_content_text(thread_data)

    output({"ok": True, "data": thread_data}, fmt)
