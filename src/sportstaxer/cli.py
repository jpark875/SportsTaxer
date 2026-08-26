"""CLI entry point. Each pipeline stage gets its own subcommand so stages can run
standalone against artifacts on disk."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from sportstaxer import __version__
from sportstaxer.config import Config, ConfigError, load_config


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sportstaxer", description=__doc__)
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--config", type=Path, help="path to config file")
    sub = parser.add_subparsers(dest="command", required=True)

    show = sub.add_parser("config", help="print resolved configuration")
    show.set_defaults(func=cmd_config)
    return parser


def cmd_config(config: Config, args: argparse.Namespace) -> int:
    print(config.model_dump_json(indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        config = load_config(args.config)
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return args.func(config, args)


if __name__ == "__main__":
    raise SystemExit(main())
