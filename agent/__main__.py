"""Entry point guard — direct `python -m agent` usage is disabled.

All agent management goes through `manobot` CLI.
"""

import sys


def main():
    print(
        "Error: Direct 'python -m agent' is not supported.\n"
        "Use the manobot CLI instead:\n"
        "  manobot gateway           # Start all agents\n"
        "  manobot agent -m 'hello'  # Chat with an agent\n"
        "  manobot --help            # See all commands",
        file=sys.stderr,
    )
    sys.exit(1)


if __name__ == "__main__":
    main()
