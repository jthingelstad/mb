"""Output modes: json | human | agent."""

import json
import re
import sys
from datetime import datetime, timezone

from rich.console import Console
from rich.table import Table


def strip_html(html: str) -> str:
    """Remove HTML tags from a string."""
    return re.sub(r"<[^>]+>", "", html)


def _relative_time(timestamp: str) -> str:
    """Convert ISO timestamp to relative time string like '2h' or '3d'."""
    try:
        dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        diff = now - dt
        seconds = int(diff.total_seconds())
        if seconds < 60:
            return f"{seconds}s"
        minutes = seconds // 60
        if minutes < 60:
            return f"{minutes}m"
        hours = minutes // 60
        if hours < 24:
            return f"{hours}h"
        days = hours // 24
        return f"{days}d"
    except (ValueError, TypeError):
        return "?"


def _extract_username(author: dict) -> str:
    """Extract @username from author object.

    Prefers _microblog.username (canonical micro.blog handle), then falls
    back to parsing the URL, then the display name.
    """
    mb = author.get("_microblog")
    if isinstance(mb, dict) and mb.get("username"):
        return mb["username"]
    url = author.get("url", "")
    if url:
        parts = url.rstrip("/").split("/")
        if parts:
            return parts[-1]
    return author.get("name", "?")


def output_json(data: dict) -> None:
    """Print a JSON envelope to stdout."""
    json.dump(data, sys.stdout, indent=2)
    sys.stdout.write("\n")


def output_human(data: dict) -> None:
    """Print rich-formatted output for humans."""
    console = Console()
    if not data.get("ok"):
        console.print(f"[red]Error:[/red] {data.get('error', 'Unknown error')}")
        return

    payload = data.get("data", {})

    # User lists (e.g. following, muting, blocking) — check before dict operations
    if isinstance(payload, list):
        if not payload:
            console.print("[dim]No items.[/dim]")
            return
        for entry in payload:
            if isinstance(entry, dict) and "username" in entry:
                console.print(f"  @{entry['username']}")
            else:
                console.print(f"  {entry}")
        return

    # Single post
    if "id" in payload and "url" in payload and "content_html" not in payload:
        console.print(f"[green]OK[/green] id={payload['id']} url={payload['url']}")
        return

    # User info
    if "username" in payload and "avatar" in payload:
        console.print(f"[bold]{payload['username']}[/bold]")
        if payload.get("name"):
            console.print(f"  Name: {payload['name']}")
        if payload.get("url"):
            console.print(f"  URL: {payload['url']}")
        return

    # Post list (items array)
    items = payload.get("items", [])
    if items:
        table = Table(show_header=True, header_style="bold")
        table.add_column("ID", style="dim")
        table.add_column("Author")
        table.add_column("Content", max_width=60)
        table.add_column("Date", style="dim")
        for item in items:
            author_obj = item.get("author", {})
            author = author_obj.get("name") or _extract_username(author_obj)
            content = strip_html(item.get("content_html", ""))[:60]
            date = item.get("date_published", "")[:10]
            table.add_row(str(item.get("id", "")), author, content, date)
        console.print(table)
        return

    # Fallback
    console.print_json(json.dumps(payload))


def output_agent(data: dict) -> None:
    """Print condensed plain-text optimized for LLM context windows."""
    if not data.get("ok"):
        print(f"ERROR: {data.get('error', 'Unknown error')}")
        return

    payload = data.get("data", {})

    # User lists (e.g. following, muting, blocking) — check before dict operations
    if isinstance(payload, list):
        for entry in payload:
            if isinstance(entry, dict) and "username" in entry:
                print(f"@{entry['username']}")
            else:
                print(f"  {entry}")
        return

    items = payload.get("items", [])
    if items:
        for item in items:
            post_id = item.get("id", "?")
            author = _extract_username(item.get("author", {}))
            time = _relative_time(item.get("date_published", ""))
            content = strip_html(item.get("content_html", "")).strip()
            # Include categories if present
            cats = item.get("_microblog", {}).get("categories", []) if isinstance(item.get("_microblog"), dict) else []
            cat_str = f" [{', '.join(cats)}]" if cats else ""
            print(f"[{post_id}] @{author} ({time}){cat_str}: {content}")
        return

    # Single result fallback
    if "id" in payload:
        print(f"OK id={payload.get('id')} url={payload.get('url', '')}")
        return

    if "username" in payload:
        print(f"@{payload['username']} {payload.get('url', '')}")
        return

    # Generic fallback
    print(json.dumps(payload))


def output(data: dict, fmt: str = "json") -> None:
    """Route output to the appropriate formatter."""
    if fmt == "human":
        output_human(data)
    elif fmt == "agent":
        output_agent(data)
    else:
        output_json(data)
