"""Test del matching LIFO (art. 67 c.1-bis TUIR)."""

from decimal import Decimal

from fiscoib.engines.lots import build_closures
from helpers import stock, trade


def test_lifo_multi_lotto_vendita_parziale():
    """Esempio ricerca 5.1: 3 acquisti + vendita parziale di 40.

    LIFO: si cedono prima le 20 del lotto C (@110), poi 20 del lotto B (@120).
    """
    aapl = stock()
    trades = [
        trade(aapl, "2024-01-10", "BUY", 50, 100),
        trade(aapl, "2024-03-15", "BUY", 30, 120),
        trade(aapl, "2024-06-20", "BUY", 20, 110),
        trade(aapl, "2024-09-01", "SELL", 40, 130),
    ]
    closures, book = build_closures(trades, [])

    assert len(closures) == 2
    # Ordine di chiusura LIFO: prima il lotto più recente (C @110).
    c0, c1 = closures
    assert c0.qty == Decimal("20") and c0.open_unit_price == Decimal("110")
    assert c1.qty == Decimal("20") and c1.open_unit_price == Decimal("120")
    assert all(c.close_unit_price == Decimal("130") for c in closures)

    # Lotti residui: A 50@100 e B 10@120.
    remaining = book.open_lots(aapl.key())
    tot_qty = sum(l.qty for l in remaining)
    assert tot_qty == Decimal("60")


def test_short_apertura_e_chiusura():
    """Vendita allo scoperto poi riacquisto: una chiusura short."""
    aapl = stock()
    trades = [
        trade(aapl, "2024-03-15", "SELL", 10, 200),   # apre short
        trade(aapl, "2024-06-20", "BUY", 10, 180),    # chiude short
    ]
    closures, _ = build_closures(trades, [])
    assert len(closures) == 1
    c = closures[0]
    assert c.is_long is False
    assert c.open_unit_price == Decimal("200")   # vendita allo scoperto
    assert c.close_unit_price == Decimal("180")  # riacquisto
