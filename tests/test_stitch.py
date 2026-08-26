from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from sportstaxer.config import Config, CropBox
from sportstaxer.stitch import (
    StitchError,
    load_canvas_manifest,
    measure_offset,
    plan_placements,
    stitch,
)
from sportstaxer.synthetic import make_capture


def write_frames(frames, directory: Path) -> list[Path]:
    directory.mkdir(parents=True, exist_ok=True)
    paths = []
    for i, frame in enumerate(frames):
        path = directory / f"frame_{i:04d}.png"
        frame.save(path)
        paths.append(path)
    return paths


def read(path: Path) -> Image.Image:
    return Image.open(path).convert("RGB")


def assert_identical(a: Image.Image, b: Image.Image) -> None:
    assert a.size == b.size
    assert np.array_equal(np.asarray(a), np.asarray(b))


def test_offsets_are_recovered_exactly(tmp_path):
    capture = make_capture(row_count=30, frame_height=640, step=300)
    paths = write_frames(capture.frames, tmp_path / "frames")

    placements = plan_placements(paths, Config(), CropBox())
    recovered = [p.offset for p in placements]

    assert recovered == capture.offsets
    assert all(p.correlation > 0.99 for p in placements[1:])
    assert not any(p.gap for p in placements)


def test_reconstruction_is_pixel_exact(tmp_path):
    capture = make_capture(row_count=30, frame_height=640, step=300)
    paths = write_frames(capture.frames, tmp_path / "frames")

    manifest = stitch(paths, tmp_path / "canvas", Config())

    assert manifest.height == capture.canvas.height
    assert len(manifest.segments) == 1
    assert_identical(read(tmp_path / "canvas" / manifest.segments[0].path), capture.canvas)


def test_reconstruction_is_pixel_exact_with_chrome_cropped(tmp_path):
    capture = make_capture(
        row_count=30, frame_height=640, step=300, header_height=60, footer_height=50
    )
    paths = write_frames(capture.frames, tmp_path / "frames")
    crop = CropBox(top=capture.header_height, bottom=capture.footer_height)

    manifest = stitch(paths, tmp_path / "canvas", Config(), crop)
    stitched = read(tmp_path / "canvas" / manifest.segments[0].path)

    # Content under the sticky chrome is never recorded, so the canvas covers the source
    # from the first frame's header edge to the last frame's footer edge.
    top = capture.header_height
    bottom = capture.offsets[-1] + 640 - capture.footer_height
    assert_identical(stitched, capture.canvas.crop((0, top, capture.canvas.width, bottom)))


def test_uncropped_chrome_destroys_the_offset_estimate(tmp_path):
    """The reason crop regions are mandatory rather than an optimisation."""
    capture = make_capture(row_count=30, frame_height=640, step=200, header_height=300)
    paths = write_frames(capture.frames, tmp_path / "frames")

    uncropped = plan_placements(paths, Config(), CropBox())
    cropped = plan_placements(paths, Config(), CropBox(top=300))

    assert [p.offset for p in uncropped] != capture.offsets
    assert [p.offset for p in cropped] == capture.offsets


def test_varying_scroll_steps(tmp_path):
    from sportstaxer.synthetic import make_rows, render_canvas, slice_frames

    canvas = render_canvas(make_rows(30, seed=5))
    offsets = [0, 120, 400, 430, 900, 1300, 1320]
    paths = write_frames(slice_frames(canvas, 640, offsets), tmp_path / "frames")

    placements = plan_placements(paths, Config(), CropBox())
    assert [p.offset for p in placements] == offsets


def test_scroll_beyond_the_overlap_is_flagged_not_spliced(tmp_path):
    from sportstaxer.synthetic import make_rows, render_canvas, slice_frames

    canvas = render_canvas(make_rows(60, seed=7))
    # A jump larger than a frame: the content between the two frames was never recorded.
    offsets = [0, 300, 2200, 2500]
    paths = write_frames(slice_frames(canvas, 640, offsets), tmp_path / "frames")

    placements = plan_placements(paths, Config(), CropBox())
    gaps = [p for p in placements if p.gap]

    assert len(gaps) == 1
    assert gaps[0].index == 2
    assert gaps[0].correlation < 0.9
    # Butted against the previous frame rather than spliced at a guessed offset.
    assert gaps[0].offset == placements[1].offset + 640


def test_reverse_scroll_is_flagged(tmp_path):
    from sportstaxer.synthetic import make_rows, render_canvas, slice_frames

    canvas = render_canvas(make_rows(30, seed=9))
    paths = write_frames(slice_frames(canvas, 640, [0, 300, 200]), tmp_path / "frames")

    placements = plan_placements(paths, Config(), CropBox())
    assert placements[2].gap
    assert "reverse scroll" in placements[2].gap_reason


def test_stationary_frames_do_not_advance_the_canvas(tmp_path):
    capture = make_capture(row_count=20, frame_height=640, step=300)
    frames = [capture.frames[0], capture.frames[0], capture.frames[1]]
    paths = write_frames(frames, tmp_path / "frames")

    placements = plan_placements(paths, Config(), CropBox())
    assert [p.offset for p in placements] == [0, 0, 300]


def test_segments_split_with_overlap_and_cover_the_canvas(tmp_path):
    capture = make_capture(row_count=40, frame_height=640, step=300)
    paths = write_frames(capture.frames, tmp_path / "frames")
    config = Config(stitch={"max_canvas_height": 1500, "segment_overlap": 200})

    manifest = stitch(paths, tmp_path / "canvas", config)

    assert len(manifest.segments) > 1
    assert manifest.segments[0].y_start == 0
    assert manifest.segments[-1].y_end == manifest.height
    for a, b in zip(manifest.segments, manifest.segments[1:], strict=False):
        assert b.y_start == a.y_end - 200
        assert (a.y_end - a.y_start) <= 1500

    for segment in manifest.segments:
        expected = capture.canvas.crop((0, segment.y_start, capture.canvas.width, segment.y_end))
        assert_identical(read(tmp_path / "canvas" / segment.path), expected)


def test_manifest_round_trips_and_locates_segments(tmp_path):
    capture = make_capture(row_count=40, frame_height=640, step=300)
    paths = write_frames(capture.frames, tmp_path / "frames")
    config = Config(stitch={"max_canvas_height": 1500, "segment_overlap": 200})

    manifest = stitch(paths, tmp_path / "canvas", config)
    assert load_canvas_manifest(tmp_path / "canvas") == manifest
    assert manifest.segment_for(0).index == 0
    assert manifest.segment_for(manifest.height - 1).index == len(manifest.segments) - 1
    assert manifest.segment_for(manifest.height) is None


def test_measure_offset_rejects_an_oversized_strip():
    capture = make_capture(row_count=10, frame_height=640, step=300)
    a = np.asarray(capture.frames[0])[:, :, ::-1].copy()
    b = np.asarray(capture.frames[1])[:, :, ::-1].copy()
    with pytest.raises(StitchError, match="strip height"):
        measure_offset(a, b, 640)


def test_empty_input_is_an_error(tmp_path):
    with pytest.raises(StitchError, match="no frames"):
        plan_placements([], Config(), CropBox())


def test_crop_that_removes_everything_is_an_error(tmp_path):
    capture = make_capture(row_count=10, frame_height=640, step=300)
    paths = write_frames(capture.frames, tmp_path / "frames")
    with pytest.raises(StitchError, match="crop removes"):
        plan_placements(paths, Config(), CropBox(top=400, bottom=400))


def test_scroll_larger_than_the_measurable_range_is_flagged(tmp_path):
    """A 600px scroll on a 640px frame leaves 40px of overlap: real content, but less
    than the correlation window needs. Flagged rather than assumed."""
    from sportstaxer.synthetic import make_rows, render_canvas, slice_frames

    canvas = render_canvas(make_rows(40, seed=11))
    paths = write_frames(slice_frames(canvas, 640, [0, 300, 900]), tmp_path / "frames")

    placements = plan_placements(paths, Config(), CropBox())
    assert placements[2].gap
    assert "below" in placements[2].gap_reason
