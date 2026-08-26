# SportsTaxer

Turns a screen recording of a sportsbook app's history screen into a reconciled
transaction ledger, exported to xlsx. Aimed at small books that offer no CSV export and
no API.

Status: milestone 2. Frame extraction works; stitching and everything after it does not.

## Requirements

- Python 3.11+
- ffmpeg on PATH

## Install

    pip install -e ".[dev]"

## Run

    sportstaxer --help
    sportstaxer frames recording.mp4

Artifacts land in `work/<run-id>/`. Each stage reads the previous stage's directory, so a
failed run resumes rather than restarting.

## Known failure modes

- Some Android gambling apps set FLAG_SECURE, so the recording is a black rectangle.
  Filming the screen with a second device is the only workaround and costs accuracy.
- Inertial scrolling blurs frames and breaks scroll stitching. See docs/capture.md.
