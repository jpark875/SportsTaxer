import shutil
from pathlib import Path

import imagehash
import pytest

from sportstaxer.config import Config
from sportstaxer.frames import (
    BlankVideoError,
    FrameExtractionError,
    extract_frames,
    load_manifest,
)

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not on PATH")


def config_for(tmp_path: Path, **kwargs) -> Config:
    config = Config(work_dir=tmp_path, **kwargs)
    return config


def test_extracts_frames_and_writes_manifest(scroll_video, tmp_path):
    config = config_for(tmp_path)
    out = tmp_path / "frames"
    manifest = extract_frames(scroll_video, out, config)

    assert manifest.extracted > manifest.kept > 1
    assert manifest.video == scroll_video
    assert load_manifest(out) == manifest
    assert len(list(out.glob("frame_*.png"))) == manifest.kept


def test_dropped_frames_are_removed_from_disk(scroll_video, tmp_path):
    out = tmp_path / "frames"
    manifest = extract_frames(scroll_video, out, config_for(tmp_path))
    for record in manifest.frames:
        if not record.kept:
            assert record.path is None
    assert sorted(p.name for p in out.glob("*.png")) == sorted(
        r.path.name for r in manifest.kept_frames()
    )


def test_dedup_drops_only_near_duplicates(scroll_video, tmp_path):
    """Dedup must be derivable from the full frame sequence, not from anything else.

    Run with dedup off, replay the threshold rule over those hashes, and the kept set
    has to match the deduplicated run exactly. That is the guarantee that dedup is a
    cost saving and not a change in results.
    """
    full = extract_frames(
        scroll_video, tmp_path / "full", config_for(tmp_path, dedup={"enabled": False})
    )
    deduped = extract_frames(scroll_video, tmp_path / "deduped", config_for(tmp_path))

    assert full.kept == full.extracted
    assert deduped.extracted == full.extracted

    threshold = deduped.hash_distance
    expected = []
    previous = None
    for record in full.frames:
        current = imagehash.hex_to_hash(record.phash)
        if previous is None or int(current - previous) > threshold:
            expected.append(record.index)
            previous = current

    assert [r.index for r in deduped.kept_frames()] == expected


def test_timestamps_follow_the_sampling_rate(scroll_video, tmp_path):
    manifest = extract_frames(scroll_video, tmp_path / "frames", config_for(tmp_path, fps=1.0))
    assert manifest.frames[0].timestamp == 0.0
    assert manifest.frames[1].timestamp == 1.0


def test_higher_fps_samples_more_frames(scroll_video, tmp_path):
    low = extract_frames(scroll_video, tmp_path / "low", config_for(tmp_path, fps=1.0))
    high = extract_frames(scroll_video, tmp_path / "high", config_for(tmp_path, fps=2.0))
    assert high.extracted > low.extracted


def test_black_video_names_flag_secure(black_video, tmp_path):
    with pytest.raises(BlankVideoError, match="FLAG_SECURE"):
        extract_frames(black_video, tmp_path / "frames", config_for(tmp_path))


def test_missing_video_is_an_error(tmp_path):
    with pytest.raises(FrameExtractionError, match="video not found"):
        extract_frames(tmp_path / "nope.mp4", tmp_path / "frames", config_for(tmp_path))


def test_completed_run_is_reused(scroll_video, tmp_path):
    out = tmp_path / "frames"
    first = extract_frames(scroll_video, out, config_for(tmp_path))
    (out / "sentinel").write_text("x", encoding="utf-8")

    assert extract_frames(scroll_video, out, config_for(tmp_path)) == first
    assert (out / "sentinel").exists()

    extract_frames(scroll_video, out, config_for(tmp_path), force=True)
    assert not (out / "sentinel").exists()


def test_changed_settings_invalidate_a_previous_run(scroll_video, tmp_path):
    out = tmp_path / "frames"
    extract_frames(scroll_video, out, config_for(tmp_path))
    (out / "sentinel").write_text("x", encoding="utf-8")

    extract_frames(scroll_video, out, config_for(tmp_path, fps=1.0))
    assert not (out / "sentinel").exists()


def test_jpeg_output(scroll_video, tmp_path):
    config = config_for(tmp_path, frames={"image_format": "jpg"})
    manifest = extract_frames(scroll_video, tmp_path / "frames", config)
    assert all(r.path.suffix == ".jpg" for r in manifest.kept_frames())
