import argparse
from getpass import getpass

from medusa.auth import (
    ANTHROPIC_CREDENTIAL_FILE,
    clear_persisted_anthropic_token,
    resolve_anthropic_auth,
    save_anthropic_setup_token,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Manage local Anthropic auth for Medusa.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    set_token_parser = subparsers.add_parser("set-token", help="Persist an Anthropic setup token.")
    set_token_parser.add_argument("--token", help="Anthropic setup token to store.")

    subparsers.add_parser("show", help="Show the resolved Anthropic auth source.")
    subparsers.add_parser("clear", help="Delete the locally persisted Anthropic token.")

    args = parser.parse_args()

    if args.command == "set-token":
        token = args.token or getpass("Paste Anthropic setup token: ").strip()
        path = save_anthropic_setup_token(token)
        print(f"Saved Anthropic token to {path}")
        return 0

    if args.command == "show":
        auth = resolve_anthropic_auth()
        print(f"source={auth.source or 'none'}")
        print(f"has_auth_token={'yes' if bool(auth.auth_token) else 'no'}")
        print(f"has_api_key={'yes' if bool(auth.api_key) else 'no'}")
        if auth.credential_path:
            print(f"path={auth.credential_path}")
        return 0

    if args.command == "clear":
        removed = clear_persisted_anthropic_token()
        if removed:
            print(f"Removed {ANTHROPIC_CREDENTIAL_FILE}")
        else:
            print("No persisted Anthropic token was found.")
        return 0

    parser.error("Unknown command")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
