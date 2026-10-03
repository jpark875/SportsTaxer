"""Stage 4: raw rows to typed ledger rows, applying the adapter's conventions."""

from __future__ import annotations

import datetime as dt
import re
from decimal import Decimal, InvalidOperation
from enum import StrEnum

from pydantic import BaseModel, Field

from sportstaxer.adapters import Adapter, Currency
from sportstaxer.config import Config
from sportstaxer.schema import ExtractionResult, RawField, RawRow


class Result(StrEnum):
    WON = "won"
    LOST = "lost"
    PUSH = "push"
    CASHOUT = "cashout"
    PENDING = "pending"
    DEPOSIT = "deposit"
    WITHDRAWAL = "withdrawal"
    UNKNOWN = "unknown"


class LedgerRow(BaseModel):
    date: dt.date | None = None
    description: str = ""
    bet_type: str | None = None
    result: Result = Result.UNKNOWN
    stake: Decimal | None = None
    payout: Decimal | None = None
    # Effect on the account balance; None when it cannot be determined (pending bets).
    net: Decimal | None = None
    balance: Decimal | None = None
    segment: int = 0
    canvas_y: int = 0
    flags: list[str] = Field(default_factory=list)

    @property
    def needs_review(self) -> bool:
        return bool(self.flags)


class ParseError(Exception):
    pass


def parse_money(text: str | None, currency: Currency) -> Decimal | None:
    """Parse an amount as written on screen. Returns None for empty text, raises on junk."""
    if text is None or not text.strip():
        return None
    cleaned = text.strip().replace(currency.symbol, "").replace(" ", "")
    negative = False
    if cleaned.startswith("(") and cleaned.endswith(")"):
        if not currency.parentheses_negative:
            raise ParseError(f"unexpected parentheses in {text!r}")
        negative, cleaned = True, cleaned[1:-1]
    if cleaned.startswith("-"):
        negative, cleaned = True, cleaned[1:]
    elif cleaned.startswith("+"):
        cleaned = cleaned[1:]
    cleaned = cleaned.replace(currency.symbol, "").replace(currency.thousands, "")
    if currency.decimal != ".":
        cleaned = cleaned.replace(currency.decimal, ".")
    if not re.fullmatch(r"\d+(\.\d+)?", cleaned):
        raise ParseError(f"not an amount: {text!r}")
    try:
        value = Decimal(cleaned)
    except InvalidOperation as exc:
        raise ParseError(f"not an amount: {text!r}") from exc
    return -value if negative else value


def parse_date(text: str | None, formats: list[str], default_year: int | None) -> dt.date | None:
    if text is None or not text.strip():
        return None
    text = text.strip()
    for fmt in formats:
        if "%Y" in fmt or "%y" in fmt:
            candidates = [(text, fmt)]
        elif default_year is not None:
            # Appending the year keeps Feb 29 parseable, which a bare 1900 default is not.
            candidates = [(f"{text} {default_year}", f"{fmt} %Y")]
        else:
            continue
        for value, pattern in candidates:
            try:
                return dt.datetime.strptime(value, pattern).date()
            except ValueError:
                continue
    raise ParseError(f"unrecognised date: {text!r}")


def classify_result(label: str | None, adapter: Adapter) -> Result:
    if not label or not label.strip():
        return Result.UNKNOWN
    wanted = label.strip().lower()
    terms = adapter.terminology
    table = (
        (Result.CASHOUT, terms.cashout),
        (Result.WON, terms.won),
        (Result.LOST, terms.lost),
        (Result.PUSH, terms.push),
        (Result.PENDING, terms.pending),
        (Result.DEPOSIT, terms.deposit),
        (Result.WITHDRAWAL, terms.withdrawal),
    )
    for result, labels in table:
        if wanted in (item.lower() for item in labels):
            return result
    return Result.UNKNOWN


def compute_net(
    result: Result, stake: Decimal | None, payout: Decimal | None, includes_stake: bool
) -> Decimal | None:
    """Effect on the balance. Needs the amounts the result implies; otherwise None."""
    if result == Result.PUSH:
        return Decimal("0")
    if result == Result.LOST:
        return -stake if stake is not None else None
    if result in (Result.WON, Result.CASHOUT):
        if payout is None:
            return None
        if not includes_stake:
            return payout
        return payout - stake if stake is not None else None
    if result == Result.DEPOSIT:
        amount = stake if stake is not None else payout
        return abs(amount) if amount is not None else None
    if result == Result.WITHDRAWAL:
        amount = stake if stake is not None else payout
        return -abs(amount) if amount is not None else None
    return None


def _field_text(field: RawField) -> str | None:
    return field.value.strip() if field and field.value else None


def parse_row(row: RawRow, adapter: Adapter, min_confidence: float, year: int | None) -> LedgerRow:
    flags = list(row.flags)

    def money(name: str) -> Decimal | None:
        try:
            return parse_money(_field_text(getattr(row, name)), adapter.currency)
        except ParseError as exc:
            flags.append(f"{name}: {exc}")
            return None

    try:
        when = parse_date(_field_text(row.date), adapter.date_formats, year)
    except ParseError as exc:
        flags.append(str(exc))
        when = None
    if when is None and not any(f.startswith("unrecognised date") for f in flags):
        flags.append("missing date")

    result = classify_result(_field_text(row.result), adapter)
    if result == Result.UNKNOWN:
        flags.append(f"unrecognised result: {_field_text(row.result) or 'none'}")

    stake, payout, balance = money("stake"), money("payout"), money("balance")
    net = compute_net(result, stake, payout, adapter.payout_includes_stake)
    if net is None and result not in (Result.PENDING, Result.UNKNOWN):
        flags.append("cannot compute net: missing amount")

    weak = [
        name
        for name in ("date", "description", "stake", "payout", "result")
        if (field := getattr(row, name)) and field.confidence < min_confidence
    ]
    if weak:
        flags.append(f"low confidence: {', '.join(weak)}")

    return LedgerRow(
        date=when,
        description=_field_text(row.description) or "",
        bet_type=_field_text(row.bet_type),
        result=result,
        stake=stake,
        payout=payout,
        net=net,
        balance=balance,
        segment=row.segment,
        canvas_y=row.bbox.y,
        flags=flags,
    )


def parse_extraction(
    extraction: ExtractionResult, adapter: Adapter, config: Config
) -> list[LedgerRow]:
    """Convert every extracted row. Rows are never dropped, only flagged."""
    rows = [
        parse_row(raw, adapter, config.ledger.min_confidence, config.ledger.assume_year)
        for raw in extraction.rows
    ]
    seen: dict[tuple, int] = {}
    for index, row in enumerate(rows):
        key = (row.date, row.description, row.stake, row.payout, row.result)
        if key in seen:
            row.flags.append(f"possible duplicate of row {seen[key] + 1}")
        else:
            seen[key] = index
    return rows
