"""Conservative monetary reservations across processes, teams and runs."""

import math
from datetime import datetime, timezone

from sqlalchemy import select

from .database import Budget, Reservation
from .service import identifier


class BudgetExhausted(ValueError):
    """All shared caps are checked before any paid request."""


def reserve(db, team, run_id, amount, run_cap=0.5, aggregate_cap=5.0):
    if (
        not math.isfinite(amount)
        or amount <= 0
        or not 0 <= run_cap <= 0.5
        or not 0 < aggregate_cap <= 5
    ):
        raise ValueError("Invalid inference reservation or cap")
    day = datetime.now(timezone.utc).date().isoformat()
    specs = [
        ("validation-v2", aggregate_cap),
        ("team:" + team + ":" + day, 5.0),
        ("run:" + run_id, run_cap),
    ]
    # One persistent global row serializes budget initialization and all reservations.
    global_row = db.scalar(
        select(Budget).where(Budget.id == "validation-v2").with_for_update()
    )
    if global_row is None:
        raise ValueError("Budget not initialized by migration/bootstrap")
    for key, cap in specs:
        row = db.scalar(select(Budget).where(Budget.id == key).with_for_update())
        if row is None:
            row = Budget(id=key, cap=cap, reserved=0.0)
            db.add(row)
        cap = min(cap, row.cap)
        if row.reserved + amount > cap + 1e-12:
            raise BudgetExhausted("Inference budget exhausted")
        row.reserved += amount
    reservation = Reservation(id=identifier(), run_id=run_id, amount=amount)
    db.add(reservation)
    return reservation.id


def settle(db, identifier, actual, metadata):
    row = db.scalar(
        select(Reservation).where(Reservation.id == identifier).with_for_update()
    )
    if row is None or not math.isfinite(actual) or actual < 0 or actual > row.amount:
        raise ValueError("Invalid inference settlement")
    if row.actual is not None and row.actual != actual:
        raise ValueError("Conflicting inference settlement")
    row.actual = actual
    row.metadata_json = metadata
    # Reservations are intentionally never refunded, including ambiguous requests.
