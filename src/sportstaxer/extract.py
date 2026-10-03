"""Stage 3: canvas to raw rows.

Money fields are read more than once. Disagreements are flagged, never resolved.
"""

from __future__ import annotations

import base64
import io
import json
from pathlib import Path
from typing import Protocol

from PIL import Image
from pydantic import BaseModel, Field

from sportstaxer.adapters import Adapter
from sportstaxer.config import Config
from sportstaxer.schema import BBox, ExtractionResult, RawField, RawRow
from sportstaxer.stitch import CanvasManifest

RESULT_NAME = "extraction.json"


class ExtractionError(Exception):
    pass


class Tile(BaseModel):
    """A slice of a canvas segment, small enough to send to a model as one image."""

    segment: int
    index: int
    # Canvas y of the tile's top edge, for translating model coordinates back.
    y_offset: int
    image_path: Path


class ModelField(BaseModel):
    value: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)


class ModelRow(BaseModel):
    """The per-row schema handed to the model. Coordinates are tile-relative."""

    date: ModelField
    description: ModelField
    bet_type: ModelField
    stake: ModelField
    payout: ModelField
    result: ModelField
    balance: ModelField
    y_top: int
    y_bottom: int


class ModelResponse(BaseModel):
    rows: list[ModelRow]


class Backend(Protocol):
    name: str

    def read_tile(self, tile: Tile, image: Image.Image, adapter: Adapter) -> ModelResponse: ...


def build_prompt(adapter: Adapter) -> str:
    terms = adapter.terminology
    return f"""Read every settled or pending bet row visible in this screenshot of the
{adapter.display_name} bet history screen. The image is a vertical strip of a longer
screen that has been stitched together, so the topmost and bottommost rows may be cut off.

{adapter.layout_hints}

Rules:
- One object per bet row, in top-to-bottom order.
- Transcribe amounts exactly as shown, including the currency symbol and separators. Do
  not convert, round or compute anything.
- This book labels the amount risked as one of: {", ".join(terms.stake)}. It labels the
  amount returned as one of: {", ".join(terms.payout)}. An amount labelled as one of
  {", ".join(terms.potential)} is a potential return on an unsettled bet, not a payout;
  leave payout null for those rows.
- Set a field to null when the row does not show it. Do not infer a missing value from
  another row.
- confidence is your own reading confidence for that field alone, 0 to 1. Use a low
  confidence for text that is blurred, clipped at the image edge, or partly covered.
- y_top and y_bottom are the pixel rows of the top and bottom edge of the row within
  this image.
- A row clipped by the top or bottom edge of the image still gets an object, with low
  confidence on whatever is cut off."""


class AnthropicBackend:
    """Vision extraction through the Anthropic API. The client is built lazily so other
    stages need neither the SDK nor an API key.
    """

    def __init__(self, model: str, max_tokens: int, client=None):
        self.name = "anthropic"
        self.model = model
        self.max_tokens = max_tokens
        self._client = client

    @property
    def client(self):
        if self._client is None:
            try:
                import anthropic
            except ImportError as exc:
                raise ExtractionError(
                    "the anthropic package is not installed; install the vision extra "
                    "or run with --backend ocr"
                ) from exc
            self._client = anthropic.Anthropic()
        return self._client

    def read_tile(self, tile: Tile, image: Image.Image, adapter: Adapter) -> ModelResponse:
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        encoded = base64.standard_b64encode(buffer.getvalue()).decode("ascii")

        response = self.client.messages.parse(
            model=self.model,
            max_tokens=self.max_tokens,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/png",
                                "data": encoded,
                            },
                        },
                        {"type": "text", "text": build_prompt(adapter)},
                    ],
                }
            ],
            output_format=ModelResponse,
        )
        if response.parsed_output is None:
            raise ExtractionError(f"model returned no parsable rows (stop {response.stop_reason})")
        return response.parsed_output


class ReplayBackend:
    """Replays recorded responses so fixtures run offline and deterministically."""

    def __init__(self, responses_dir: Path):
        self.name = "replay"
        self.responses_dir = responses_dir

    @staticmethod
    def filename(tile: Tile) -> str:
        return f"tile_{tile.segment:03d}_{tile.index:03d}.json"

    def read_tile(self, tile: Tile, image: Image.Image, adapter: Adapter) -> ModelResponse:
        path = self.responses_dir / self.filename(tile)
        if not path.is_file():
            raise ExtractionError(f"no recorded response at {path}")
        return ModelResponse.model_validate(json.loads(path.read_text(encoding="utf-8")))


def make_backend(config: Config) -> Backend:
    choice = config.extract.backend
    if choice == "anthropic":
        return AnthropicBackend(config.extract.model, config.extract.max_tokens)
    if choice == "ocr":
        from sportstaxer.ocr import TesseractBackend

        return TesseractBackend()
    raise ExtractionError(f"backend {choice!r} cannot be constructed from config alone")


def plan_tiles(manifest: CanvasManifest, canvas_dir: Path, config: Config) -> list[Tile]:
    tiles = []
    for segment in manifest.segments:
        source = Image.open(canvas_dir / segment.path).convert("RGB")
        height = source.height
        step = config.extract.tile_height - config.extract.tile_overlap
        if step <= 0:
            raise ExtractionError("tile overlap must be smaller than tile height")

        starts = list(range(0, max(height - config.extract.tile_overlap, 1), step))
        for index, start in enumerate(starts):
            end = min(start + config.extract.tile_height, height)
            path = canvas_dir / f"tile_{segment.index:03d}_{index:03d}.png"
            source.crop((0, start, source.width, end)).save(path)
            tiles.append(
                Tile(
                    segment=segment.index,
                    index=index,
                    y_offset=segment.y_start + start,
                    image_path=path,
                )
            )
    return tiles


def _to_raw(row: ModelRow, tile: Tile, width: int) -> RawRow:
    return RawRow(
        date=RawField(value=row.date.value, confidence=row.date.confidence),
        description=RawField(value=row.description.value, confidence=row.description.confidence),
        bet_type=RawField(value=row.bet_type.value, confidence=row.bet_type.confidence),
        stake=RawField(value=row.stake.value, confidence=row.stake.confidence),
        payout=RawField(value=row.payout.value, confidence=row.payout.confidence),
        result=RawField(value=row.result.value, confidence=row.result.confidence),
        balance=RawField(value=row.balance.value, confidence=row.balance.confidence),
        bbox=BBox(
            x=0,
            y=tile.y_offset + row.y_top,
            width=width,
            height=max(row.y_bottom - row.y_top, 1),
        ),
        segment=tile.segment,
    )


def _find_duplicate(rows: list[RawRow], candidate: RawRow, threshold: float) -> RawRow | None:
    """Return the already-seen row that `candidate` duplicates by bbox overlap, if any."""
    for existing in rows:
        if existing.bbox.iou(candidate.bbox) >= threshold:
            return existing
    return None


def _compare_money(kept: RawRow, other: RawRow) -> None:
    for name, field in kept.money().items():
        rival = getattr(other, name)
        left = (field.value or "").strip()
        right = (rival.value or "").strip()
        if left != right:
            flag = f"money disagreement: {name} {left or 'null'} vs {right or 'null'}"
            if flag not in kept.flags:
                kept.flags.append(flag)
            # Neither reading is trusted from here on. No winner, no average.
            field.confidence = 0.0


def extract_canvas(
    manifest: CanvasManifest,
    canvas_dir: Path,
    adapter: Adapter,
    config: Config,
    backend: Backend | None = None,
) -> ExtractionResult:
    """Read every row off the canvas and write the result next to it."""
    backend = backend or make_backend(config)
    tiles = plan_tiles(manifest, canvas_dir, config)
    if not tiles:
        raise ExtractionError(f"no canvas tiles in {canvas_dir}")

    rows: list[RawRow] = []
    for pass_index in range(config.extract.money_passes):
        for tile in tiles:
            image = Image.open(tile.image_path).convert("RGB")
            response = backend.read_tile(tile, image, adapter)
            for model_row in response.rows:
                candidate = _to_raw(model_row, tile, manifest.width)
                existing = _find_duplicate(rows, candidate, config.extract.same_row_iou)
                if existing is None:
                    if pass_index:
                        candidate.flags.append(f"row seen only on pass {pass_index + 1}")
                    rows.append(candidate)
                else:
                    _compare_money(existing, candidate)

    rows.sort(key=lambda row: row.bbox.y)
    result = ExtractionResult(
        backend=backend.name,
        model=config.extract.model if backend.name == "anthropic" else None,
        passes=config.extract.money_passes,
        canvas_dir=str(canvas_dir),
        rows=rows,
    )
    (canvas_dir / RESULT_NAME).write_text(result.model_dump_json(indent=2), encoding="utf-8")
    return result


def load_extraction(canvas_dir: Path) -> ExtractionResult:
    path = canvas_dir / RESULT_NAME
    if not path.is_file():
        raise ExtractionError(f"no extraction result in {canvas_dir}")
    return ExtractionResult.model_validate(json.loads(path.read_text(encoding="utf-8")))
