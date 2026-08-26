"""CLI entry point. Each pipeline stage gets its own subcommand so stages can run
standalone against artifacts on disk."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from sportstaxer import __version__
from sportstaxer.config import Config, ConfigError, load_config
from sportstaxer.frames import FrameExtractionError, extract_frames


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sportstaxer", description=__doc__)
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--config", type=Path, help="path to config file")
    sub = parser.add_subparsers(dest="command", required=True)

    show = sub.add_parser("config", help="print resolved configuration")
    show.set_defaults(func=cmd_config)

    frames = sub.add_parser("frames", help="extract deduplicated frames from a recording")
    frames.add_argument("video", type=Path)
    frames.add_argument("--run-id", help="artifact directory name (default: video stem)")
    frames.add_argument("--fps", type=float, help="sampling rate, overrides config")
    frames.add_argument("--no-dedup", action="store_true", help="keep every sampled frame")
    frames.add_argument("--force", action="store_true", help="re-extract even if a manifest exists")
    frames.set_defaults(func=cmd_frames)
    return parser


def cmd_config(config: Config, args: argparse.Namespace) -> int:
    print(config.model_dump_json(indent=2))
    return 0


def cmd_frames(config: Config, args: argparse.Namespace) -> int:
    if args.fps is not None:
        config.fps = args.fps
    if args.no_dedup:
        config.dedup.enabled = False

    run_id = args.run_id or args.video.stem
    out_dir = config.stage_dir(run_id, "frames")
    try:
        manifest = extract_frames(args.video, out_dir, config, force=args.force)
    except FrameExtractionError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(f"{manifest.kept}/{manifest.extracted} frames kept at {config.fps} fps -> {out_dir}")
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
