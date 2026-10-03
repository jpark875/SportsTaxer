"""Stage 5: check the ledger against the recording's opening and closing balances."""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

from sportstaxer.parse import LedgerRow, Result
from sportstaxer.stitch import CanvasManifest

Status = Literal["balanced", "mismatch", "unverified"]


class ReconcileError(Exception):
    pass


class Reconciliation(BaseModel):
    status: Status
    opening: Decimal | None = None
    closing: Decimal | None = None
    expected_closing: Decimal | None = None
    difference: Decimal | None = None
    rows: int
    pending: int = 0
    flagged: int = 0
    notes: list[str] = Field(default_factory=list)


def reconcile(
    rows: list[LedgerRow],
    manifest: CanvasManifest,
    opening: Decimal | None = None,
    closing: Decimal | None = None,
    tolerance: Decimal = Decimal("0.005"),
) -> Reconciliation:
    """Compare opening plus every row's net against the closing balance.

    A canvas with gaps is refused outright: the missing content is unrecorded, so any
    comparison would be meaningless. Unknown nets are reported, never assumed zero.
    """
    if manifest.gaps:
        raise ReconcileError(
            f"canvas has {len(manifest.gaps)} gap(s); re-record the run with more overlap"
        )
    if (opening is None) != (closing is None):
        raise ReconcileError("opening and closing balances must be given together")

    notes: list[str] = []
    pending = sum(1 for row in rows if row.result == Result.PENDING)
    flagged = sum(1 for row in rows if row.needs_review)
    unknown = [row for row in rows if row.net is None and row.result != Result.PENDING]
    if unknown:
        notes.append(f"{len(unknown)} row(s) have no computable net and are excluded from the sum")
    if pending:
        notes.append(f"{pending} pending bet(s) are excluded; their stakes may already be held")

    if opening is None or closing is None:
        notes.append("no balances supplied; totals were not verified")
        return Reconciliation(
            status="unverified", rows=len(rows), pending=pending, flagged=flagged, notes=notes
        )

    expected = opening + sum((row.net for row in rows if row.net is not None), Decimal("0"))
    difference = closing - expected
    balanced = abs(difference) <= tolerance and not unknown
    if abs(difference) > tolerance:
        notes.append(f"closing balance is off by {difference:+,.2f}")
    return Reconciliation(
        status="balanced" if balanced else "mismatch",
        opening=opening,
        closing=closing,
        expected_closing=expected,
        difference=difference,
        rows=len(rows),
        pending=pending,
        flagged=flagged,
        notes=notes,
    )
