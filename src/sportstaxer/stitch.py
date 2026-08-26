"""Stage 2: frames to a stitched canvas.

Registration happens in pixel space. A strip from the middle of frame N is
cross-correlated against frame N+1 to recover the vertical scroll, offsets accumulate,
and every frame is composited onto one tall canvas that gets OCR'd once.

The alternative, OCR per frame plus fuzzy row dedup, has to guess whether two extracted
rows are the same bet and has no principled confidence measure. Image registration
returns a correlation score, and rows end up truncated only at the edges of the finished
canvas rather than at every frame boundary.
"""

from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np
from pydantic import BaseModel

from sportstaxer.config import Config, CropBox

MANIFEST_NAME = "canvas.json"

# Rows left above the template strip in the later frame. Small, because everything above
# it is scroll range given up: the largest measurable scroll is the frame height less the
# strip and this margin. It exists only so a few pixels of upward drift still register as
# a negative delta rather than as an unexplained correlation failure.
SEARCH_MARGIN = 8


class StitchError(Exception):
    pass


class FramePlacement(BaseModel):
    index: int
    frame: str
    # Canvas y of the frame's cropped content top edge.
    offset: int
    # Scroll distance from the previous frame; None for the first.
    delta: int | None = None
    correlation: float | None = None
    gap: bool = False
    gap_reason: str | None = None


class CanvasSegment(BaseModel):
    index: int
    path: str
    y_start: int
    y_end: int


class CanvasManifest(BaseModel):
    """Where every frame landed on the canvas, and where the canvas cannot be trusted.

    Consumers must treat `gaps` as fatal for reconciliation: a gap means the scroll
    jumped further than the frame overlap and content between the two frames was never
    recorded.
    """

    frames_dir: Path
    crop: CropBox
    width: int
    height: int
    frame_count: int
    placements: list[FramePlacement]
    segments: list[CanvasSegment]

    @property
    def gaps(self) -> list[FramePlacement]:
        return [p for p in self.placements if p.gap]

    def segment_for(self, y: int) -> CanvasSegment | None:
        for segment in self.segments:
            if segment.y_start <= y < segment.y_end:
                return segment
        return None


def _load(path: Path) -> np.ndarray:
    image = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if image is None:
        raise StitchError(f"cannot read frame: {path}")
    return image


def _crop(image: np.ndarray, crop: CropBox) -> np.ndarray:
    height, width = image.shape[:2]
    bottom = height - crop.bottom
    right = width - crop.right
    if bottom <= crop.top or right <= crop.left:
        raise StitchError("crop removes the whole frame")
    return image[crop.top : bottom, crop.left : right]


def _match(target: np.ndarray, template_frame: np.ndarray, strip_height: int) -> tuple[int, float]:
    strip = template_frame[SEARCH_MARGIN : SEARCH_MARGIN + strip_height]
    scores = cv2.matchTemplate(
        cv2.cvtColor(target, cv2.COLOR_BGR2GRAY),
        cv2.cvtColor(strip, cv2.COLOR_BGR2GRAY),
        cv2.TM_CCOEFF_NORMED,
    )
    _, best, _, location = cv2.minMaxLoc(scores)
    return location[1] - SEARCH_MARGIN, float(best)


def measure_offset(
    previous: np.ndarray, current: np.ndarray, strip_height: int
) -> tuple[int, float]:
    """Return (scroll delta, correlation) between two cropped frames.

    A positive delta means the content moved up the screen, which is a downward scroll.

    The template comes from the top of the later frame and is searched for in the earlier
    one. Taking it from the middle of the earlier frame instead does not work at the
    overlap the capture protocol asks for: at a half-screen scroll the middle of frame N
    is off the top of frame N+1, so there is nothing to match and every pair reads as a
    gap.

    Measurable scrolls run from -SEARCH_MARGIN to (frame height - strip - SEARCH_MARGIN).
    Anything outside that falls out as a low correlation, which is reported as a gap
    rather than guessed at.
    """
    if strip_height + 2 * SEARCH_MARGIN >= previous.shape[0]:
        raise StitchError(f"strip height {strip_height} does not fit a {previous.shape[0]}px frame")
    return _match(previous, current, strip_height)


def measure_reverse(
    previous: np.ndarray, current: np.ndarray, strip_height: int
) -> tuple[int, float]:
    """Measure with the frames swapped, to name an upward scroll instead of just failing."""
    back, score = _match(current, previous, strip_height)
    return -back, score


def plan_placements(frame_paths: list[Path], config: Config, crop: CropBox) -> list[FramePlacement]:
    """Register consecutive frames and accumulate absolute canvas offsets."""
    if not frame_paths:
        raise StitchError("no frames to stitch")

    placements = [FramePlacement(index=0, frame=frame_paths[0].name, offset=0)]
    previous = _crop(_load(frame_paths[0]), crop)
    offset = 0

    for index, path in enumerate(frame_paths[1:], start=1):
        current = _crop(_load(path), crop)
        if current.shape != previous.shape:
            raise StitchError(f"frame size changed at {path.name}")

        delta, correlation = measure_offset(previous, current, config.stitch.strip_height)
        threshold = config.stitch.min_correlation
        gap_reason = None

        if delta < 0 and correlation >= threshold:
            gap_reason = f"reverse scroll of {-delta}px"
        elif correlation < threshold:
            # A scroll upward puts the template off the top of the earlier frame, so the
            # forward match fails. Retry swapped to report which of the two happened.
            back, back_correlation = measure_reverse(previous, current, config.stitch.strip_height)
            if back_correlation >= threshold and back < 0:
                gap_reason = f"reverse scroll of {-back}px"
                correlation = back_correlation
            else:
                gap_reason = f"correlation {correlation:.3f} below {threshold}"

        if gap_reason:
            # Never splice on a bad estimate. Butt the frame against the previous one so
            # nothing is silently overwritten, and let reconciliation refuse the run.
            delta = previous.shape[0]

        offset += delta
        placements.append(
            FramePlacement(
                index=index,
                frame=path.name,
                offset=offset,
                delta=delta,
                correlation=correlation,
                gap=gap_reason is not None,
                gap_reason=gap_reason,
            )
        )
        previous = current

    return placements


def _segment_ranges(height: int, max_height: int, overlap: int) -> list[tuple[int, int]]:
    if height <= max_height:
        return [(0, height)]
    if overlap >= max_height:
        raise StitchError("segment overlap must be smaller than the canvas height cap")

    ranges = []
    start = 0
    while start < height:
        end = min(start + max_height, height)
        ranges.append((start, end))
        if end == height:
            break
        start = end - overlap
    return ranges


def stitch(
    frame_paths: list[Path],
    out_dir: Path,
    config: Config,
    crop: CropBox | None = None,
) -> CanvasManifest:
    """Composite frames into one or more canvas images and write them with a manifest."""
    crop = crop or CropBox()
    placements = plan_placements(frame_paths, config, crop)

    first = _crop(_load(frame_paths[0]), crop)
    frame_height, width = first.shape[:2]
    height = placements[-1].offset + frame_height

    out_dir.mkdir(parents=True, exist_ok=True)
    by_name = {path.name: path for path in frame_paths}
    segments = []

    for index, (y_start, y_end) in enumerate(
        _segment_ranges(height, config.stitch.max_canvas_height, config.stitch.segment_overlap)
    ):
        canvas = np.zeros((y_end - y_start, width, 3), dtype=np.uint8)
        for placement in placements:
            top, bottom = placement.offset, placement.offset + frame_height
            if bottom <= y_start or top >= y_end:
                continue
            content = _crop(_load(by_name[placement.frame]), crop)
            visible_top = max(top, y_start)
            visible_bottom = min(bottom, y_end)
            canvas[visible_top - y_start : visible_bottom - y_start] = content[
                visible_top - top : visible_bottom - top
            ]

        path = out_dir / f"canvas_{index:03d}.png"
        if not cv2.imwrite(str(path), canvas):
            raise StitchError(f"cannot write canvas: {path}")
        segments.append(CanvasSegment(index=index, path=path.name, y_start=y_start, y_end=y_end))

    manifest = CanvasManifest(
        frames_dir=frame_paths[0].parent,
        crop=crop,
        width=width,
        height=height,
        frame_count=len(frame_paths),
        placements=placements,
        segments=segments,
    )
    (out_dir / MANIFEST_NAME).write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
    return manifest


def load_canvas_manifest(canvas_dir: Path) -> CanvasManifest:
    path = canvas_dir / MANIFEST_NAME
    if not path.is_file():
        raise StitchError(f"no canvas manifest in {canvas_dir}")
    return CanvasManifest.model_validate(json.loads(path.read_text(encoding="utf-8")))
