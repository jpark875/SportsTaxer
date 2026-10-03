import shutil
import subprocess
from pathlib import Path

import pytest

from sportstaxer.synthetic import make_capture


def encode(frames, path: Path, fps: float = 2.0, hold: int = 2) -> Path:
    """Encode frames to h264, holding each for `hold` frames to mimic the scroll pause."""
    staging = path.parent / f"{path.stem}_src"
    staging.mkdir(parents=True, exist_ok=True)
    n = 0
    for frame in frames:
        for _ in range(hold):
            n += 1
            frame.save(staging / f"{n:04d}.png")

    subprocess.run(
        [
            "ffmpeg",
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-framerate",
            str(fps),
            "-i",
            str(staging / "%04d.png"),
            "-c:v",
            "libx264",
            "-crf",
            "18",
            "-pix_fmt",
            "yuv420p",
            str(path),
        ],
        check=True,
        capture_output=True,
    )
    shutil.rmtree(staging)
    return path


@pytest.fixture(scope="session")
def scroll_video(tmp_path_factory) -> Path:
    capture = make_capture(row_count=24, frame_height=640, step=300, header_height=60)
    return encode(capture.frames, tmp_path_factory.mktemp("video") / "scroll.mp4")


@pytest.fixture(scope="session")
def black_video(tmp_path_factory) -> Path:
    path = tmp_path_factory.mktemp("video") / "black.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=720x640:d=3:r=2",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(path),
        ],
        check=True,
        capture_output=True,
    )
    return path
