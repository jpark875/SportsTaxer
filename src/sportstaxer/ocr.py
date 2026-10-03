"""Classical OCR fallback for runs with no network or API key. Reads amounts well and
column membership badly; review its output before trusting it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from PIL import Image

from sportstaxer.adapters import Adapter
from sportstaxer.extract import ExtractionError, ModelField, ModelResponse, ModelRow, Tile

# Lines further apart than this belong to different bets. Tuned on the synthetic
# fixture's 96px row pitch; retune against a real book.
ROW_GAP_PX = 28

MONEY = re.compile(r"[-(]?\s*[$£€]\s?\d[\d,]*(?:\.\d{2})?\)?")
DATE = re.compile(
    r"\b(\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{2,4}|"
    r"[A-Z][a-z]{2}\s+\d{1,2}(?:,\s*\d{4})?)\b"
)


@dataclass
class Line:
    text: str
    top: int
    bottom: int
    confidence: float


class TesseractBackend:
    def __init__(self):
        self.name = "ocr"

    def read_tile(self, tile: Tile, image: Image.Image, adapter: Adapter) -> ModelResponse:
        return ModelResponse(rows=read_rows(image, adapter))


def _lines(image: Image.Image) -> list[Line]:
    try:
        import pytesseract
    except ImportError as exc:
        raise ExtractionError(
            "the ocr backend needs pytesseract and a tesseract binary on PATH"
        ) from exc

    try:
        data = pytesseract.image_to_data(image, output_type=pytesseract.Output.DICT)
    except pytesseract.TesseractNotFoundError as exc:
        raise ExtractionError("tesseract is not installed or not on PATH") from exc

    grouped: dict[tuple[int, int, int], list[int]] = {}
    for i, text in enumerate(data["text"]):
        if not text.strip():
            continue
        key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
        grouped.setdefault(key, []).append(i)

    lines = []
    for indexes in grouped.values():
        words = [data["text"][i] for i in indexes]
        confidences = [float(data["conf"][i]) for i in indexes if float(data["conf"][i]) >= 0]
        top = min(data["top"][i] for i in indexes)
        bottom = max(data["top"][i] + data["height"][i] for i in indexes)
        lines.append(
            Line(
                text=" ".join(words),
                top=top,
                bottom=bottom,
                confidence=(sum(confidences) / len(confidences) / 100) if confidences else 0.0,
            )
        )
    return sorted(lines, key=lambda line: line.top)


def _group_rows(lines: list[Line]) -> list[list[Line]]:
    rows: list[list[Line]] = []
    for line in lines:
        if rows and line.top - rows[-1][-1].bottom <= ROW_GAP_PX:
            rows[-1].append(line)
        else:
            rows.append([line])
    return rows


def _labelled_amount(text: str, labels: list[str]) -> str | None:
    lowered = text.lower()
    for label in labels:
        position = lowered.find(label.lower())
        if position < 0:
            continue
        match = MONEY.search(text, position)
        if match:
            return match.group(0).replace(" ", "")
    return None


def _first_word_of(text: str, words: list[str]) -> str | None:
    lowered = text.lower()
    for word in words:
        if word.lower() in lowered:
            return word
    return None


def read_rows(image: Image.Image, adapter: Adapter) -> list[ModelRow]:
    """Group OCR lines into bet rows and label the fields from adapter terminology."""
    terms = adapter.terminology
    rows = []

    for group in _group_rows(_lines(image)):
        text = " ".join(line.text for line in group)
        confidence = min(line.confidence for line in group)
        amounts = MONEY.findall(text)

        stake = _labelled_amount(text, terms.stake)
        payout = _labelled_amount(text, terms.payout)
        if stake is None and payout is None and len(amounts) == 1:
            # An unlabelled single amount is more likely the stake than the return, but
            # it is a guess, so it carries the guess's confidence rather than the OCR's.
            stake, confidence = amounts[0].strip().replace(" ", ""), min(confidence, 0.3)

        date_match = DATE.search(text)
        result = _first_word_of(text, terms.won + terms.lost + terms.push + terms.cashout)
        description = max(
            (line.text for line in group if not MONEY.search(line.text)),
            key=len,
            default=text,
        )

        rows.append(
            ModelRow(
                date=ModelField(
                    value=date_match.group(0) if date_match else None, confidence=confidence
                ),
                description=ModelField(value=description, confidence=confidence),
                bet_type=ModelField(value=None, confidence=0.0),
                stake=ModelField(value=stake, confidence=confidence if stake else 0.0),
                payout=ModelField(value=payout, confidence=confidence if payout else 0.0),
                result=ModelField(value=result, confidence=confidence if result else 0.0),
                balance=ModelField(value=None, confidence=0.0),
                y_top=group[0].top,
                y_bottom=group[-1].bottom,
            )
        )
    return rows
