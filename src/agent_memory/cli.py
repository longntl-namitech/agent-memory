"""`agent-memory` command line. Subcommands: `review diff`."""

import argparse
from datetime import datetime
from pathlib import Path

from agent_memory.core.layout import Store
from agent_memory.core.review import rules_diff


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="agent-memory")
    sub = parser.add_subparsers(dest="command", required=True)
    review = sub.add_parser("review").add_subparsers(dest="action", required=True)
    diff = review.add_parser("diff", help="print the RULES diff between two points in time")
    diff.add_argument("--store", type=Path, required=True)
    diff.add_argument("--from", dest="start", type=datetime.fromisoformat, required=True)
    diff.add_argument("--to", dest="end", type=datetime.fromisoformat, required=True)
    args = parser.parse_args(argv)
    if not args.store.is_dir():
        parser.error(f"no store at {args.store}")  # Store() would create an empty one
    print("\n".join(rules_diff(Store(args.store), args.start, args.end)))
    return 0
