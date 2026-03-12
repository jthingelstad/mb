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

    if isinstance(payload, dict) and "results" in payload and "action" in payload:
        action = payload.get("action", "action")
        console.print(f"[bold]{action}[/bold]: {payload.get('ok_count', 0)} ok, {payload.get('error_count', 0)} errors")
        for entry in payload.get("results", []):
            status = "[green]ok[/green]" if entry.get("ok") else "[red]error[/red]"
            console.print(f"  {status} @{entry.get('username', '?')}")
            if entry.get("error"):
                console.print(f"    {entry['error']}")
        return

    if isinstance(payload, dict) and "users" in payload:
        users = payload.get("users", [])
        errors = payload.get("errors", [])
        if not users and not errors:
            console.print("[dim]No items.[/dim]")
            return
        if users:
            show_last_post = any(entry.get("last_post_date") or entry.get("last_post_content_text") for entry in users)
            show_inactive = any("inactive_days" in entry for entry in users)
            table = Table(show_header=True, header_style="bold")
            table.add_column("Username")
            if show_last_post:
                table.add_column("Last Post", style="dim")
            if show_inactive:
                table.add_column("Inactive", style="dim")
            if show_last_post:
                table.add_column("Content", max_width=60)
            for entry in users:
                last_post = (entry.get("last_post_date") or "")[:10] or "never"
                inactive = "unknown" if entry.get("inactive_days") is None else f"{entry['inactive_days']}d"
                content = entry.get("last_post_content_text") or ""
                row = [f"@{entry.get('username', '?')}"]
                if show_last_post:
                    row.append(last_post)
                if show_inactive:
                    row.append(inactive)
                if show_last_post:
                    row.append(content)
                table.add_row(*row)
            console.print(table)
        for entry in errors:
            console.print(f"  @{entry.get('username', '?')} error={entry.get('error', 'lookup error')}")
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

    if isinstance(payload, dict) and "results" in payload and "action" in payload:
        for entry in payload.get("results", []):
            status = "ok" if entry.get("ok") else f"error={entry.get('error', 'unknown')}"
            print(f"@{entry.get('username', '?')} {status}")
        return

    if isinstance(payload, dict) and "users" in payload:
        for entry in payload.get("users", []):
            parts = [f"@{entry.get('username', '?')}"]
            if entry.get("inactive_days") is not None:
                parts.append(f"inactive_days={entry['inactive_days']}")
            if entry.get("last_post_date"):
                parts.append(f"last_post={entry['last_post_date'][:10]}")
            line = " ".join(parts)
            if entry.get("last_post_content_text"):
                line = f"{line}: {entry['last_post_content_text']}"
            print(line)
        for entry in payload.get("errors", []):
            print(f"@{entry.get('username', '?')} error={entry.get('error', 'lookup_error')}")
        return

    items = payload.get("items", [])
    if items:
        for item in items:
            post_id = item.get("id", "?")
            author = _extract_username(item.get("author", {}))
            time = _relative_time(item.get("date_published", ""))
            content = strip_html(item.get("content_html", "")).strip()
            # Include categories if present (tags from normalized items, _microblog.categories from JSON API)
            cats = item.get("tags", [])
            if not cats:
                cats = item.get("_microblog", {}).get("categories", []) if isinstance(item.get("_microblog"), dict) else []
            cat_str = f" [{', '.join(cats)}]" if cats else ""
            indent = "  " * item.get("depth", 0)
            print(f"{indent}[{post_id}] @{author} ({time}){cat_str}: {content}")
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


def output(data: dict, fmt: str = "agent") -> None:
    """Route output to the appropriate formatter."""
    if fmt == "human":
        output_human(data)
    elif fmt == "agent":
        output_agent(data)
    else:
        output_json(data)
