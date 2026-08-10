"""Utility condivise per i test: un RatesProvider offline pre-popolato."""

import os
import sys
from datetime import date
from decimal import Decimal

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fiscoib.fx.rates import RatesProvider  # noqa: E402


@pytest.fixture
def rates(tmp_path):
    """Provider offline con cambi noti pre-caricati (nessuna rete)."""
    db = os.path.join(tmp_path, "rates.sqlite")
    rp = RatesProvider(db_path=db, offline=True)

    # daily: 1 EUR = X USD
    daily = {
        "2024-01-15": "1.09",
        "2024-06-20": "1.07",
        "2024-01-10": "1.10",
        "2024-03-15": "1.08",
        "2024-09-01": "1.06",
        "2024-11-16": "1.08",
        "2025-01-15": "1.03",
        "2025-06-20": "1.05",
    }
    for d, r in daily.items():
        rp.preload(d, "USD", "daily", Decimal(r), "test")

    # monthly avg: 1 EUR = X USD
    monthly = {
        ("2024-12"): "1.0479",
        ("2024-01"): "1.09",
        ("2024-06"): "1.07",
        ("2024-09"): "1.06",
        ("2025-12"): "1.04",
    }
    for k, r in monthly.items():
        rp.preload(k, "USD", "monthly", Decimal(r), "test")

    return rp
