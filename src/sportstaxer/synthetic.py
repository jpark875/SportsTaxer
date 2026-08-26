"""Synthetic scroll fixtures: a tall fake ledger image, sliced into overlapping frames
with known offsets.

Stitching is checked against these for pixel-exact reconstruction, so the generator has
to be deterministic for a given seed and has to reproduce the things that break
correlation in real recordings: sticky chrome that never moves and a clock that changes
every frame.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from PIL import Image, ImageDraw, ImageFont

TEAMS = [
    "Lakers",
    "Celtics",
    "Heat",
    "Knicks",
    "Bulls",
    "Suns",
    "Nuggets",
    "Mavericks",
    "Chiefs",
    "Eagles",
    "Ravens",
    "49ers",
    "Bills",
    "Cowboys",
    "Packers",
    "Lions",
]
MARKETS = ["Moneyline", "Spread -3.5", "Over 214.5", "Under 47.5", "Player Points 22.5"]
RESULTS = ["Won", "Lost", "Push", "Cash Out"]


@dataclass(frozen=True)
class SyntheticRow:
    date: str
    description: str
    stake: float
    payout: float
    result: str


@dataclass(frozen=True)
class SyntheticCapture:
    """A canvas plus the frames cut from it and the offset each frame was cut at."""

    canvas: Image.Image
    frames: list[Image.Image]
    offsets: list[int]
    rows: list[SyntheticRow]
    header_height: int
    footer_height: int


def _font(size: int) -> ImageFont.ImageFont:
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # Pillow < 10.1
        return ImageFont.load_default()


def make_rows(count: int, seed: int = 0) -> list[SyntheticRow]:
    rng = random.Random(seed)
    rows = []
    for i in range(count):
        stake = round(rng.uniform(5, 250), 2)
        result = rng.choice(RESULTS)
        payout = 0.0 if result == "Lost" else round(stake * rng.uniform(1.1, 3.4), 2)
        rows.append(
            SyntheticRow(
                date=f"2025-{rng.randint(1, 12):02d}-{rng.randint(1, 28):02d}",
                description=f"{rng.choice(TEAMS)} v {rng.choice(TEAMS)} {rng.choice(MARKETS)} #{i}",
                stake=stake,
                payout=payout,
                result=result,
            )
        )
    return rows


def render_canvas(
    rows: list[SyntheticRow],
    width: int = 720,
    row_height: int = 96,
) -> Image.Image:
    canvas = Image.new("RGB", (width, row_height * len(rows)), (18, 18, 20))
    draw = ImageDraw.Draw(canvas)
    title_font, detail_font = _font(20), _font(15)

    for i, row in enumerate(rows):
        top = i * row_height
        # Alternating row backgrounds give correlation something to lock onto even
        # where the text happens to repeat.
        draw.rectangle(
            [0, top, width, top + row_height - 1],
            fill=(30, 30, 34) if i % 2 else (24, 24, 28),
        )
        draw.line([0, top, width, top], fill=(60, 60, 66))
        draw.text((16, top + 10), row.description, font=title_font, fill=(232, 232, 236))
        draw.text(
            (16, top + 44), f"{row.date}  {row.result}", font=detail_font, fill=(150, 150, 158)
        )
        draw.text(
            (width - 210, top + 10),
            f"Stake ${row.stake:,.2f}",
            font=detail_font,
            fill=(200, 200, 206),
        )
        draw.text(
            (width - 210, top + 44),
            f"Payout ${row.payout:,.2f}",
            font=detail_font,
            fill=(120, 200, 140),
        )
    return canvas


def plan_offsets(canvas_height: int, frame_height: int, step: int) -> list[int]:
    """Offsets for a scroll of fixed step, ending on the last full frame."""
    if frame_height > canvas_height:
        raise ValueError("frame_height exceeds canvas height")
    if step <= 0:
        raise ValueError("step must be positive")
    last = canvas_height - frame_height
    offsets = list(range(0, last, step))
    offsets.append(last)
    return offsets


def _draw_chrome(
    frame: Image.Image, header_height: int, footer_height: int, clock_minute: int
) -> None:
    draw = ImageDraw.Draw(frame)
    width, height = frame.size
    if header_height:
        draw.rectangle([0, 0, width, header_height], fill=(12, 12, 14))
        draw.text((16, 8), "Bet History", font=_font(18), fill=(240, 240, 244))
        # A clock that ticks every frame: unchanging chrome and changing chrome both
        # have to be cropped before correlating.
        draw.text(
            (width - 90, 8),
            f"9:{clock_minute % 60:02d}",
            font=_font(16),
            fill=(240, 240, 244),
        )
    if footer_height:
        draw.rectangle([0, height - footer_height, width, height], fill=(12, 12, 14))
        draw.text(
            (16, height - footer_height + 10),
            "Home   Bets   Account",
            font=_font(15),
            fill=(180, 180, 186),
        )


def slice_frames(
    canvas: Image.Image,
    frame_height: int,
    offsets: list[int],
    header_height: int = 0,
    footer_height: int = 0,
) -> list[Image.Image]:
    """Cut frames from the canvas at the given offsets, overlaying chrome on each.

    Chrome is drawn over the content the way a sticky header does on a real screen, so
    the pixels it covers are lost rather than shifted.
    """
    frames = []
    for i, offset in enumerate(offsets):
        if offset < 0 or offset + frame_height > canvas.height:
            raise ValueError(f"offset {offset} does not fit the canvas")
        frame = canvas.crop((0, offset, canvas.width, offset + frame_height)).copy()
        _draw_chrome(frame, header_height, footer_height, clock_minute=i)
        frames.append(frame)
    return frames


def make_capture(
    row_count: int = 40,
    frame_height: int = 640,
    step: int = 300,
    width: int = 720,
    row_height: int = 96,
    header_height: int = 0,
    footer_height: int = 0,
    seed: int = 0,
) -> SyntheticCapture:
    rows = make_rows(row_count, seed=seed)
    canvas = render_canvas(rows, width=width, row_height=row_height)
    offsets = plan_offsets(canvas.height, frame_height, step)
    frames = slice_frames(canvas, frame_height, offsets, header_height, footer_height)
    return SyntheticCapture(
        canvas=canvas,
        frames=frames,
        offsets=offsets,
        rows=rows,
        header_height=header_height,
        footer_height=footer_height,
    )
