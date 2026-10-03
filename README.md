# SportsTaxer

Turns a screen recording of a sportsbook app's history screen into a reconciled
transaction ledger, exported to xlsx. Aimed at small books that offer no CSV export and
no API.

Pipeline: `frames` -> `stitch` -> `extract` -> `ledger` (parse, reconcile, xlsx).

## Requirements

- Python 3.11+
- ffmpeg on PATH

## Install

    pip install -e ".[dev]"

## Run

    sportstaxer --help
    sportstaxer books
    sportstaxer run recording.mp4 --book synthbook --opening 1000 --closing 1180.50

`run` chains every stage and writes `out/<run-id>.xlsx`. The stages also run one at a time:

    sportstaxer frames recording.mp4
    sportstaxer stitch recording --book synthbook
    sportstaxer extract recording --book synthbook
    sportstaxer ledger recording --book synthbook --opening 1000 --closing 1180.50

Artifacts land in `work/<run-id>/`. Each stage reads the previous stage's directory, so a
failed run resumes rather than restarting.

Extraction backends (`--backend`): `anthropic` (default, needs `pip install -e ".[vision]"`
and `ANTHROPIC_API_KEY`), `ocr` (needs the `ocr` extra and tesseract; review its output),
and `replay` (`--responses DIR` of recorded answers, fully offline).

## Output

The workbook has three sheets: `Ledger` (one row per bet, flagged rows highlighted),
`Summary` (reconciliation and per-month totals) and `Review` (every flag with its reason).

Reconciliation checks `opening + sum(net)` against `--closing`. A canvas with gaps is
refused. A mismatch still writes the workbook but exits with status 3. Without balances the
run is reported as unverified. Pending bets and rows with no computable net are excluded
from the sum and reported.

Adapter profiles in `adapters/` hold everything book-specific, including whether a
reported payout includes the returned stake.

## Known failure modes

- Some Android gambling apps set FLAG_SECURE, so the recording is a black rectangle.
  Filming the screen with a second device is the only workaround and costs accuracy.
- Inertial scrolling blurs frames and breaks scroll stitching. See docs/capture.md.
