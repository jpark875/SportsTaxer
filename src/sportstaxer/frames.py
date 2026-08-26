"""Stage 1: video to deduplicated frames on disk.

ffmpeg samples the video at a fixed rate, then near-duplicate frames are dropped by
perceptual hash. Dedup is pure cost saving for the stages downstream and must not change
results: every dropped frame is within the hash threshold of the kept frame before it,
and the manifest records both so a run can be audited without re-extracting.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import imagehash
from PIL import Image, ImageStat
from pydantic import BaseModel

from sportstaxer.config import Config

MANIFEST_NAME = "manifest.json"


class FrameExtractionError(Exception):
    pass


class BlankVideoError(FrameExtractionError):
    """Every sampled frame is featureless, which usually means FLAG_SECURE."""


class FrameRecord(BaseModel):
    index: int
    timestamp: float
    phash: str
    kept: bool
    path: Path | None = None
    # Hash distance to the previous kept frame; None for the first frame.
    distance: int | None = None


class FrameManifest(BaseModel):
    video: Path
    fps: float
    dedup_enabled: bool
    hash_distance: int
    extracted: int
    kept: int
    frames: list[FrameRecord]

    def kept_frames(self) -> list[FrameRecord]:
        return [f for f in self.frames if f.kept]

    def kept_paths(self, frames_dir: Path) -> list[Path]:
        return [frames_dir / f.path for f in self.kept_frames() if f.path]


def extract_frames(
    video: Path,
    out_dir: Path,
    config: Config,
    force: bool = False,
) -> FrameManifest:
    """Sample video into out_dir and return the manifest, reusing a completed run."""
    if not video.is_file():
        raise FrameExtractionError(f"video not found: {video}")

    manifest_path = out_dir / MANIFEST_NAME
    if manifest_path.is_file() and not force:
        existing = FrameManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
        if (
            existing.fps == config.fps
            and existing.dedup_enabled == config.dedup.enabled
            and existing.hash_distance == config.dedup.hash_distance
        ):
            return existing

    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)

    suffix = config.frames.image_format
    _run_ffmpeg(video, out_dir / f"frame_%06d.{suffix}", config)
    paths = sorted(out_dir.glob(f"frame_*.{suffix}"))
    if not paths:
        raise FrameExtractionError(f"ffmpeg produced no frames from {video}")

    records = _scan(paths, config)
    manifest = FrameManifest(
        video=video,
        fps=config.fps,
        dedup_enabled=config.dedup.enabled,
        hash_distance=config.dedup.hash_distance,
        extracted=len(records),
        kept=sum(1 for r in records if r.kept),
        frames=records,
    )
    manifest_path.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
    return manifest


def _run_ffmpeg(video: Path, pattern: Path, config: Config) -> None:
    command = [
        "ffmpeg",
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(video),
        "-vf",
        f"fps={config.fps}",
    ]
    if config.frames.image_format == "jpg":
        command += ["-q:v", _jpeg_qscale(config.frames.jpeg_quality)]
    command.append(str(pattern))

    try:
        result = subprocess.run(command, capture_output=True, text=True)
    except FileNotFoundError as exc:
        raise FrameExtractionError("ffmpeg not found on PATH") from exc
    if result.returncode != 0:
        raise FrameExtractionError(f"ffmpeg failed on {video}:\n{result.stderr.strip()}")


def _jpeg_qscale(quality: int) -> str:
    # ffmpeg -q:v runs 2 (best) to 31 (worst), the inverse of a 1-100 quality scale.
    return str(round(2 + (100 - quality) / 99 * 29))


def _scan(paths: list[Path], config: Config) -> list[FrameRecord]:
    records: list[FrameRecord] = []
    previous_hash = None
    blank = 0

    for index, path in enumerate(paths, start=1):
        with Image.open(path) as image:
            image.load()
            frame_hash = imagehash.phash(image)
            if ImageStat.Stat(image.convert("L")).stddev[0] < config.frames.blank_std_threshold:
                blank += 1

        distance = None if previous_hash is None else int(frame_hash - previous_hash)
        keep = not config.dedup.enabled or distance is None or distance > config.dedup.hash_distance
        if keep:
            previous_hash = frame_hash
        else:
            path.unlink()

        records.append(
            FrameRecord(
                index=index,
                timestamp=(index - 1) / config.fps,
                phash=str(frame_hash),
                kept=keep,
                path=Path(path.name) if keep else None,
                distance=distance,
            )
        )

    if blank == len(paths):
        raise BlankVideoError(
            "every sampled frame is blank. Android apps that set FLAG_SECURE record as a "
            "black rectangle; see docs/capture.md for the workaround."
        )
    return records


def load_manifest(frames_dir: Path) -> FrameManifest:
    path = frames_dir / MANIFEST_NAME
    if not path.is_file():
        raise FrameExtractionError(f"no frame manifest in {frames_dir}")
    return FrameManifest.model_validate(json.loads(path.read_text(encoding="utf-8")))
