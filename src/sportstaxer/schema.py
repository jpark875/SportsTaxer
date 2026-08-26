"""Types shared by extraction, parsing, reconciliation, review and export.

Two layers on purpose. `RawRow` is what a model or OCR engine said, with confidences and
pixel provenance and no interpretation. `LedgerRow` (in parse.py) is what the numbers
mean once an adapter's conventions have been applied. Keeping them apart is what makes it
possible to re-parse a run without re-extracting it, and to show a reviewer the pixels
behind a figure.
"""

from __future__ import annotations

from typing import ClassVar

from pydantic import BaseModel, Field


class BBox(BaseModel):
    x: int
    y: int
    width: int
    height: int

    @property
    def bottom(self) -> int:
        return self.y + self.height

    @property
    def right(self) -> int:
        return self.x + self.width

    def iou(self, other: BBox) -> float:
        overlap_x = max(0, min(self.right, other.right) - max(self.x, other.x))
        overlap_y = max(0, min(self.bottom, other.bottom) - max(self.y, other.y))
        intersection = overlap_x * overlap_y
        if not intersection:
            return 0.0
        union = self.width * self.height + other.width * other.height - intersection
        return intersection / union

    def shifted(self, dy: int) -> BBox:
        return BBox(x=self.x, y=self.y + dy, width=self.width, height=self.height)


class RawField(BaseModel):
    value: str | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)

    def __bool__(self) -> bool:
        return bool(self.value and self.value.strip())


class RawRow(BaseModel):
    """One row as read off the canvas, before any interpretation.

    `bbox` is in canvas coordinates, which is what lets the review UI crop the source
    pixels for a figure and what the export's provenance column points at.
    """

    date: RawField = RawField()
    description: RawField = RawField()
    bet_type: RawField = RawField()
    stake: RawField = RawField()
    payout: RawField = RawField()
    result: RawField = RawField()
    balance: RawField = RawField()
    bbox: BBox
    segment: int = 0
    flags: list[str] = Field(default_factory=list)

    MONEY_FIELDS: ClassVar[tuple[str, ...]] = ("stake", "payout", "balance")

    def money(self) -> dict[str, RawField]:
        return {name: getattr(self, name) for name in self.MONEY_FIELDS}

    def min_confidence(self) -> float:
        fields = [self.date, self.description, self.stake, self.payout, self.result]
        return min((f.confidence for f in fields if f), default=0.0)


class ExtractionResult(BaseModel):
    backend: str
    model: str | None = None
    passes: int
    canvas_dir: str
    rows: list[RawRow]

    @property
    def flagged(self) -> list[RawRow]:
        return [row for row in self.rows if row.flags]
