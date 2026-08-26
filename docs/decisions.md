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
