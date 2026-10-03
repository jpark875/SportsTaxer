from decimal import Decimal

import pytest

from sportstaxer.config import CropBox
from sportstaxer.parse import LedgerRow, Result
from sportstaxer.reconcile import ReconcileError, reconcile
from sportstaxer.stitch import CanvasManifest, FramePlacement


def manifest(gap: bool = False) -> CanvasManifest:
    placement = FramePlacement(
        index=1, frame="f.png", offset=0, gap=gap, gap_reason="x" if gap else None
    )
    return CanvasManifest(
        frames_dir=".",
        crop=CropBox(),
        width=10,
        height=10,
        frame_count=1,
        placements=[placement],
        segments=[],
    )


def row(net, result=Result.WON, flags=None) -> LedgerRow:
    return LedgerRow(
        result=result, net=Decimal(net) if net is not None else None, flags=flags or []
    )


def test_balanced_run():
    rows = [row("25"), row("-10", Result.LOST)]
    report = reconcile(rows, manifest(), Decimal("100"), Decimal("115"))
    assert report.status == "balanced"
    assert report.difference == 0
    assert report.expected_closing == Decimal("115")


def test_mismatch_reports_the_difference():
    report = reconcile([row("25")], manifest(), Decimal("100"), Decimal("120"))
    assert report.status == "mismatch"
    assert report.difference == Decimal("-5")
    assert "off by" in report.notes[0]


def test_unknown_net_prevents_balanced():
    report = reconcile([row("25"), row(None)], manifest(), Decimal("0"), Decimal("25"))
    assert report.status == "mismatch"
    assert any("no computable net" in n for n in report.notes)


def test_pending_rows_are_counted_not_summed():
    report = reconcile(
        [row("25"), row(None, Result.PENDING)], manifest(), Decimal("0"), Decimal("25")
    )
    assert report.status == "balanced"
    assert report.pending == 1


def test_without_balances_the_run_is_unverified():
    report = reconcile([row("25", flags=["low confidence: stake"])], manifest())
    assert report.status == "unverified"
    assert report.flagged == 1


def test_gaps_are_fatal():
    with pytest.raises(ReconcileError, match="gap"):
        reconcile([row("25")], manifest(gap=True), Decimal("0"), Decimal("25"))


def test_balances_come_as_a_pair():
    with pytest.raises(ReconcileError, match="together"):
        reconcile([row("25")], manifest(), opening=Decimal("0"))
