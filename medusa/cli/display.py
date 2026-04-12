from __future__ import annotations

from typing import Any, Sequence

from InquirerPy import inquirer
from rich.console import Console
from rich.table import Table

console = Console()


_BACK_SENTINEL = object()


def select_menu(message: str, choices: Sequence[dict[str, Any]], *, allow_back: bool = True) -> Any:
    """Arrow-key select menu. Press Escape to go back (returns None when allow_back=True)."""
    result = inquirer.select(
        message=message,
        choices=list(choices),
        pointer=">",
        mandatory=not allow_back,
        instruction="(esc to go back)" if allow_back else "",
    ).execute()
    return result


def text_input(message: str, *, password: bool = False) -> str | None:
    """Text input. Returns None on Escape."""
    if password:
        return inquirer.secret(
            message=message, transformer=lambda _: "[hidden]",
            mandatory=False, instruction="(esc to go back)",
        ).execute()
    return inquirer.text(
        message=message,
        mandatory=False, instruction="(esc to go back)",
    ).execute()


def confirm(message: str, default: bool = False) -> bool | None:
    """Confirm prompt. Returns None on Escape."""
    return inquirer.confirm(
        message=message, default=default,
        mandatory=False,
    ).execute()


def status_table(
    active_provider: str | None,
    active_model: str | None,
    config_path: str | None,
    provider_statuses: list[dict[str, Any]],
    active_reasoning: str | None = None,
) -> None:
    table = Table(title="Medusa LLM Configuration", show_lines=True)
    table.add_column("", style="bold cyan", width=16)
    table.add_column("", min_width=40)

    active_display = f"{active_provider} / {active_model}" if active_provider else "not configured"
    if active_reasoning:
        active_display += f"  [dim](reasoning: {active_reasoning})[/dim]"
    table.add_row("Active", active_display)
    if config_path:
        table.add_row("Config file", config_path)

    for status in provider_statuses:
        provider_id = status["id"]
        label = status["label"]
        if status["authenticated"]:
            auth_line = f"[green]authenticated[/green] ({status['source']})"
            if status.get("expires_at"):
                import datetime

                dt = datetime.datetime.fromtimestamp(
                    status["expires_at"] / 1000, tz=datetime.timezone.utc
                )
                auth_line += f"\n  expires: {dt:%Y-%m-%d %H:%M} UTC"
        else:
            auth_line = "[red]no credentials found[/red]"
        table.add_row(label, auth_line)

    console.print()
    console.print(table)
    console.print()


def success(msg: str) -> None:
    console.print(f"[bold green]OK[/bold green] {msg}")


def error(msg: str) -> None:
    console.print(f"[bold red]Error[/bold red] {msg}")


def info(msg: str) -> None:
    console.print(f"[bold blue]Info[/bold blue] {msg}")
