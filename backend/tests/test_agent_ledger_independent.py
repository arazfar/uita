"""Real SQLite concurrency/restart boundaries, never paid inference."""
from concurrent.futures import ThreadPoolExecutor
import sqlite3
from threading import Barrier

import pytest

from uita.provider import ProviderError, SpendLedger


def records(path):
    with sqlite3.connect(path) as connection:
        return connection.execute('SELECT id,reserved_usd,actual_usd FROM inference_reservations').fetchall()


def test_concurrent_aggregate_reservations_cannot_overcommit(tmp_path):
    path = str(tmp_path/'concurrent.sqlite')
    SpendLedger(path, cap=.05)
    barrier = Barrier(8)

    def reserve(index):
        ledger = SpendLedger(path, cap=.05)
        barrier.wait(timeout=5)
        try:
            return ledger.reserve(.03, f'job-{index}', .04)
        except ProviderError:
            return None

    with ThreadPoolExecutor(max_workers=8) as pool:
        result = list(pool.map(reserve, range(8)))
    assert sum(value is not None for value in result) == 1
    assert len(records(path)) == 1


def test_per_job_cap_survives_reopening_and_does_not_charge_failed_reservation(tmp_path):
    path = str(tmp_path/'jobs.sqlite')
    first = SpendLedger(path, cap=.05)
    first.reserve(.012, 'a', .02)
    reopened = SpendLedger(path, cap=.05)
    with pytest.raises(ProviderError, match='Per-job'):
        reopened.reserve(.012, 'a', .02)
    reopened.reserve(.012, 'b', .02)
    assert len(records(path)) == 2
    assert sum(row[1] for row in records(path)) == pytest.approx(.024)


def test_original_aggregate_cap_cannot_be_increased_on_restart(tmp_path):
    path = str(tmp_path/'immutable-cap.sqlite')
    first = SpendLedger(path, cap=.02)
    first.reserve(.015)
    reopened = SpendLedger(path, cap=.05)
    assert reopened.cap == .02
    with pytest.raises(ProviderError):
        reopened.reserve(.006)


def test_actual_cost_is_idempotent_and_does_not_release_ambiguous_reservation(tmp_path):
    path = str(tmp_path/'actual.sqlite')
    ledger = SpendLedger(path, cap=.05)
    reservation = ledger.reserve(.04)
    ledger.record_actual(reservation, .001)
    ledger.record_actual(reservation, .001)
    assert records(path) == [(reservation, .04, .001)]
    with pytest.raises(ProviderError):
        ledger.reserve(.011)
    with pytest.raises(ProviderError):
        ledger.record_actual(reservation, .002)
    assert records(path) == [(reservation, .04, .001)]


@pytest.mark.parametrize('actual', [-1, float('nan'), float('inf'), .021])
def test_invalid_actual_cost_cannot_corrupt_reserved_accounting(tmp_path, actual):
    path = str(tmp_path/'invalid-actual.sqlite')
    ledger = SpendLedger(path, cap=.05)
    reservation = ledger.reserve(.02)
    with pytest.raises(ProviderError):
        ledger.record_actual(reservation, actual)
    assert records(path) == [(reservation, .02, None)]


def test_unknown_reservation_cannot_be_settled(tmp_path):
    ledger = SpendLedger(str(tmp_path/'unknown.sqlite'), cap=.05)
    with pytest.raises(ProviderError):
        ledger.record_actual('never-reserved', .001)
