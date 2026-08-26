import pytest
from PIL import ImageChops

from sportstaxer.synthetic import (
    make_capture,
    make_rows,
    plan_offsets,
    render_canvas,
    slice_frames,
)


def test_rows_are_deterministic_for_a_seed():
    assert make_rows(20, seed=3) == make_rows(20, seed=3)
    assert make_rows(20, seed=3) != make_rows(20, seed=4)


def test_lost_bets_pay_nothing():
    for row in make_rows(200, seed=1):
        assert (row.payout == 0.0) == (row.result == "Lost")


def test_canvas_height_follows_row_count():
    canvas = render_canvas(make_rows(12, seed=0), width=640, row_height=80)
    assert canvas.size == (640, 960)


def test_plan_offsets_covers_the_whole_canvas():
    offsets = plan_offsets(2000, 640, 300)
    assert offsets[0] == 0
    assert offsets[-1] == 1360
    assert all(b - a <= 300 for a, b in zip(offsets, offsets[1:], strict=False))


def test_plan_offsets_rejects_impossible_geometry():
    with pytest.raises(ValueError):
        plan_offsets(500, 640, 100)
    with pytest.raises(ValueError):
        plan_offsets(2000, 640, 0)


def test_frames_are_exact_crops_of_the_canvas():
    capture = make_capture(row_count=20, frame_height=640, step=300)
    for frame, offset in zip(capture.frames, capture.offsets, strict=True):
        expected = capture.canvas.crop((0, offset, capture.canvas.width, offset + 640))
        assert ImageChops.difference(frame, expected).getbbox() is None


def test_consecutive_frames_overlap_by_the_step():
    capture = make_capture(row_count=20, frame_height=640, step=300)
    first, second = capture.frames[0], capture.frames[1]
    assert (
        ImageChops.difference(
            first.crop((0, 300, 720, 640)), second.crop((0, 0, 720, 340))
        ).getbbox()
        is None
    )


def test_chrome_covers_content_and_the_clock_ticks():
    capture = make_capture(row_count=20, header_height=60, footer_height=50)
    first, second = capture.frames[0], capture.frames[1]
    header_first, header_second = first.crop((0, 0, 720, 60)), second.crop((0, 0, 720, 60))
    assert ImageChops.difference(header_first, header_second).getbbox() is not None
    body_only = capture.canvas.crop((0, 0, 720, 60))
    assert ImageChops.difference(header_first, body_only).getbbox() is not None


def test_slice_frames_rejects_offsets_off_the_canvas():
    canvas = render_canvas(make_rows(5, seed=0))
    with pytest.raises(ValueError):
        slice_frames(canvas, 200, [canvas.height - 100])
