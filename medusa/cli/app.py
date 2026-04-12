from __future__ import annotations

import argparse
import sys

from medusa.cli.display import select_menu


def _interactive_menu() -> int:
    from medusa.cli.flows import clear_flow, select_flow, setup_flow, show_flow

    action = select_menu(
        "Medusa LLM Configuration",
        [
            {"name": "Set up a provider", "value": "setup"},
            {"name": "Select active model", "value": "select"},
            {"name": "Show current config", "value": "show"},
            {"name": "Clear credentials", "value": "clear"},
        ],
    )

    if action is None:
        return 0

    dispatch = {
        "setup": setup_flow,
        "select": select_flow,
        "show": show_flow,
        "clear": clear_flow,
    }
    return dispatch[action]()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="medusa.cli",
        description="Medusa LLM provider and model configuration.",
    )
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("setup", help="Set up a provider (configure credentials).")
    subparsers.add_parser("select", help="Select the active provider and model.")
    subparsers.add_parser("show", help="Show current configuration and auth status.")
    subparsers.add_parser("clear", help="Clear stored credentials for a provider.")

    args = parser.parse_args(argv)

    if args.command is None:
        return _interactive_menu()

    from medusa.cli.flows import clear_flow, select_flow, setup_flow, show_flow

    dispatch = {
        "setup": setup_flow,
        "select": select_flow,
        "show": show_flow,
        "clear": clear_flow,
    }
    return dispatch[args.command]()
