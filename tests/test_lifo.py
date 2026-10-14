"""Test del matching LIFO (art. 67 c.1-bis TUIR)."""

from decimal import Decimal

from fiscoib.engines.lots import build_closures
from fiscoib.warnings import WarningCollector
from helpers import cfd, etf, stock, trade


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


def test_etf_costo_medio_ponderato():
    """Quote OICR: criterio costo medio ponderato, NON LIFO.

    100 @50 + 100 @70 -> medio 60. Vendita di 50 chiude al medio corrente (60).
    Nuovo acquisto 50 @100 ricalcola il medio progressivamente:
    (150*60 + 50*100)/200 = 70. La vendita successiva chiude a 70.
    """
    e = etf()
    trades = [
        trade(e, "2024-01-10", "BUY", 100, 50, currency="EUR"),
        trade(e, "2024-03-15", "BUY", 100, 70, currency="EUR"),
        trade(e, "2024-06-20", "SELL", 50, 90, currency="EUR"),
        trade(e, "2024-09-01", "BUY", 50, 100, currency="EUR"),
        trade(e, "2024-11-16", "SELL", 50, 120, currency="EUR"),
    ]
    closures, book = build_closures(trades, [])

    # Ogni vendita genera UNA chiusura al costo medio (niente split per lotto).
    assert len(closures) == 2
    c0, c1 = closures
    assert c0.qty == Decimal("50") and c0.open_unit_price == Decimal("60")
    assert c0.close_unit_price == Decimal("90")
    assert c1.qty == Decimal("50") and c1.open_unit_price == Decimal("70")
    assert c1.close_unit_price == Decimal("120")

    # Residuo: 150 quote al medio 70.
    remaining = book.open_lots(e.key())
    assert sum(l.qty for l in remaining) == Decimal("150")
    assert remaining[0].unit_price == Decimal("70")


def test_azione_non_oicr_resta_lifo():
    """Un titolo azionario (subCategory != ETF) usa ancora il LIFO."""
    aapl = stock()
    assert not aapl.is_fund
    trades = [
        trade(aapl, "2024-01-10", "BUY", 10, 100),
        trade(aapl, "2024-03-15", "BUY", 10, 120),
        trade(aapl, "2024-06-20", "SELL", 10, 130),
    ]
    closures, _ = build_closures(trades, [])
    assert len(closures) == 1
    # LIFO: si cede il lotto più recente (@120), non il medio (@110).
    assert closures[0].open_unit_price == Decimal("120")


def test_short_spurio_segnalato():
    """Vendita non chiusa di un titolo non-CFD -> warning SHORT_SPURIO."""
    aapl = stock()
    w = WarningCollector()
    trades = [trade(aapl, "2024-03-15", "SELL", 10, 200)]
    build_closures(trades, [], warnings=w)

    matches = [x for x in w if x.code == "SHORT_SPURIO"]
    assert len(matches) == 1
    assert "10" in matches[0].message and "AAPL" in matches[0].message


def test_short_spurio_non_emesso_per_cfd():
    """Short residuo su CFD: lecito, nessun warning SHORT_SPURIO."""
    c = cfd()
    w = WarningCollector()
    trades = [trade(c, "2024-03-15", "SELL", 10, 200)]
    build_closures(trades, [], warnings=w)
    assert not [x for x in w if x.code == "SHORT_SPURIO"]


def test_same_day_open_prima_di_close():
    """A parità di data, openCloseIndicator 'O' viene elaborato prima di 'C'."""
    aapl = stock()
    w = WarningCollector()
    # Nel Flex la vendita compare prima, ma è una chiusura ('C'): l'acquisto
    # di apertura ('O') dello stesso giorno va processato per primo.
    trades = [
        trade(aapl, "2024-06-20", "SELL", 10, 130, open_close="C"),
        trade(aapl, "2024-06-20", "BUY", 10, 100, open_close="O"),
    ]
    closures, _ = build_closures(trades, [], warnings=w)
    assert len(closures) == 1
    assert closures[0].is_long is True
    assert closures[0].open_unit_price == Decimal("100")
    assert closures[0].close_unit_price == Decimal("130")
    assert not [x for x in w if x.code == "SHORT_SPURIO"]
