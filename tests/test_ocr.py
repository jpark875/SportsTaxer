from pathlib import Path

import pytest

from sportstaxer import ocr
from sportstaxer.adapters import load_adapter
from sportstaxer.ocr import Line, read_rows

ADAPTER = load_adapter("synthbook", Path("adapters"))


@pytest.fixture
def lines(monkeypatch):
    def install(values: list[Line]):
        monkeypatch.setattr(ocr, "_lines", lambda image: values)

    return install


def line(text: str, top: int, height: int = 18, confidence: float = 0.9) -> Line:
    return Line(text=text, top=top, bottom=top + height, confidence=confidence)


def test_lines_close_together_become_one_row(lines):
    lines(
        [
            line("Lakers v Heat Moneyline", 10),
            line("2025-03-04 Won Stake $25.00 Payout $47.50", 40),
            line("Celtics v Bulls Spread", 140),
            line("2025-03-05 Lost Stake $10.00 Payout $0.00", 170),
        ]
    )

    rows = read_rows(None, ADAPTER)

    assert len(rows) == 2
    assert rows[0].stake.value == "$25.00"
    assert rows[0].payout.value == "$47.50"
    assert rows[0].date.value == "2025-03-04"
    assert rows[0].result.value == "won"
    assert rows[0].description.value == "Lakers v Heat Moneyline"
    assert rows[1].stake.value == "$10.00"


def test_row_bounds_span_all_its_lines(lines):
    lines([line("Lakers v Heat", 10), line("Stake $25.00", 40, height=20)])
    (row,) = read_rows(None, ADAPTER)
    assert (row.y_top, row.y_bottom) == (10, 60)


def test_alternate_stake_wording_is_recognised(lines):
    lines([line("Risk $30.00 to win $60.00", 10)])
    (row,) = read_rows(None, ADAPTER)
    assert row.stake.value == "$30.00"
    # "to win" is a potential return, not a payout, so it must not land in payout.
    assert row.payout.value is None


def test_unlabelled_single_amount_is_a_low_confidence_guess(lines):
    lines([line("Lakers v Heat $25.00", 10, confidence=0.95)])
    (row,) = read_rows(None, ADAPTER)
    assert row.stake.value == "$25.00"
    assert row.stake.confidence == 0.3


def test_row_confidence_is_the_worst_line_in_it(lines):
    lines([line("Lakers v Heat", 10, confidence=0.4), line("Stake $25.00", 40, confidence=0.99)])
    (row,) = read_rows(None, ADAPTER)
    assert row.description.confidence == 0.4


def test_missing_fields_carry_zero_confidence(lines):
    lines([line("Lakers v Heat Moneyline", 10)])
    (row,) = read_rows(None, ADAPTER)
    assert row.payout.value is None
    assert row.payout.confidence == 0.0
    assert row.result.confidence == 0.0
