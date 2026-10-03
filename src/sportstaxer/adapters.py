"""Per-sportsbook profiles. Book-specific behaviour belongs in this schema, never in
pipeline code.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field, ValidationError

from sportstaxer.config import CropBox


class AdapterError(Exception):
    pass


class Currency(BaseModel):
    symbol: str = "$"
    thousands: str = ","
    decimal: str = "."
    # Some books write negatives as (12.34).
    parentheses_negative: bool = True


class Terminology(BaseModel):
    """Book wording mapped onto the internal vocabulary, case-insensitive on whole labels."""

    stake: list[str] = ["stake", "wager", "risk", "bet"]
    payout: list[str] = ["payout", "return", "returns", "paid"]
    potential: list[str] = ["to win", "potential payout", "potential return"]
    won: list[str] = ["won", "win", "winner", "settled - won"]
    lost: list[str] = ["lost", "loss", "lose", "settled - lost"]
    push: list[str] = ["push", "tie", "void", "voided", "cancelled", "canceled", "refunded"]
    cashout: list[str] = ["cash out", "cashed out", "cashout"]
    pending: list[str] = ["pending", "open", "in progress", "live"]
    deposit: list[str] = ["deposit", "credit"]
    withdrawal: list[str] = ["withdrawal", "withdraw", "debit", "payout to bank"]


class Adapter(BaseModel):
    """One sportsbook's profile.

    `payout_includes_stake` has no default: guessing it wrong doubles or halves winnings.
    """

    model_config = {"extra": "forbid"}

    name: str
    display_name: str
    payout_includes_stake: bool
    crop: CropBox = CropBox()
    date_formats: list[str] = Field(default_factory=lambda: ["%Y-%m-%d"])
    # Year is often absent from history screens; the parser needs somewhere to get it.
    assume_year_from_filename: bool = False
    timezone: str = "local"
    currency: Currency = Currency()
    terminology: Terminology = Terminology()
    # Free text handed to the extraction model describing the screen layout.
    layout_hints: str = ""
    notes: str = ""

    @property
    def fixture_dir(self) -> str:
        return f"fixtures/{self.name}"


def load_adapter(name: str, adapters_dir: Path) -> Adapter:
    path = adapters_dir / f"{name}.yaml"
    if not path.is_file():
        available = ", ".join(sorted(a.stem for a in adapters_dir.glob("*.yaml"))) or "none"
        raise AdapterError(f"no adapter profile {name!r} in {adapters_dir} (have: {available})")

    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise AdapterError(f"adapter profile must contain a mapping: {path}")
    try:
        adapter = Adapter.model_validate(raw)
    except ValidationError as exc:
        raise AdapterError(f"invalid adapter profile {path}:\n{exc}") from exc

    if adapter.name != name:
        raise AdapterError(f"adapter {path} declares name {adapter.name!r}, expected {name!r}")
    return adapter


def list_adapters(adapters_dir: Path) -> list[str]:
    return sorted(path.stem for path in adapters_dir.glob("*.yaml"))
