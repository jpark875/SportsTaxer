from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from sportstaxer.adapters import Currency, load_adapter
from sportstaxer.config import Config
from sportstaxer.parse import (
    ParseError,
    Result,
    classify_result,
    compute_net,
    parse_date,
    parse_money,
    parse_row,
)
from sportstaxer.schema import BBox, RawField, RawRow

ADAPTER = load_adapter("synthbook", Path("adapters"))


def raw(**values) -> RawRow:
    fields = {k: RawField(value=v, confidence=0.95) for k, v in values.items()}
    return RawRow(bbox=BBox(x=0, y=10, width=700, height=90), **fields)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("$1,234.50", "1234.50"),
        ("$5", "5"),
        ("-$12.00", "-12.00"),
        ("($12.00)", "-12.00"),
        ("+ $3.10", "3.10"),
        ("", None),
        (None, None),
    ],
)
def test_money(text, expected):
    result = parse_money(text, Currency())
    assert result == (Decimal(expected) if expected is not None else None)


def test_money_rejects_junk():
    with pytest.raises(ParseError):
        parse_money("$12.5x", Currency())


def test_money_with_european_separators():
    currency = Currency(symbol="€", thousands=".", decimal=",")
    assert parse_money("€1.234,50", currency) == Decimal("1234.50")


def test_date_with_year():
    assert parse_date("2025-03-04", ["%Y-%m-%d"], None) == date(2025, 3, 4)


def test_date_without_year_uses_default_and_handles_leap_day():
    assert parse_date("Feb 29", ["%b %d"], 2024) == date(2024, 2, 29)


def test_date_without_year_or_default_fails():
    with pytest.raises(ParseError):
        parse_date("Mar 4", ["%b %d"], None)


def test_result_labels_are_case_insensitive():
    assert classify_result("WON", ADAPTER) == Result.WON
    assert classify_result("Cash Out", ADAPTER) == Result.CASHOUT
    assert classify_result("settled - lost", ADAPTER) == Result.LOST
    assert classify_result("mystery", ADAPTER) == Result.UNKNOWN


@pytest.mark.parametrize(
    ("result", "stake", "payout", "includes", "net"),
    [
        (Result.WON, "10", "25", False, "25"),
        (Result.WON, "10", "35", True, "25"),
        (Result.LOST, "10", "0", False, "-10"),
        (Result.PUSH, "10", "10", True, "0"),
        (Result.CASHOUT, "10", "4", False, "4"),
        (Result.DEPOSIT, "50", None, False, "50"),
        (Result.WITHDRAWAL, "50", None, False, "-50"),
    ],
)
def test_net(result, stake, payout, includes, net):
    stake_value = Decimal(stake)
    payout_value = Decimal(payout) if payout is not None else None
    assert compute_net(result, stake_value, payout_value, includes) == Decimal(net)


def test_net_is_unknown_for_pending_and_missing_amounts():
    assert compute_net(Result.PENDING, Decimal("5"), None, False) is None
    assert compute_net(Result.WON, Decimal("5"), None, False) is None


def test_clean_row_has_no_flags():
    row = parse_row(
        raw(
            date="2025-03-04",
            description="Lakers v Heat",
            stake="$10.00",
            payout="$25.00",
            result="Won",
        ),
        ADAPTER,
        min_confidence=0.8,
        year=None,
    )
    assert row.flags == []
    assert row.net == Decimal("25.00")
    assert row.date == date(2025, 3, 4)


def test_bad_fields_are_flagged_not_dropped():
    row = parse_row(
        raw(date="soon", description="x", stake="$1o.00", payout="$1.00", result="Odd"),
        ADAPTER,
        min_confidence=0.8,
        year=None,
    )
    assert row.date is None
    assert row.stake is None
    assert any("unrecognised date" in f for f in row.flags)
    assert any(f.startswith("stake:") for f in row.flags)
    assert any("unrecognised result" in f for f in row.flags)


def test_low_confidence_and_carried_flags_reach_the_row():
    source = raw(date="2025-03-04", description="x", stake="$1.00", payout="$0.00", result="Lost")
    source.stake.confidence = 0.0
    source.flags.append("money disagreement: stake $1.00 vs $7.00")
    row = parse_row(source, ADAPTER, min_confidence=0.8, year=None)
    assert "low confidence: stake" in row.flags
    assert row.flags[0].startswith("money disagreement")
    assert row.needs_review


def test_config_defaults():
    assert Config().ledger.min_confidence == 0.8
