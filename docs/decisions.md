# Design decisions

Appended to as we go. Dated entries, newest last.

## 2026-08-25 - config is a single pydantic model loaded once

Stages take a `Config` and never read files or the environment themselves. That is what
makes a stage runnable standalone against a fixture without the stages before it. Unknown
keys are rejected rather than ignored, because a silently ignored typo in a threshold
would change results without any visible sign.

Relative paths in the config file resolve against the file rather than the working
directory, so a run behaves the same regardless of where it was invoked from.

## 2026-08-25 - argparse rather than typer

The brief has no preference and argparse is in the standard library. Subcommands are one
per pipeline stage. Nothing in the CLI so far justifies a dependency.

## 2026-08-25 - pyyaml added to dependencies

The brief specifies YAML adapter profiles but does not list a YAML parser in the stack.
pyyaml is the parser; config loading uses it too rather than carrying a second format.

## 2026-08-25 - dedup by perceptual hash, verified by replay

Frames are dropped when their phash is within a Hamming distance of the previous kept
frame. The correctness argument is that the decision depends on nothing but the frame
sequence, so a test extracts with dedup off, replays the threshold rule over the recorded
hashes, and asserts the kept set matches the deduplicated run exactly. Every frame's hash
goes in the manifest whether it was kept or not, which is what makes that replay possible
after the dropped files are gone.

On synthetic captures held four frames per scroll position, thresholds from 2 to 12 all
recover exactly the distinct positions and drop 75% of frames, so the default of 4 is not
a delicate choice. That is a property of clean synthetic input; it has to be re-measured
against a real recording, where compression noise raises distances between identical
positions.

Known risk for the real-recording milestone: dedup runs before any cropping, so a ticking
OS clock is inside the hashed image. A clock large enough to move the phash would defeat
dedup entirely. Cropping before hashing would fix it but makes dedup depend on adapter
config, so it stays as is until a real recording shows it is needed.

## 2026-08-25 - blank video detection is a stage 1 failure

An all-black capture is the FLAG_SECURE case, and it has to fail loudly rather than
produce an empty ledger. The check is grayscale standard deviation per frame, and it only
fires when every sampled frame is featureless, so a recording that opens on a black splash
screen still runs.

## 2026-08-25 - registration template comes from the later frame, not the earlier one

The brief describes taking a strip from the middle of frame N and correlating it against
frame N+1. That cannot work at the overlap the capture protocol asks for: after a
half-screen scroll the middle of frame N is off the top of frame N+1, so the best match
is noise and every pair reads as a gap. Measured on synthetic frames, the correlation for
a correct 300px scroll came out at 0.47 with the strip taken that way.

The template is instead taken from near the top of the later frame and searched for in the
earlier one, which is the same registration with the roles swapped. Content at the top of
N+1 came from lower down in N, so it is present in both.

The strip sits SEARCH_MARGIN (8px) below the top edge. Everything above the strip is
scroll range given up, since the largest measurable scroll is the frame height less the
strip and the margin. The margin is not zero only so that a few pixels of upward drift
register as a negative delta rather than as an unexplained correlation failure.

A scroll too large to measure is not an error in itself: at 600px on a 640px frame there
is still 40px of real overlap and no content is lost. It is still reported as a gap,
because the alternative is trusting an offset the correlation does not support.

## 2026-08-25 - gaps butt frames rather than splice them

When correlation is below threshold the frame is placed directly below the previous one
with no overlap. Nothing is overwritten, the discontinuity is visible when you open the
canvas, and the placement is recorded with the reason. Reconciliation treats any gap as
fatal.

## 2026-08-25 - stitching measured against compressed video

End to end on a synthetic capture encoded to h264 and re-extracted: 12 of 48 frames kept,
every offset recovered exactly (canvas height 3730px against a true content height of
3730px), correlation minimum 0.999. Remaining pixel difference against the lossless canvas
is 0.6/255 mean, which is h264 quantisation and not registration error.

This is a rehearsal, not the real-recording milestone. What it does not exercise: a real
device's rolling shutter, variable frame timing, inertial scroll blur, and chrome whose
crop regions were guessed rather than known.

## 2026-08-25 - payout_includes_stake has no default

An adapter profile that omits it fails to load. Every other field can fall back to
something sensible, but guessing this one wrong changes reported gross winnings by the
stake on every settled bet, and it is not detectable downstream without a balance to
reconcile against.
