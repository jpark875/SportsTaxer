"""CLI entry point. Each pipeline stage gets its own subcommand so stages can run
standalone against artifacts on disk."""

from __future__ import annotations

import argparse
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path

from sportstaxer import __version__
from sportstaxer.adapters import AdapterError, list_adapters, load_adapter
from sportstaxer.config import Config, ConfigError, load_config
from sportstaxer.export import export_xlsx
from sportstaxer.extract import (
    ExtractionError,
    ReplayBackend,
    extract_canvas,
    load_extraction,
    make_backend,
)
from sportstaxer.frames import FrameExtractionError, extract_frames, load_manifest
from sportstaxer.parse import parse_extraction
from sportstaxer.reconcile import ReconcileError, reconcile
from sportstaxer.stitch import StitchError, load_canvas_manifest, stitch

STAGE_ERRORS = (
    AdapterError,
    ExtractionError,
    FrameExtractionError,
    ReconcileError,
    StitchError,
)


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

    books = sub.add_parser("books", help="list adapter profiles")
    books.set_defaults(func=cmd_books)

    stitch_cmd = sub.add_parser("stitch", help="register frames into a canvas")
    stitch_cmd.add_argument("run_id")
    stitch_cmd.add_argument("--book", required=True, help="adapter profile name")
    stitch_cmd.set_defaults(func=cmd_stitch)

    extract = sub.add_parser("extract", help="read rows off the canvas")
    extract.add_argument("run_id")
    extract.add_argument("--book", required=True, help="adapter profile name")
    add_extract_options(extract)
    extract.set_defaults(func=cmd_extract)

    ledger = sub.add_parser("ledger", help="parse, reconcile and export to xlsx")
    ledger.add_argument("run_id")
    add_ledger_options(ledger)
    ledger.set_defaults(func=cmd_ledger)

    run = sub.add_parser("run", help="run every stage on a recording")
    run.add_argument("video", type=Path)
    run.add_argument("--run-id", help="artifact directory name (default: video stem)")
    run.add_argument("--fps", type=float, help="sampling rate, overrides config")
    run.add_argument("--force", action="store_true", help="re-extract frames")
    add_extract_options(run)
    add_ledger_options(run)
    run.set_defaults(func=cmd_run)
    return parser


def add_extract_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--backend", choices=["anthropic", "ocr", "replay"])
    parser.add_argument("--responses", type=Path, help="recorded responses for --backend replay")


def add_ledger_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--book", required=True, help="adapter profile name")
    parser.add_argument("--opening", type=decimal_arg, help="balance on the first frame")
    parser.add_argument("--closing", type=decimal_arg, help="balance on the last frame")
    parser.add_argument("--year", type=int, help="year for dates the book shows without one")
    parser.add_argument("-o", "--output", type=Path, help="xlsx path (default: out/<run-id>.xlsx)")


def decimal_arg(text: str) -> Decimal:
    try:
        return Decimal(text.replace(",", "").lstrip("$"))
    except InvalidOperation as exc:
        raise argparse.ArgumentTypeError(f"not an amount: {text!r}") from exc


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


def cmd_books(config: Config, args: argparse.Namespace) -> int:
    for name in list_adapters(config.adapters_dir):
        adapter = load_adapter(name, config.adapters_dir)
        stake = "inclusive" if adapter.payout_includes_stake else "exclusive"
        print(f"{name:<16} {adapter.display_name:<24} payout {stake} of stake")
    return 0


def cmd_stitch(config: Config, args: argparse.Namespace) -> int:
    frames_dir = config.stage_dir(args.run_id, "frames")
    out_dir = config.stage_dir(args.run_id, "canvas")
    try:
        adapter = load_adapter(args.book, config.adapters_dir)
        manifest = load_manifest(frames_dir)
        canvas = stitch(manifest.kept_paths(frames_dir), out_dir, config, adapter.crop)
    except (AdapterError, FrameExtractionError, StitchError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(
        f"canvas {canvas.width}x{canvas.height} in {len(canvas.segments)} segment(s) -> {out_dir}"
    )
    if canvas.gaps:
        print(f"{len(canvas.gaps)} gap(s); reconciliation will refuse this run:", file=sys.stderr)
        for gap in canvas.gaps:
            print(f"  frame {gap.frame} at y={gap.offset}: {gap.gap_reason}", file=sys.stderr)
    return 0


def run_extract(config: Config, run_id: str, args: argparse.Namespace) -> None:
    adapter = load_adapter(args.book, config.adapters_dir)
    canvas_dir = config.stage_dir(run_id, "canvas")
    if args.backend:
        config.extract.backend = args.backend
    if config.extract.backend == "replay":
        if args.responses is None:
            raise ExtractionError("--backend replay needs --responses DIR")
        backend = ReplayBackend(args.responses)
    else:
        backend = make_backend(config)
    result = extract_canvas(load_canvas_manifest(canvas_dir), canvas_dir, adapter, config, backend)
    print(f"{len(result.rows)} row(s), {len(result.flagged)} flagged -> {canvas_dir}")


def run_ledger(config: Config, run_id: str, args: argparse.Namespace) -> int:
    adapter = load_adapter(args.book, config.adapters_dir)
    canvas_dir = config.stage_dir(run_id, "canvas")
    if args.year:
        config.ledger.assume_year = args.year
    rows = parse_extraction(load_extraction(canvas_dir), adapter, config)
    report = reconcile(rows, load_canvas_manifest(canvas_dir), args.opening, args.closing)
    path = export_xlsx(rows, report, args.output or config.out_dir / f"{run_id}.xlsx")

    print(f"{len(rows)} row(s), {report.flagged} need review -> {path}")
    for note in report.notes:
        print(f"  note: {note}", file=sys.stderr)
    if report.status == "mismatch":
        print(f"reconciliation FAILED: off by {report.difference:+,.2f}", file=sys.stderr)
        return 3
    print(f"reconciliation: {report.status}")
    return 0


def cmd_extract(config: Config, args: argparse.Namespace) -> int:
    try:
        run_extract(config, args.run_id, args)
    except (*STAGE_ERRORS, FileNotFoundError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


def cmd_ledger(config: Config, args: argparse.Namespace) -> int:
    try:
        return run_ledger(config, args.run_id, args)
    except STAGE_ERRORS as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


def cmd_run(config: Config, args: argparse.Namespace) -> int:
    run_id = args.run_id or args.video.stem
    if args.fps is not None:
        config.fps = args.fps
    try:
        manifest = extract_frames(
            args.video, config.stage_dir(run_id, "frames"), config, force=args.force
        )
        print(f"{manifest.kept}/{manifest.extracted} frames kept")
        adapter = load_adapter(args.book, config.adapters_dir)
        frames_dir = config.stage_dir(run_id, "frames")
        canvas = stitch(
            load_manifest(frames_dir).kept_paths(frames_dir),
            config.stage_dir(run_id, "canvas"),
            config,
            adapter.crop,
        )
        print(f"canvas {canvas.width}x{canvas.height}, {len(canvas.gaps)} gap(s)")
        run_extract(config, run_id, args)
        return run_ledger(config, run_id, args)
    except STAGE_ERRORS as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


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
