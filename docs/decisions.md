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
