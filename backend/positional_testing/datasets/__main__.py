"""Validate/import the frozen library or inspect PostgreSQL counts; no model calls."""

import argparse
import json
from pathlib import Path

from .validation import load_collection


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("validate", "import", "summary"))
    parser.add_argument(
        "--directory", type=Path, default=Path(__file__).with_name("seed") / "v1"
    )
    args = parser.parse_args()
    if args.command == "validate":
        result = load_collection(args.directory)[2]
    else:
        from .store import import_collection, summary

        result = (
            import_collection(args.directory) if args.command == "import" else summary()
        )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
