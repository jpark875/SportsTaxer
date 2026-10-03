"""Pipeline configuration. Stages take a Config and never read files or env themselves."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, ValidationError

CONFIG_FILENAME = "sportstaxer.yaml"


class ConfigError(Exception):
    pass


class DedupConfig(BaseModel):
    enabled: bool = True
    # Perceptual hash Hamming distance below which a frame counts as a duplicate of the
    # previous kept frame. Provisional until measured against a real recording.
    hash_distance: int = Field(default=4, ge=0)


class FramesConfig(BaseModel):
    image_format: Literal["png", "jpg"] = "png"
    jpeg_quality: int = Field(default=90, ge=1, le=100)
    # Grayscale standard deviation below which a frame counts as featureless. A
    # FLAG_SECURE capture reads as 0; real frames of a dark app UI measure above 20.
    blank_std_threshold: float = Field(default=3.0, ge=0.0)


class ExtractConfig(BaseModel):
    backend: Literal["anthropic", "ocr", "replay"] = "anthropic"
    model: str = "claude-opus-5-5"
    # Overlap must exceed the tallest ledger row or a boundary row is read in neither tile.
    tile_height: int = Field(default=1400, gt=0)
    tile_overlap: int = Field(default=260, ge=0)
    # Money fields are read twice and any disagreement is flagged rather than resolved.
    money_passes: int = Field(default=2, ge=1)
    # Bounding-box overlap above which two reads are treated as the same row.
    same_row_iou: float = Field(default=0.5, gt=0.0, le=1.0)
    max_tokens: int = Field(default=16000, gt=0)


class CropBox(BaseModel):
    """Pixels to crop from each edge. Sticky chrome left in pins the offset estimate at zero."""

    top: int = Field(default=0, ge=0)
    bottom: int = Field(default=0, ge=0)
    left: int = Field(default=0, ge=0)
    right: int = Field(default=0, ge=0)


class StitchConfig(BaseModel):
    # Cross-correlation score below which the offset estimate is not trusted and a gap
    # marker is recorded instead of splicing.
    min_correlation: float = Field(default=0.9, ge=0.0, le=1.0)
    # Taller than one ledger row, short enough to survive a half-screen scroll.
    strip_height: int = Field(default=120, gt=0)
    max_canvas_height: int = Field(default=20_000, gt=0)
    segment_overlap: int = Field(default=400, ge=0)


class LedgerConfig(BaseModel):
    # Fields read below this confidence put the row on the review list.
    min_confidence: float = Field(default=0.8, ge=0.0, le=1.0)
    # History screens often omit the year; used for date formats that lack %Y.
    assume_year: int | None = None


class Config(BaseModel):
    model_config = {"extra": "forbid"}

    fps: float = Field(default=2.0, gt=0)
    frames: FramesConfig = FramesConfig()
    extract: ExtractConfig = ExtractConfig()
    dedup: DedupConfig = DedupConfig()
    stitch: StitchConfig = StitchConfig()
    ledger: LedgerConfig = LedgerConfig()
    work_dir: Path = Path("work")
    out_dir: Path = Path("out")
    adapters_dir: Path = Path("adapters")

    def stage_dir(self, run_id: str, stage: str) -> Path:
        """Where a stage writes its intermediate artifacts for a given run."""
        return self.work_dir / run_id / stage


def find_config(start: Path) -> Path | None:
    for directory in [start, *start.parents]:
        candidate = directory / CONFIG_FILENAME
        if candidate.is_file():
            return candidate
    return None


def load_config(path: Path | None = None) -> Config:
    """Load config from path, or from the nearest sportstaxer.yaml, or use defaults."""
    if path is None:
        path = find_config(Path.cwd())
    if path is None:
        return Config()
    if not path.is_file():
        raise ConfigError(f"config file not found: {path}")

    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ConfigError(f"config file must contain a mapping: {path}")
    try:
        config = Config.model_validate(raw)
    except ValidationError as exc:
        raise ConfigError(f"invalid config in {path}:\n{exc}") from exc

    # Relative paths in the file are relative to the file, not the cwd of the caller.
    base = path.parent
    if not config.work_dir.is_absolute():
        config.work_dir = base / config.work_dir
    if not config.out_dir.is_absolute():
        config.out_dir = base / config.out_dir
    if not config.adapters_dir.is_absolute():
        config.adapters_dir = base / config.adapters_dir
    return config
