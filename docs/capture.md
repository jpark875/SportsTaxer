# Capture protocol

Recording quality determines accuracy more than any model choice. A recording that
ignores this is not worth processing.

- Scroll in discrete flicks with a one-second pause between each. Inertial scrolling
  produces motion blur that wrecks both correlation and OCR. Pauses give clean
  stationary frames.
- Overlap roughly half a screen per jump.
- Lock brightness. Do not let auto dark mode switch mid-recording. Record at native
  resolution.
- Start and end on a frame showing the account balance. Reconciliation needs an opening
  and closing balance and cannot run without both.
- One book per recording.

## FLAG_SECURE

Some Android gambling apps set FLAG_SECURE, which makes the screen recording come out as
a black rectangle. iOS is generally permissive. Frame extraction detects an all-black or
near-uniform video and fails with a message rather than producing empty output.

The only workaround is filming the screen with a second device, which costs significant
accuracy: glare, keystone distortion, moire and rolling-shutter banding all degrade both
correlation and extraction.
